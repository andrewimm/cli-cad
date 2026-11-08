# cadstress — geometry stress tests

Drives the `cad` API (and, for S05, the real CLI + daemon) directly, without an
agent, to find robustness, accuracy and scaling defects.

```bash
cd stress
../.venv/bin/python -m cadstress run S01 [--cases 1000] [--seed 1] [--workers 8]
../.venv/bin/python -m cadstress run all
```

Results land in `../stress-runs/<suite>-seed<N>-<time>/`: `results.jsonl` (one
line per case: parameters, raw outcome, verdict), `summary.json`, `summary.md`
and `failures/<case>/repro.py` (+ `minimal_repro.py` where the harness could
reduce it). Archived summaries live in [`results/`](results); findings are
written up in [docs/STRESS_RESULTS.md](../docs/STRESS_RESULTS.md).

| suite | what | size |
|---|---|---|
| S01 | Booleans on solid pairs: full / partial overlap, face- and edge-touching, nearly tangent, tiny intersections, nearly coincident faces; union, cut, intersect | 1000 cases |
| S02 | Fillets on boxes, brackets, convex and star profiles, plates with holes, pocketed blocks; seven edge selections; radii 0.1-5 mm and 0.9 / 1.1 x the bisected maximum | ~500 attempts |
| S03 | The same shapes built at 0.1x-100x (plus 0.001x-10000x probes); normalised volume, area, bbox, clearances, holes, wall thickness, tessellation, STEP round trip | 6 families x 9 scales |
| S04 | 10-1000 holes, bosses and ribs, one call per feature vs one call for all; construction phases, tessellation, render, STEP, peak RSS | 24 cases, fresh process each |
| S05 | 200 parameter mutations of a bracket through `cad set` on the daemon: thin walls, oversized fillets, holes at edges, tangency, merging and vanishing features | 200 cases |

## How cases are judged

* **Deterministic:** every case is generated from `(seed, index)`; the case *is* a
  self-contained Python snippet, so a failure's reproduction is the exact code that ran.
* **Isolated:** cases run in worker processes; a segfault is recorded as `crash`
  and a hang past the per-case limit as `timeout`, and the run continues.
* **Input classes:** each case declares whether its input is `valid` (a definite
  answer exists), `ambiguous` (perturbations near the kernel tolerance) or, for
  fillets, feasible/infeasible relative to the bisected maximum radius.
* **Outcome classes:** `pass`; `controlled` (a structured `CadError` or a reported
  warning where the input warrants it); `defect` (crash, timeout, uncaught
  exception, invalid or empty solid accepted, wrong volume or topology, a failure on
  valid input, an uninformative error); `limitation` (characterised, e.g. a
  scaling timeout or an out-of-range scale).
* **Expected values:** analytic where possible (axis-aligned boxes); otherwise the
  Boolean identities V(A∪B)+V(A∩B)=V(A)+V(B) and V(A−B)=V(A)−V(A∩B).
