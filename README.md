# cad — agent-first parametric CAD

A programmable CAD environment designed for autonomous coding agents: write a
Python script, get exact solid geometry (Open CASCADE BRep), check it with
numbers, look at deterministic headless renders, revise, and export STEP/STL.

```
agent ──> cad (Rust CLI) ──unix socket──> cadd (Rust daemon) ──> model worker (Python + OCCT)
                │                                                   live shapes, meshes, caches
                └── --no-daemon / `cad run` ──> same Python engine in-process
```

## Install (development)

Requirements: macOS or Linux, [uv](https://docs.astral.sh/uv/), Rust (cargo).

```bash
uv sync                      # Python 3.12 venv with OCP (OCCT 8 bindings), numpy, pillow
cargo build --release        # target/release/cad and target/release/cadd
export PATH="$PWD/target/release:$PATH"
cad capabilities
```

The `cad` binary finds the venv automatically (`.venv/bin/python` above the
executable); otherwise set `CAD_PYTHON` to an interpreter with the `cad`
package installed. Without the Rust binaries, `uv run cadpy <command>` runs the
same CLI in standalone mode.

## Quick start

```bash
cad examples copy mounting_bracket my_bracket && cd my_bracket
cad build                    # -> revision 1 (immutable; identical inputs are reused)
cad inspect                  # validity, bbox, volume, holes, features, warnings
cad render --views iso,front,top        # PNG + JSON camera metadata + contact sheet
cad set wall_height 45       # parameter overlay (params.toml) -> revision 2
cad diff 1 2                 # parameter, source and geometry deltas
cad export --format step,stl
```

A model script:

```python
from cad import Part, Parameter

width = Parameter("width", 60, min=20, max=200)

def build():
    p = Part("plate")
    p.box(width, 40, 4, name="base")               # centred in X/Y, bottom on Z=0
    p.hole_pattern(3.2, spacing=(width - 12, 28), count=(2, 2))
    p.fillet(p.edges().vertical(), radius=2)
    p.tag("mounting_surface", p.faces().facing("-z"))
    p.assert_valid()
    return p
```

Agent-facing documentation: `cad docs` (source: [src/cad/docs/REFERENCE.md](src/cad/docs/REFERENCE.md)).

## What exists today

| area | status |
|---|---|
| Modelling | box, cylinder, sphere, extrude/revolve of 2D profiles (rect, circle, rounded rect, slot, polygon, boolean combos), holes (through/blind, counterbore, countersink, grids, bolt circles), fillet, chamfer, shell, boolean with other parts, translate/rotate/mirror |
| Semantic geometry | feature-generated face names (`base.top`, `hole1.wall`) tracked through OCCT history; user tags; geometric selectors (`facing`, `convex/concave`, `max("z")`, `holes()`…); ambiguity and lost references are reported, never guessed |
| Validation | validity, solid count, bbox, volume, area, centre of mass, hole detection, min distance, interference, structured warnings (`CUT_NO_EFFECT`, `DISCONNECTED_BODIES`, …) |
| Feature graph | per-feature params, dependencies (incl. selection provenance), outputs, warnings, timings, failed features |
| Rendering | deterministic NumPy software rasteriser: 7 standard + arbitrary views, orthographic, auto-framing, shaded/edges/lines, silhouettes, annotations (axes triad, scale bar), JSON camera metadata, contact sheet |
| Runtime | Rust `cad` client + `cadd` daemon, one Python worker per project, auto-start, crash recovery, timeouts, optional rlimits, standalone mode |
| State | immutable revisions with atomic publication, parameter overlay, source snapshots, build/mesh/render/export caches surviving restarts, diff/checkout/restore |
| Evals | 9 declarative tasks (6 dev, 3 held-out) with reference solutions, deterministic grader, independent-agent runner (Claude Code CLI), cad call logging, structured feedback, visual review, reports/compare, performance eval |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions and
known limitations, [docs/SECURITY.md](docs/SECURITY.md) before running untrusted
scripts, [evals/README.md](evals/README.md) for the evaluation harness and
[docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md) for measured results.

## Tests

```bash
uv run pytest -q                                 # unit + integration (daemon tests need the release build)
cd evals && ../.venv/bin/python -m cadeval selftest   # reference solutions vs validators
```
