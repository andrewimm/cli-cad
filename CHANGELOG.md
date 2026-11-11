# Changelog

Each release has a `## X.Y.Z (date)` section; the release workflow publishes it as the release notes.
Versions follow [semver](https://semver.org/). Before 1.0, a minor version (0.x.0) may change the scripting
API or the CLI; patch versions do not.

## 0.1.1 (2026-11-11)

- `snap_hook`: `catch_face_at` is now where the catch face leaves the beam (its end nearest the root). For a
  hook with `retention_angle` below 90 it used to give the tip end, so a ledge placed there overlapped the
  sloped catch face.
- README: a "Get started" prompt to paste into a coding agent, which installs the CLI and the agent skill and
  starts designing a first print.

## 0.1.0 (2026-11-08)

First release. `cad` turns a Python script into exact solid geometry (Open CASCADE BRep), checks it with
numbers, renders it headlessly, and exports manufacturing files. It is built for coding agents: every
command has `--json` output, stable error codes and hints.

- **Modelling:**
  - boxes, cylinders and spheres;
  - extrude and revolve of 2D profiles, including text;
  - lofts, sweeps along paths, drafts;
  - holes, fillets, chamfers, shells, booleans and transforms;
  - named faces and edges that survive edits, plus geometric selectors.
- **Design for printing:**
  - screw holes M2–M8 (clearance, counterbore, countersunk, tap, heat-set insert, nut pocket);
  - threads, snap-fit hooks, elephant's-foot chamfers;
  - minimum wall thickness;
  - a material catalogue.
- **Assemblies:**
  - joints (revolute, slider, cylindrical, fixed) driven by parameters;
  - clearance and interference checks;
  - `cad sweep` over a parameter range;
  - imported vendor parts (STEP, IGES, STL) as reference envelopes.
- **Stress analysis** (`cad fea`, optional install):
  - load cases on named faces;
  - safety factor, including across print layers;
  - hot spots traced to the features and parameters that cause them;
  - stress, safety and displacement renders.
- **Output:**
  - STEP, STL and BREP;
  - 3MF with materials, which loads correctly in Bambu Studio, OrcaSlicer, PrusaSlicer (`--3mf-for prusa`
    for multi-material) and Cura;
  - `cad slice` through Bambu Studio: print time, grams per filament, a ready-to-print file.
- **Runtime:**
  - a Rust client and per-installation daemon with warm Python workers;
  - immutable revisions, parameter overrides and diffs;
  - deterministic software renders;
  - a standalone mode for sandboxes.
- **Install:** prebuilt for macOS (Apple silicon, Intel) and Linux (x86_64, aarch64) with
  `curl -LsSf https://github.com/andrewimm/clicd/releases/latest/download/install.sh | sh`. Stress analysis
  is not available on Linux aarch64, because gmsh publishes no wheels for it.
