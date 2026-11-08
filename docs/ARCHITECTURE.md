# Architecture and decisions

## Layout

```
src/cad/                 Python package (canonical modelling API + engine)
  part.py                Part, features, named-reference tracking, queries
  selection.py           Face/Edge selections (chainable geometric predicates)
  profile.py             2D profiles and sketch planes
  params.py              Parameter() declarations and override context
  _occ.py                the only module with dense raw-OCP helpers
  tessellate.py          BRep -> mesh + edge polylines; canonical BREP hashing
  renderer.py            software rasteriser, cameras, annotation, metadata
  export.py              STEP / STL / BREP
  study.py, fea.py       Study load cases; meshing (gmsh, in a subprocess), solving, hot spots, report
  _fea_mesh.py           the only gmsh code, run as a separate script (GPL, optional; own OCCT copy)
  fea_render.py          stress maps: colours, legend, hot-spot markers, load glyphs
  runner.py              executes a model script, collects Parts, maps errors to script lines
  project.py             cad.toml, params.toml, .cad/ revisions (atomic publish), locking
  engine.py              project sessions: build / inspect / measure / query / render / export / diff
  cli.py                 argparse CLI as a pure function main(argv, cwd, engine) -> (code, out, err)
  worker.py              JSON-lines model worker wrapping cli.main with a persistent Engine
  examples/, docs/       agent-facing examples and reference (shipped with the package)
crates/cad/              Rust: `cad` client, `cadd` daemon
evals/                   tasks, reference solutions, cadeval harness
```

## Decisions and trade-offs

**Stress analysis: gmsh + scikit-fem, not CalculiX.** Everything installs with pip on macOS and Linux
(CalculiX has no Homebrew formula and would mean shipping a Fortran binary). gmsh meshes the exact BRep
into curved 10-node tetrahedra in a separate process (it bundles its own OCCT, and it is GPL, so it is
an optional extra the core never imports); scikit-fem solves linear elasticity with quadratic elements
and pyamg multigrid. Curved elements mattered: straight-sided ones read 5-15 % high on holes and shafts.
`normal` quality solves twice, refining around the first pass's hot spots, which both sharpens peaks
and measures how far they moved (sharp inside corners never settle). Loads live in the script as
`Study` objects addressed by face references and are stored per revision as face indices; mesh
surfaces are matched back to BRep faces by exact centre of mass and area. CalculiX remains an option
for contact and nonlinear materials later.

**Kernel bindings: OCP (`cadquery-ocp`, OCCT 8.0).** Maintained, pip-installable
wheels for macOS/Linux, near-complete OCCT surface. CadQuery/build123d were not
used as the API layer: the goal is an API designed around agent failure modes
(explicit alignment, named references, structured errors, ambiguity reporting),
and owning the thin layer over OCP keeps that under our control. OCCT 8 changed
several binding details (static methods without `_s` in some modules, NCollection
lists as `OCP.collections`, `Bnd_Box.Get` unavailable) — confined to `_occ.py`.

**Renderer: NumPy software rasteriser, not OCCT V3d / VTK / wgpu (yet).** It
needs no GPU, display, EGL/OSMesa or window system, so it is identical on a
headless Linux CI box and a laptop, and it is bit-for-bit deterministic (a test
asserts this). Scanline rasterisation with a stable lexsort z-resolve, 2x
supersampling, Gouraud shading, BRep feature edges with depth-tested visibility,
and silhouettes from depth/face-id discontinuities. Cost: ~0.4–0.5 s per
1024×768 view for typical parts — acceptable because renders are cached by
geometry hash + camera + settings and meshes are reused across views. The
backend boundary is `rasterize(scene, camera, ...) -> (image, framing)`; a wgpu
backend can replace it and also deliver depth / normal / object-id buffers
(the rasteriser already computes depth and face-id buffers internally).

**Process model: Rust client + Rust daemon + Python workers.** The Rust client
starts in ~1 ms, so warm commands cost ~8–11 ms end to end versus ~620 ms for
Python + OCP start-up per standalone invocation (measured by `cadeval perf`).
The daemon owns routing, worker lifecycle, timeouts, rlimits and crash
reporting; all CAD semantics live in Python. There is exactly one CLI
implementation (`cad/cli.py`): the daemon forwards argv to a worker that calls
the same `main()` that standalone mode runs in-process, so standalone and
daemon output are identical (an integration test compares them).

**Sessions.** One worker per project root (resolved by `--project`, cwd ancestors,
then the opened project), plus a global worker for project-less commands.
Requests to one project are serialised; projects run in parallel. A worker
that dies while idle is replaced transparently; a crash during a command is
reported as `WORKER_CRASHED` (exit 6) and the next command starts a new worker,
which reloads the last successful revision from disk.

**Revisions and caches.** A build's identity is
`sha256(source files, effective parameters, cad version, kernel)`. Identical
inputs reuse the existing revision (`cached: true`). Revisions are written to a
temp dir and `rename`d into place under a file lock; HEAD changes only on
success, so a failed build never disturbs the last good model. Per revision:
canonical BREP per part (triangulation stripped, hash = geometry identity),
feature graph, named references (as face/edge indices in deterministic
exploration order, so inspect/measure/query work on reloaded geometry
without re-running the script), source snapshot, script stdout/warnings.
Mesh, render and export caches are keyed by geometry hash plus settings and
survive daemon restarts. Whole-build caching only: no feature-level incremental
regeneration (arbitrary Python cannot be safely partially re-executed).

**Named references.** Features name the faces they create (`<feature>.<role>`);
after every operation names are remapped through the OCCT history
(`Modified` / `IsDeleted`). Faces split by later features map to all pieces;
consumed faces mark the name *lost in feature X* (`REFERENCE_LOST`) instead
of silently re-binding. This is not full persistent naming (e.g. references
are not re-derived when an upstream parameter changes topology), but names are
re-established on every rebuild because the script re-runs top to bottom.

**Errors.** Every API failure is a `CadError(code, message, hint, feature,
details)`; script exceptions carry the user's file/line. Kernel failures are
diagnosed where possible (fillet retries edges individually to report which
fail and why). Non-fatal geometry smells are warnings attached to features.

## Known limitations

- No sketch constraints or closed-loop joints (four-bar linkages); assemblies are trees of joints from one fixed part. Text is flat-face only (no wrapping onto curved surfaces).
- Shelling freeform (lofted / swept) bodies relies on OCCT's offset algorithm: `shell` retries looser tolerances and the other join type, but a loft fused onto a prism often still fails. Volumes of booleaned pieces of such shells integrate ~0.2 % off (the geometry itself is consistent, checked by meshing).
- Rendering is orthographic only, with section views; no transparency, feature highlighting or exploded views yet. Worker peak memory during rendering is ~0.8 GB (float buffers at 2× supersampling).
- Adding features one call at a time is quadratic in the number of features (full re-validation each time); use batch positions for repeated features.
- Import: STL meshes become faceted solids (fine for reference geometry and simple booleans; curved surfaces stay faceted). 3MF/OBJ import is not supported. Slicing needs Bambu Studio installed and uses its bundled presets (user presets from the app's profile folder are not read yet).
- `find_holes()` recognises cylindrical holes; slots, tapered holes and holes split into >2 faces may be reported partially.
- Feature graph is a record, not a re-executable DAG; edits happen in the script.
- Resource limits: RLIMIT_AS is not enforced by macOS.
- Stress analysis is linear static on one part at a time: no contact between parts, plasticity, buckling, large deflection, fatigue, or anisotropic stiffness of prints (only a separate across-layer strength check), and infill is not modelled (solid assumed). Loads from joints and bonded multi-part assemblies are not wired up yet. Peak stresses are within ~2-5 % of textbook cases at the default quality; idealised clamps and sharp inside corners are reported as artifacts rather than hidden.
