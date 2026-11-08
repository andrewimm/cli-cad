<!-- What changed and why. If it came from agent feedback or an eval run, link or quote it. -->

- [ ] `uv run pytest -q` passes
- [ ] `cargo fmt --check` and `cargo clippy --release -- -D warnings` pass (if Rust changed)
- [ ] Agent-facing changes are documented in `src/cad/docs/REFERENCE.md` (and `skills/cad/SKILL.md` if workflow changes)
- [ ] New checks have negative tests; new agent features have an eval task, or a note on why not
