# Geometry stress results

Suites: [`stress/`](../stress/README.md). Archived summaries and reproductions:
[`stress/results/`](../stress/results). Seed 1 throughout; macOS arm64, OCP 8.0.1.

## Summary

| suite | first run | final run | what changed |
|---|---|---|---|
| S01 Booleans (1000 cases) | 34 "defects" → 4 after harness fixes | **1000 pass** | union fallback when face merging corrupts the result; adaptive volume integration |
| S02 Fillets (504 attempts) | 2 defects + 1 found during smoke runs | **0 defects**; 68 controlled failures, all scoring 4/4 on error quality | fillet/chamfer results must be valid solids with an unchanged solid count; no silent body loss |
| S03 Scale (6 families × 9 scales) | pass | **pass**; worst normalised deviation 8e-9 across 0.001×–10000× | — |
| S04 Repeated features (24 cases) | 5 timeouts (>1500 s), quadratic | **24 pass**; batch calls linear-ish | fast OCP list conversion, fast internal metrics, batch positions, Delabella mesher |
| S05 Parameter mutation (200 cases) | 21 silent body splits | **0 defects**; 155 pass, 45 controlled | `BODY_SPLIT` warning |

## Defects found and fixed

1. **Volumes were inaccurate on trimmed curved faces (S01).** Box ∩ sphere pieces
   violated V(A∪B)+V(A∩B)=V(A)+V(B) by 0.35 mm³ (4 ppm). The Booleans were exact;
   OCCT's default Gauss integration was not. `volume`, `area` and
   `center_of_mass` now use adaptive integration (eps 1e-9; residual exactly 0 on
   the failing case). This also affected `cad measure`, mass and the eval grader.
2. **Union of a box and a sphere returned an invalid solid (S01, 4/1000).** Our
   post-fuse face/edge unification (`SimplifyResult`) corrupted valid fuse results.
   The union now falls back to the unmerged result when unification invalidates it.
3. **A fillet could silently delete the body (S02).** At a radius just under half a
   box's thickness the kernel returned a result with no solid that passed BRep
   validity, and the API accepted it. Any operation that leaves no solid now raises
   (`FILLET_FAILED` etc.).
4. **A fillet could split one solid into two (S02, 2 cases).** Star-profile vertical
   fillets at 0.9 r_max produced two solids. Fillets/chamfers must now return a valid
   solid with the same solid count, otherwise they fail with per-edge diagnostics.
5. **Invalid fillet results surfaced as a generic `INVALID_SHAPE` (S02).** They now
   raise `FILLET_FAILED` with the radius, the reason, a hint and the failing edges.
6. **Reference tracking was 10x slower than the geometry kernel (S04).** Iterating
   an OCP `NCollection` list from Python costs ~2.8 ms per call in the bindings;
   one such list per tracked face per feature dominated construction time (469 s of
   927 s for 500 individual holes). Lists are now read with Size/First on a copy
   (~5 µs).
7. **Repeated bosses/ribs had no linear-time path (S04).** `box(..., at=[...])` and
   `cylinder(..., at=[...])` now place many instances with one Boolean
   (1000 bosses: timeout → 1.3 s).
8. **Tessellating faces with many holes was slow (S04).** OCCT's default face mesher
   took 7.8 s on a plate with 1000 holes; the Delabella mesher produces the same
   208,012 triangles with identical accuracy in 0.45 s. Peak RSS for that case fell
   from 2.6 GB to 0.9 GB.
9. **Cuts that sever the part were silent (S05, 21/200).** Merged holes cut the plate
   in two without any diagnostic. Cuts, holes and intersections that increase the
   solid count now warn `BODY_SPLIT`.

Harness bugs found and fixed along the way (not product defects): a respawn loop when
workers cannot start, JSON-literal `false` in generated code, a partial-overlap
generator that sometimes produced non-overlapping or containing pairs, and judge
expectations for nearly coincident pairs and split tagged faces.

## S01 — Booleans

1000 cases (120 full overlap, 220 partial, 130 face-touching, 110 edge-touching,
140 nearly tangent with ε ∈ [1e-8, 1e-2], 140 small intersections with depth
∈ [1e-5, 1e-1], 140 nearly coincident faces with ε ∈ [1e-9, 1e-4]); 3000
operations. Final: all pass, including every ambiguous near-tolerance case (each
either produced a valid result within the perturbation bound or a controlled
`NO_BODY`). Median case 0.11–0.19 s (two primitives, three Booleans, validity and
volume checks).

## S02 — Fillets

72 shape/selection cases, 504 fillet attempts. Success by radius (final run):

| radius | attempts | succeeded |
|---|---|---|
| 0.1 mm | 72 | 72 |
| 0.5 mm | 72 | 72 |
| 1 mm | 72 | 71 |
| 2 mm | 72 | 59 |
| 5 mm | 72 | 36 |
| 0.9 × r_max | 72 | 72 (after fix: 2 now fail in a controlled way instead of splitting) |
| 1.1 × r_max | 72 | 4 (valid non-monotonic successes) |

Every failure is a `FILLET_FAILED` with a hint, failing edges and the radius
(quality 4/4). No selection was entirely un-filletable; stale selections were
always rejected; no unrelated named face disappeared.

## S03 — Scale

Within 0.1×–100×: every family builds, all normalised deviations ≤ 8e-9 (volume,
area), 0 (bounding box), ≤ 2e-14 (clearance, wall thickness, STEP round trip).
The probes at 0.001×, 0.01×, 1000× and 10000× behave the same.

**Limitation:** at 0.001× the 0.4 µm shell wall fails (`INVALID_SHAPE`): features
below ~1e-6 mm approach OCCT's 1e-7 mm confusion tolerance. Keep model units in mm
and features above ~1 µm.

## S04 — Repeated features (1000-feature rows)

| case | before | after |
|---|---|---|
| holes, one call | 8.9 s | 1.6 s |
| holes, one call each | timeout | 342 s |
| bosses, one call each | timeout | 385 s |
| bosses, one call (`at=[...]`) | — | 1.3 s |
| ribs, one call each | timeout | 1354 s |
| ribs, one call (`at=[...]`) | — | 6.0 s |
| tessellation (1000-hole plate) | 8.6 s | 1.1 s |
| peak RSS (1000-hole plate) | 2.6 GB | 0.9 GB |

Rendering stays under 1 s and STEP export under 2 s at 1000 features.

**Limitation:** building one feature per call remains quadratic (growth exponent
~2.4): each feature re-validates and re-measures the whole body. At 1000 ribs added
individually, validation is 530 s of 1354 s. Use batch positions (`holes`,
`hole_pattern`, `box/cylinder(at=[...])`) for repeated features; incremental
validation is future work.

## S05 — Parameter mutation via the daemon

200 `cad set` builds (median 98 ms each, p95 246 ms): 80 valid configurations all
pass. Of the risky ones, oversized fillets fail with `FILLET_FAILED` (18/20),
vanishing features that break a later reference fail with `FILLET_FAILED` /
`REFERENCE_LOST`, merged holes that sever the plate succeed with a `BODY_SPLIT`
warning, and thin walls down to 0.01 mm build valid solids. Throughout: no
crashes, no worker restarts, no timeouts; after every failure the active revision
stayed at the last successful build and `cad inspect` worked. At the end,
`cad checkout 1` and `cad unset` (returning to revision 1 from the build cache)
both worked, with 50 revisions recorded.
