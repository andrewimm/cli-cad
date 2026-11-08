# Contributing

`cad` is CAD for coding agents: every change is judged by whether an agent can use it correctly from
`cad docs` alone. Bug reports from agent sessions (the command, its `--json` output and what the agent
expected) are as welcome as code.

## Setup

macOS or Linux, [uv](https://docs.astral.sh/uv/) and Rust (cargo).

```bash
uv sync                     # Python 3.12 venv: OCP (OCCT 8), numpy, pillow, plus the dev group
                            # (pytest, lib3mf and the optional stress-analysis packages)
cargo build --release       # target/release/cad and cadd (the daemon tests use them)
export PATH="$PWD/target/release:$PATH"
```

On Linux, OCP and gmsh need a few system libraries (see `.github/workflows/ci.yml`):
`libgl1 libglu1-mesa libegl1 libxrender1 libxcursor1 libxft2 libxinerama1 libfontconfig1` and a font such as
`fonts-dejavu-core` for text.

## Before opening a pull request

```bash
uv run pytest -q                       # everything, including analytic FEA checks and the eval validators
cargo fmt --check && cargo clippy --release -- -D warnings
```

CI runs the same on Ubuntu and macOS, and checks that the core works without the optional stress-analysis
packages.

- **Agent-facing surface:** a new modelling call, CLI flag, warning code or error goes in
  `src/cad/docs/REFERENCE.md` (what agents read with `cad docs`). If it changes how agents should work, it
  also goes in `skills/cad/SKILL.md`. The skill's Python examples run as tests.
- **Errors:** errors and warnings carry a stable `code`, a `message` and a `hint` saying what to change.
  A failure that only says "failed" is a bug.
- **Evals:** behaviour aimed at agents should be checked with an independent agent (`evals/README.md`):
  add a task with a reference solution and negative grader tests (`tests/test_eval_checks.py`), then
  `cadeval run`. Agent runs call a model and cost money, so they are not part of CI.
- **Optional dependencies:** gmsh (the FEA mesher) is GPL. It stays an optional extra, runs only as a separate
  process (`src/cad/_fea_mesh.py`), and the package must import and work without it.
- **Commits:** stage explicit paths. Scripts and slicers write logs, renders and `result.json` files into the
  working tree; keep them out of commits.
