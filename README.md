# cad — agent-first parametric CAD

[![CI](https://github.com/andrewimm/clicd/actions/workflows/ci.yml/badge.svg)](https://github.com/andrewimm/clicd/actions/workflows/ci.yml)

A programmable CAD environment designed for autonomous coding agents: write a
Python script, get exact solid geometry (Open CASCADE BRep), check it with
numbers, look at deterministic headless renders, revise, and export STEP/STL.

```
agent ──> cad (Rust CLI) ──unix socket──> cadd (Rust daemon) ──> model worker (Python + OCCT)
                │                                                   live shapes, meshes, caches
                └── --no-daemon / `cad run` ──> same Python engine in-process
```

## Install

These steps are written so an agent can follow them unattended. Each one ends with a check.

**Supported:** macOS (Apple silicon or Intel) and Linux (x86_64 or aarch64). Stress analysis is not
available on Linux aarch64, because its mesher (gmsh) publishes no wheels for it. Windows is not supported;
use WSL2. Expect about 1.5 GB on disk (the Open CASCADE geometry kernel is large).

### 1. Linux only: system libraries

The geometry kernel needs OpenGL and fontconfig libraries even when nothing is displayed. macOS needs
nothing here. On Debian or Ubuntu:

```bash
sudo apt-get install -y libgl1 libegl1 libfontconfig1 fonts-dejavu-core
# only for stress analysis (--fea below): the gmsh mesher also needs
sudo apt-get install -y libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1 libxi6 libxkbcommon0
```

### 2. Install the latest release

```bash
curl -LsSf https://github.com/andrewimm/clicd/releases/latest/download/install.sh | sh
# or, with stress analysis (cad fea; its mesher, gmsh, is GPL-licensed, hence optional):
curl -LsSf https://github.com/andrewimm/clicd/releases/latest/download/install.sh | sh -s -- --fea
```

This downloads `install.sh` from the latest [GitHub Release](https://github.com/andrewimm/clicd/releases),
which then:
1. installs [uv](https://docs.astral.sh/uv/) if it is missing;
2. downloads that release's pre-built package for this machine (a Python wheel containing the `cad` package
   and the compiled `cad`/`cadd` binaries);
3. runs `uv tool install` on it, which gives cad its own Python 3.12 environment and puts `cad` and `cadd`
   in `~/.local/bin`;
4. runs `cad` once to check that it works.

You need no Rust, compiler or clone. To pin a version, replace `releases/latest/download` with
`releases/download/v0.1.0`. [CHANGELOG.md](CHANGELOG.md) says what each version changed.

### 3. Check it

```bash
cad --version                 # cad X.Y.Z
cad capabilities | tail -1    # stress analysis (cad fea): available | not installed (with the install command)
```

If `cad` is "command not found", `~/.local/bin` is not on your PATH. Run `uv tool update-shell` and open a
new shell, or add it yourself: `export PATH="$HOME/.local/bin:$PATH"` (bash/zsh, in your shell profile) or
`fish_add_path ~/.local/bin` (fish). The installer warns about this.

A first model, end to end (in any scratch directory):

```bash
cad examples copy mounting_bracket /tmp/bracket && cd /tmp/bracket
cad build && cad inspect && cad render --views iso   # renders/r1/*.png
```

### Optional extras

- **Agent skill:** `npx skills add andrewimm/clicd --skill cad` installs [skills/cad/SKILL.md](skills/cad/SKILL.md)
  for Claude Code, Codex and other agents that read the skills.sh format. It teaches them the workflow.
  Agents can also run `cad docs` at any time for the full reference.
- **Stress analysis later:** re-run the install command with `-s -- --fea`.
- **Slicing** (`cad slice`: print time, filament grams, a ready-to-print `.gcode.3mf`) needs
  [Bambu Studio](https://bambulab.com/en/download/studio). `cad` looks for it:
  - in `/Applications` on macOS;
  - as `bambu-studio` on PATH;
  - at `/opt/bambu-studio` on Linux.

  Elsewhere, set `CAD_BAMBU_STUDIO=/path/to/binary`. Exported 3MF files also open in OrcaSlicer,
  PrusaSlicer and Cura (`cad docs 3mf`).
- **Fonts** for engraved and embossed text: any installed font works (`cad fonts` lists them). The default
  is Helvetica, falling back to Arial or DejaVu Sans.

### Updating and uninstalling

```bash
curl -LsSf https://github.com/andrewimm/clicd/releases/latest/download/install.sh | sh   # upgrade (add -s -- --fea if you use it)
uv tool uninstall clicd                                                                     # uninstall
```

A running daemon from the old version is replaced automatically. Projects keep their own `.cad/` state.

### Building from source

Use this to run unreleased changes from `main`. It takes about 5 minutes and needs git, uv and Rust
(cargo):

```bash
command -v uv    || curl -LsSf https://astral.sh/uv/install.sh | sh            # or: brew install uv
command -v cargo || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
# open a new shell afterwards (or: source $HOME/.local/bin/env; source $HOME/.cargo/env)
```

On macOS without the command-line developer tools, run `xcode-select --install` first (Rust needs a linker).
On Linux, install the libraries from step 1, plus a compiler:

```bash
sudo apt-get install -y build-essential
```

Then:

```bash
git clone https://github.com/andrewimm/clicd.git && cd clicd
scripts/install.sh            # or: scripts/install.sh --fea
```

This builds the package and puts it, with its own Python environment, in `~/.local/cad`, then links `cad`
and `cadd` into `~/.local/bin`, replacing a release install's links. If a prerequisite is missing, it stops
with the command that fixes it. Like the release installer, it ends by checking that `cad` runs. Pass a
directory to install somewhere else (`scripts/install.sh /opt/cad`); set `CAD_LINK_DIR=""` to skip the links.
To update, run `git pull && scripts/install.sh`. To uninstall, run
`rm -rf ~/.local/cad ~/.local/bin/cad ~/.local/bin/cadd`.

### Troubleshooting

- **Sandboxes that forbid Unix sockets (e.g. Codex):** the daemon cannot start, so `cad` runs each command
  standalone automatically. Results are the same, and stderr shows a note. Set `CAD_NO_DAEMON=1` to skip
  the attempt.
- **`libGL.so.1` / `libEGL.so.1: cannot open shared object file`** (Linux): install the libraries from step 1.
- **No pre-built package for this machine** (another OS or CPU): build from source.
- **`cad` finds the wrong Python:** it uses the Python of the environment it is installed in. Set
  `CAD_PYTHON` to an interpreter that has the `cad` package to override that.
- **A command hangs or a worker crashed:** `cad daemon stop`. The next command starts a fresh daemon.

### Development setup

To work on cad itself, use the checkout directly instead of the installed copy:

```bash
uv sync                      # .venv with the dev group: pytest, lib3mf and the stress-analysis packages
cargo build --release        # target/release/cad and target/release/cadd
export PATH="$PWD/target/release:$PATH"
uv run pytest -q
```

`uv run cad <command>` runs the binaries `uv sync` built into `.venv`; `uv run python -m cad <command>` runs
the same CLI in standalone mode. See
[CONTRIBUTING.md](CONTRIBUTING.md).

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
Agents start from the [Agent Skill](skills/cad/SKILL.md). Its examples run as tests in `tests/test_skill.py`.

## What exists today

| area | status |
|---|---|
| Modelling | box, cylinder, sphere, extrude/revolve of 2D profiles (rect, circle, rounded rect, slot, tapered slot, polygon, text, boolean combos), lofts, sweeps along paths, drafts, holes (through/blind, counterbore, countersink, grids, bolt circles), engraved/embossed text, STEP/IGES/STL import, fillet, chamfer, shell, boolean with other parts, translate/rotate/mirror |
| Semantic geometry | feature-generated face names (`base.top`, `hole1.wall`) tracked through OCCT history; user tags; geometric selectors (`facing`, `convex/concave`, `max("z")`, `holes()`…); ambiguity and lost references are reported, never guessed |
| Validation | validity, solid count, bbox, volume, area, centre of mass, hole detection, min distance, interference, structured warnings (`CUT_NO_EFFECT`, `DISCONNECTED_BODIES`, …) |
| Feature graph | per-feature params, dependencies (incl. selection provenance), outputs, warnings, timings, failed features |
| Rendering | deterministic NumPy software rasteriser: 7 standard + arbitrary views, section (cut-away) views, orthographic, auto-framing, shaded/edges/lines, silhouettes, annotations (axes triad, scale bar), JSON camera metadata, contact sheet |
| Design for printing | screw holes M2-M8 (clearance, counterbore, countersunk, tap, heat-set insert, nut pocket), external and internal threads, snap-fit hooks, elephant's-foot chamfers, minimum wall thickness, material catalogue (density, stiffness, strength) |
| Assemblies | joints (revolute, slider, cylindrical, fixed) driven by parameters, joint limits, pairwise clearance and interference, `cad sweep` of a parameter range checking clearances, imported vendor parts as reference envelopes |
| Manufacturing | STEP / STL / BREP export, 3MF with materials (separate objects or one multi-material object; extruders assigned in Bambu Studio, OrcaSlicer, PrusaSlicer and Cura, checked by `scripts/slicer_compat`), `cad slice` through Bambu Studio (print time, grams per filament, supports, ready-to-print .gcode.3mf) |
| Stress analysis | `Study` load cases on named faces (fixed, force, bearing, torque, pressure, gravity), `cad fea`: curved quadratic tetrahedra (gmsh) + linear elasticity (scikit-fem, AMG), two-pass hot-spot refinement, safety factor incl. across print layers, hot spots traced to features and parameters, artifact warnings (sharp corners, clamps); `cad render --fea` stress / safety / displacement maps with legend, hot spots and loads |
| Runtime | Rust `cad` client + `cadd` daemon, one Python worker per project, auto-start, crash recovery, timeouts, optional rlimits, standalone mode |
| State | immutable revisions with atomic publication, parameter overlay, source snapshots, build/mesh/render/export caches surviving restarts, diff/checkout/restore |
| Evals | 28 declarative tasks (21 dev, 7 held-out) with reference solutions, deterministic grader, independent-agent runner (Claude Code CLI), cad call logging, structured feedback, visual review, reports/compare, performance eval |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions and
known limitations, [docs/SECURITY.md](docs/SECURITY.md) before running untrusted
scripts, [evals/README.md](evals/README.md) for the evaluation harness and
[docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md) for measured results, and
[stress/README.md](stress/README.md) / [docs/STRESS_RESULTS.md](docs/STRESS_RESULTS.md) for the
geometry stress suites (Booleans, fillets, scale, repeated features, parameter mutation).

## Tests

```bash
uv run pytest -q                                 # unit + integration (daemon tests need the release build)
cd evals && ../.venv/bin/python -m cadeval selftest   # reference solutions vs validators
```

CI (GitHub Actions) runs the tests on Ubuntu and macOS, Rust fmt/clippy, a CLI smoke test through the
daemon, and a core-only install without the optional stress-analysis packages. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0 (see [LICENSE](LICENSE)). The optional stress-analysis extra installs gmsh, which is GPL-licensed;
cad never imports it and runs it only as a separate process, and everything else works without it.
