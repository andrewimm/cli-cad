# Contributing

`cad` is CAD for coding agents: every change is judged by whether an agent can use it correctly from
`cad docs` alone. Bug reports from agent sessions (the command, its `--json` output and what the agent
expected) are as welcome as code.

## Setup

macOS or Linux, [uv](https://docs.astral.sh/uv/) and Rust (cargo). The README's [Install](README.md#install)
section shows how to get each one.

```bash
uv sync                     # Python 3.12 venv: OCP (OCCT 8), numpy, pillow, plus the dev group
                            # (pytest, lib3mf and the optional stress-analysis packages)
cargo build --release       # target/release/cad and cadd (the daemon tests use them)
export PATH="$PWD/target/release:$PATH"
```

On Linux, install the system libraries listed in the [README](README.md#1-prerequisites-from-source) first.

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

## Releasing

1. Bump `version` in `crates/cad/Cargo.toml`; the Python package takes its version from there. Run
   `cargo build` so `Cargo.lock` follows, and `uv lock`.
2. Add a `## X.Y.Z (date)` section at the top of `CHANGELOG.md`. It becomes the release notes.
3. Optionally, run the Release workflow by hand (Actions → Release → Run workflow). It builds and tests
   every platform's wheel without publishing.
4. Commit, then `git tag vX.Y.Z && git push origin vX.Y.Z`.

The workflow builds a wheel per platform (macOS arm64 and x86_64, Linux x86_64 and aarch64) containing the
`cad` package and the `cad`/`cadd` binaries. It installs each wheel with the release's `install.sh` on its
own platform and runs a model end to end. If all of that passes, it publishes the GitHub Release with the
wheels and `install.sh`. A tag that does not match the version in `Cargo.toml`, or a missing changelog
section, stops it.

