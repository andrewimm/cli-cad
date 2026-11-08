# Evaluation results

All agent runs used Claude Code in print mode (`claude -p --model sonnet`) as an
independent tester: a fresh workspace containing only `TASK.md`, `cad` on PATH
through a logging shim, an isolated daemon per attempt, tools limited to
`cad`/`ls`/`cat` plus file read/write, and no access to the implementation (0
implementation reads were detected across all runs). Every result was graded by
rebuilding the agent's project and running deterministic geometric checks,
independently of the agent's own claims. A separate vision-model session scored
the standard renders 1–5 against the request. Run summaries are in
[`evals/results/`](../evals/results); raw transcripts, call logs, renders and
feedback are in `eval-runs/` (not committed).

## Versions

| version | commit | changes (all driven by agent feedback) |
|---|---|---|
| baseline | `ea11430` | first complete system |
| v2 | `89b56c5` | section/cut-away renders, `extrude(through=True)`, `Profile.offset`, distances between named references, bare feature ids as references, documented `cad.toml` / `cad init` in the current dir / hole start and extrude-plane semantics / rotate sign |
| v2.1 | `7c2b98e` | removed doc and example numbers that mirrored eval tasks (leakage found by a tester); `NO_PROJECT` hint says to run `cad init` here |
| v3 | `4a10191` | holes positioned in 2D start where the drill line **enters material**, not at the bbox face; `RECESS_NO_EFFECT` warning; `regular_polygon(across_flats=)` |


## Results

Means per attempt; 2 attempts per task.

| suite | version | n | pass | cad calls | failed builds | turns | cost | medium+high issues | visual (1–5) |
|---|---|---|---|---|---|---|---|---|---|
| dev (9 tasks) | baseline | 18 | 100% | 5.28 | 0.00 | 9.1 | $0.126 | 0.33 | 4.67 |
| dev | v2 (docs leaked) | 18 | 100% | 5.61 | 0.17 | 9.4 | $0.136 | 0.11 | 4.61 |
| dev | v2.1 | 18 | 100% | 5.56 | 0.11 | 8.9 | $0.131 | 0.00 | 4.72 |
| dev | v3 | 18 | 100% | 5.44 | 0.28 | 9.9 | $0.140 | 0.11 | 4.67 |
| held-out set 1 (3 tasks) | baseline | 6 | 100% | 7.17 | 0 | 9.8 | $0.130 | 0.67 | 5.00 |
| held-out set 1 | v2.1 | 6 | 100% | 6.83 | 0 | 9.8 | $0.139 | 0.67 | 4.83 |
| held-out set 1 | v3 ‡ | 6 | 100% | 4.83 | 0 | 8.2 | $0.124 | 0.00 | 5.00 |
| **held-out set 2 (2 fresh tasks)** | **baseline** | 4 | 100% | **8.00** | 0 | **11.0** | $0.144 | **0.75** | 4.50 |
| **held-out set 2** | **v3** | 4 | 100% | **4.75** | 0 | **7.75** | $0.131 | **0.00** | 4.50 |

‡ v3's main fix was motivated by held-out set 1 feedback, so set 1 stopped being
clean after v2.1. Held-out set 2 (cable clip, NEMA 17 mount) was written after
v3's code was final and before any agent saw it, then run on both baseline and v3.

## What the evidence supports

- **Task completion is saturated.** All 70 graded attempts passed every check
  (0 over-claims). Pass rate cannot show an improvement between versions on these
  tasks; harder tasks are needed for that (see below).
- **The v3 hole fix measurably reduced effort where it applied.** On the fresh
  cable-clip task, both baseline agents hit the "countersink cut in mid-air"
  hazard (a 2D hole position started at the bbox top raised by the ring). They
  reported it as high/medium severity and spent 10 and 13 `cad` calls (13–14 turns)
  diagnosing and working around it. The v3 agents used 4 and 5 calls (7–9 turns)
  and reported no problems. Across held-out set 2: calls −41%, turns −30%,
  medium/high issues 0.75 → 0 per attempt. n = 4 per side, so treat the size of
  the effect as indicative, but the mechanism shows directly in the transcripts.
- **Documentation fixes removed the dominant complaints.** The most frequent baseline
  issues were the undocumented `cad.toml`/`cad init` (8 mentions), hole start/depth
  semantics (7), extrude plane/offset semantics (5), and missing section views (4 + the
  vision reviewer). None recur as medium issues after v2.1. Effort metrics on the dev set
  did not change measurably (5.3 → 5.4 calls; differences are within run-to-run noise).
- **No regressions** in pass rate or check scores on any task.

## Things the evals caught that tests had not

- `Part.holes` was defined twice (the drilling op and the query); the later definition
  silently replaced the drilling op. Found by the validator self-test; renamed the query to
  `find_holes()` and added an AST guard test.
- Agents believed `hole()` only accepted axis-aligned directions (it accepts vectors) and
  rotated tool parts to work around it: a documentation failure, not an API gap.
- The doc examples written for v2 used numbers from the eval tasks. A tester pointed out
  that an example "is almost exactly this task". The numbers were de-leaked (v2.1) and the
  analysis above discounts v2.
- The harness itself: relative run directories broke PATH for the agent, and agents' shells
  re-initialise PATH from the user profile. Both were found by smoke-running an agent before the batch.

## Performance (daemon vs standalone)

`cadeval perf` (measured at `f19e5bf`; the runtime layer has not changed since), Apple Silicon, mounting-bracket project, medians (`evals/results/perf.json`):

| measurement | standalone | daemon (warm) |
|---|---|---|
| inspect / measure / query / cached build / cached render | ~620 ms | 8–11 ms |
| render, uncached, per 1024×768 view | 1364 ms | 475 ms |
| full build (forced) | — | 291 ms |
| cold start (spawn daemon + worker + command) | — | 601 ms |
| worker crash → next command served | — | 635 ms |
| 11-step agent workflow (build, inspect, renders, set, measure, …) | 10.5 s | 3.3 s (**3.2×**) |

Worker peak RSS was ~0.78 GB, dominated by 2× supersampled render buffers.

## Limitations of these evals

- One agent model family (Claude Sonnet via Claude Code) and 2 attempts per task;
  small samples, no confidence intervals.
- Tasks are well specified, dimensioned prompts. They do not test vague requirements,
  large assemblies, organic shapes, sweeps/lofts, threads or tolerancing, where the
  current API has known gaps (docs/ARCHITECTURE.md).
- Next: add tasks that require missing capabilities (sweeps, snap fits, hinged assemblies,
  FEA-checked brackets) so completion rate becomes informative again, more attempts per
  task, a second agent family, and periodic fresh held-out tasks.

## A01 — Unfamiliar agent onboarding

An independent agent gets a clean workspace, `cad` installed from a wheel and the
release binaries into an isolated prefix (`scripts/install.sh`; nothing from the
repository on PATH), and a minimal prompt: *"A command-line CAD tool named `cad` is
installed"* plus *"Design a 60 × 40 mm mounting plate with four holes and export a
printable STL."* No starter script, no pointers to the docs. Grading accepts any
thickness and hole size: the footprint must be 60 × 40 in some orientation with four
through-holes along the thickness, and a watertight STL matching the final model must
exist in the workspace. Times come from the `cad` call log relative to the agent's start.

| 5 attempts each | baseline (`0ff5867`) | v2 (`af455c4`: `cad --help` getting started, `cad docs <topic>`, quick start) |
|---|---|---|
| passed / exported a valid STL | 5/5 / 5/5 | 5/5 / 5/5 |
| time to first valid model (median) | 16.0 s | **13.1 s** |
| time to exported STL (median) | 17.1 s | 16.2 s |
| `cad` commands (mean) | 10.4 | **7.0** |
| shell commands (mean) | 5.6 | 4.0 |
| documentation lookups (mean) | 5.0 | **2.0** |
| API errors | 0 | 0 |
| cost per attempt | $0.130 | **$0.098** |

Baseline agents all took the same route: `cad --help`, the first 150 lines of
`cad docs`, a grep for "hole", `cad examples`, usually `cad examples show
plate_with_holes`. All five asked for a quick start in `--help`; four said the hole API
was buried in a long reference. After v2 every agent went `--help` → `cad init` →
`cad docs holes` → build → inspect → render → export. Two packaging/onboarding issues
surfaced while building the eval: `cad init`'s template was itself a plate with four
holes (now a neutral cube), and the wheel had to be confirmed to ship the reference and
examples (it does). Remaining feedback (STL printability confirmation) led to a
watertightness report on every STL export; that change is not yet re-measured.

## Multi-material 3MF (coaster task)

Task: a PLA coaster with a flush TPU insert, exported as one 3MF for single-pass
multi-material printing. The grader reads the agent's 3MF with lib3mf (the 3MF
Consortium's reference implementation) and checks that every mesh is closed and
oriented and that each part's material covers that part's geometry.

| 3 attempts each | v1 (3MF + materials) | v2 (layout guidance, cad.toml key, export hint) |
|---|---|---|
| passed | 3/3 | 3/3 |
| chose the multi-material layout for a one-piece print | 0/3 | **3/3** |
| verified contact with `cad clearance` | 0/3 | **3/3** |
| cad commands (mean) | 10.0 | 7.7 |
| cost per attempt | $0.127 | $0.118 |

All agents found the features through `cad docs --list` / `cad docs materials` / `cad docs 3mf`.
v1 feedback: which 3MF layout fits "printed in one go" was unclear (3/3), no cad.toml key for
it (2/3), `cad clearance` read as reference-only, and section cuts painted both materials the
same red. Remaining v2 feedback: the two materials' cut faces are still similar in tint.
Not verified here: import into PrusaSlicer/OrcaSlicer/Bambu Studio (no slicer in this environment);
the slicer-specific extruder config follows PrusaSlicer's `Slic3r_PE_model.config` format.
