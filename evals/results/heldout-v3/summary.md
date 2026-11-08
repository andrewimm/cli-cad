# Eval run heldout-v3

model `sonnet`, git `4a10191`, label `heldout-v3`

- attempts: 10, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 4.8, mean failed builds 0, mean turns 8
- cost: total $1.265 (mean $0.127); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| cable_clip | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8 |  |
| hex_standoff | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8.5 |  |
| hinge_leaf | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |
| nema17_mount | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 7.5 |  |
| pipe_flange | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |

## cad error codes seen


## Feedback issues

- [cable_clip] docs_unclear/low: Docs don't show a cylinder with axis='y' centred on a point (align='center' worked, found by guess). A short example would help.
- [cable_clip] other/low: Section render shows a faceted ring (coarse tessellation) - cosmetic only.
- [cable_clip] docs_unclear/low: Extrude on the XZ plane with symmetric=True: docs make it clear it is centred, but the ring's circle centre must be given in (u,v)=(X,Z); fine once read. No hard problems.
- [cable_clip] other/low: find_holes reports countersunk hole depth 1.0 (only the cylindrical part), which may surprise users expecting 3.
- [hinge_leaf] docs_unclear/low: Docs don't say whether countersink diameter is measured at the top face, or what happens when the cone depth ((7-3.5)/2=1.75) is nearly the plate thickness. I verified via inspect (cylindrical wall depth 0.25) and the render.
- [hinge_leaf] docs_unclear/low: For a hole along the knuckle axis, it was not obvious that a 3D 'at' can start outside the part (X=-25) with a vector direction; I inferred it from the angled-hole example. A 2D 'at' with direction +x would also work but I did not try it.
- [hinge_leaf] docs_unclear/low: find_holes reports countersunk holes as d=3.5 with depth 0.25 (cylindrical part only); countersink is not reported as a separate attribute.
- [nema17_mount] docs_unclear/low: Slot orientation: Profile.slot's 'angle' semantics (0 = along u/X, 90 = along Y) is not stated explicitly in docs; I assumed and verified via inspect/volume.
- [nema17_mount] query_missing/low: cad inspect does not list slots (non-circular cut-outs) in the hole list; verification of slots relied on volume arithmetic and a render.
- [nema17_mount] query_missing/low: cad inspect lists holes but not slots (cut via extrude of Profile.slot), so slot size/position could only be verified visually in the render.
- [nema17_mount] docs_unclear/low: Slot orientation: Profile.slot(length, width, angle) docs do not say angle=0 runs along u (X); I assumed angle=90 gives a Y-running slot and confirmed by render.
- [nema17_mount] docs_unclear/low: Counterbore from the bottom: it was not stated explicitly that with direction='+z' the counterbore starts at the bottom face; confirmed through find_holes output (counterbore at z=0, depth 3).
- [pipe_flange] docs_unclear/low: Unclear whether a hole with 2D `at` and no depth on the hub top starts at the hub; worked fine (through everything). Also cad init in a dir with existing model.py is fine.
- [pipe_flange] docs_unclear/low: cad init . names the project after the directory ('workspace'), not the part; harmless but part naming comes only from Part('flange'). Also bolt_circle with a plain name= gives features 'bolts.wall.<i>' - fine.

## Suggestions

- [cable_clip] Add a tube/ring example (cylinder along Y with bore) to docs
- [cable_clip] Finer render tessellation for curved faces
- [cable_clip] Add a Part.tube/ring helper for axis-aligned tubes
- [cable_clip] Have find_holes also report countersink diameter/angle
- [hex_standoff] A chamfer/fillet helper like edges('body.start').outer() (exclude hole edges) would be handy.
- [hex_standoff] Show chamfer edge selection count in build output.
- [hex_standoff] Add a recipe for chamfering only outer end-face edges (e.g. edges of end faces minus circular).
- [hinge_leaf] Report countersink diameter/depth in find_holes() output.
- [hinge_leaf] Show an example of a cylinder along X with 'at' as the start point and align='min'.
- [hinge_leaf] Report countersink/counterbore diameter and angle in find_holes / inspect.
- [hinge_leaf] Mention in the hole docs that shell redirection to create files may need the Write tool in sandboxed agents (environment-specific).
- [nema17_mount] State in the docs that Profile.slot length is end-to-end and angle=90 runs along v.
- [nema17_mount] Show a bottom-face counterbore example (direction='+z' with counterbore).
- [nema17_mount] Report slot features in find_holes or a separate find_slots.
- [nema17_mount] Let find_holes/inspect report slots (obround through-cuts).
- [nema17_mount] State in the Profile.slot docs which axis angle=0 runs along.
- [nema17_mount] Add a bottom-counterbore example to the Holes section.
- [pipe_flange] Mention in the bolt_circle docs that start_angle=0 puts the first hole on +X (it does, verified via inspect).
- [pipe_flange] Docs could state explicitly that hole(at=(0,0)) with 2D at on a stacked cylinder starts at the highest material (it worked, but is only implied).
