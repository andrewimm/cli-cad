# cadeval — evaluation harness

Measures whether independent coding agents can use `cad` to produce correct
mechanical designs, and whether changes to the tool improve that.

```bash
cd evals
../.venv/bin/python -m cadeval list                      # tasks (dev / heldout split)
../.venv/bin/python -m cadeval selftest                  # reference solutions must pass every validator
../.venv/bin/python -m cadeval run --split dev --attempts 2 --visual --label baseline
../.venv/bin/python -m cadeval compare ../eval-runs/<A> ../eval-runs/<B>
../.venv/bin/python -m cadeval perf                      # daemon vs standalone timings
```

## Tasks (`tasks/*.toml`)

Each task is a natural-language design request plus declarative checks:

| check | meaning |
|---|---|
| `part_count` | number (and optionally names) of parts produced |
| `valid` | every part is a valid BRep with one solid |
| `bbox` | size (and optionally min corner) within `tol` |
| `volume` | within `rel_tol` of the expected volume |
| `holes` | holes of a diameter/axis at given positions (positions in the two axes perpendicular to the hole axis), optional depth, `exact_count` |
| `points_inside` / `points_outside` | point-membership probes that pin down features (ribs, cut-outs, clearances, chamfers) |
| `interference` | shared volume between two parts below `max_volume` |
| `python` | escape hatch: `def check(parts) -> (ok, message)` |

`split = "heldout"` tasks are not used while developing improvements; run them
periodically (`--split heldout`) to detect overfitting. Reference solutions in
`solutions/` prove each validator is satisfiable (`selftest`, also run by pytest).

## Agent runs

`cadeval run` launches **Claude Code in print mode** (`claude -p`) per attempt:

- a fresh workspace containing only `TASK.md` (and setup files for modification tasks);
- `cad` on PATH through a logging shim (every call: argv, exit code, error code, duration → `cad_calls.jsonl`);
- an isolated daemon/state directory per attempt;
- tools limited to `Bash(cad:*)`, `ls`, `cat`, Read/Write/Edit/Glob/Grep; the prompt
  points at public docs (`cad docs`, `cad help`, `cad examples`) and forbids reading the
  package source (reads of the source are counted as `implementation_peeks`);
- a request to write `feedback.json` (schema: `cad schema feedback`).

After each attempt the grader **rebuilds the workspace itself** and runs the
checks; agents' self-reported success is recorded separately (`overclaimed`
counts attempts that claimed success but failed grading). With `--visual`, a
separate vision-model session reviews the standard renders against the request.

Artifacts per attempt: `workspace/`, `transcript.jsonl` (raw event stream),
`cad_calls.jsonl`, `feedback.json`, `grade.json`, `renders/`, `visual.json`,
`metrics.json`, `meta.json`. Each run has `summary.json` and `summary.md`.

No other agent runner or vision provider is configured; `cadeval prepare TASK DIR`
plus `cadeval grade TASK DIR` is the manual path for any other agent or a human.
