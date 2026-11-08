# Eval run heldout-baseline

model `sonnet`, git `ea11430`, label `heldout-baseline`

- attempts: 6, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 7.167, mean failed builds 0, mean turns 9.833
- cost: total $0.779 (mean $0.13); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| hex_standoff | 1.0 | 1.0 | 8.5 | 2 (0) | 1 | 2 | 11.5 |  |
| hinge_leaf | 1.0 | 1.0 | 8 | 1.5 (0) | 1 | 1 | 10 |  |
| pipe_flange | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |

## cad error codes seen

- UNKNOWN_REFERENCE: 1

## Feedback issues

- [hex_standoff] docs_unclear/medium: Profile.regular_polygon 'diameter' is not defined in the docs (circumscribed vs across-flats), and neither is what angle=0 means. I had to build and read the bbox to find that diameter is circumscribed and angle=0 puts vertices on X (flats at Y=+-4).
- [hex_standoff] api_confusing/low: Chamfering body.start/body.end convex edges also selected the hole's circular edges when the hole was cut first, so the bore was chamfered too. Selection by face name gives no way to say 'outer loop only'.
- [hex_standoff] docs_unclear/medium: Profile.regular_polygon 'diameter' is not documented as circumscribed vs across-flats, nor which angle puts a vertex on +X. I assumed circumscribed with a vertex on the X axis and confirmed it from the bbox (X 9.2376, Y 8).
- [hex_standoff] api_confusing/low: edges().convex().horizontal() also selects the circular bore edges at the end faces, so the chamfer silently hit the bore too. It was only visible in the face count and the hole info (depth 19 at z=0.5). Fixed with .linear().
- [hinge_leaf] api_confusing/medium: hole() with a 2D 'at' starts at the part's bounding-box face it enters. After adding the knuckle (top at Z=6) the bbox top was Z=6, not the plate top at Z=2, so the countersink cone sat in empty air above the plate. The result was plain 3.5 mm through holes. There was no warning and the build was valid, with no HOLE_MISSED or CUT_NO_EFFECT, because the cylinder part still cut the plate.
- [hinge_leaf] docs_unclear/low: The docs say a 2D point 'starts at the part's bounding-box face' but don't warn that this differs from the local top face when other features are taller. A countersink starting above the surface should be called out.
- [hinge_leaf] other/low: The find_holes depth for a countersunk hole reports only the cylindrical part (0.25) and doesn't mention the countersink. I could only confirm the countersink via query of cone faces.
- [hinge_leaf] docs_unclear/medium: With a 2D `at`, a hole starts at the part's bbox face. Once the knuckle raises the bbox top to Z=6, a 2D point would start above the plate and the countersink would land in the wrong place. I used a 3D start point (x, y, 2) instead. The docs don't warn about this.
- [hinge_leaf] docs_unclear/low: It isn't stated whether a countersink diameter is measured at the start point (the surface) or elsewhere. I assumed the surface. I did not measure the countersink face to confirm.
- [hinge_leaf] query_missing/low: find_holes reports a countersunk hole as depth 0.25 (the cylindrical part only) and doesn't report the countersink diameter or angle, so I couldn't verify the 7 mm / 90 degree spec numerically.
- [pipe_flange] docs_unclear/low: Docs don't state whether a hole() with a 2D 'at' placed at a hub top starts at the bbox top face; I assumed through-all from bbox top, which worked. Also not stated that bolt_circle holes cut only the disc if started from the top (the hub is inside the bolt circle, so fine).
- [pipe_flange] other/low: cad inspect reports hole depth 12 for bolt holes and 30 for the bore, which is helpful; the 'holes=7' count in the summary line is fine.
- [pipe_flange] docs_unclear/low: Docs do not say whether hole()/bolt_circle() with default depth cuts through the whole stacked part when the hub is taller than the disc; find_holes reports bolt holes depth 12 (correct) and bore depth 30, which confirmed it.

## Suggestions

- [hex_standoff] Document regular_polygon diameter and angle conventions, and add an option such as across_flats=.
- [hex_standoff] Add an edge filter for outer wire / loop vs inner loops of a face.
- [hex_standoff] I did not open the final render after fixing the chamfer; I verified with inspect only (bbox, hole depth 20, volume).
- [hex_standoff] Document regular_polygon diameter semantics and add an across_flats= option.
- [hex_standoff] Warn or report when a chamfer touches more edges than expected, or show chamfered edge count in the result.
- [hinge_leaf] Warn (e.g. COUNTERSINK_ABOVE_SURFACE) when a countersink or counterbore start is above the material surface it should cut into, or let hole() accept a face reference such as at=plate.top.
- [hinge_leaf] Let hole() take a face ref to start on, e.g. face='plate.top'.
- [hinge_leaf] Report countersink/counterbore parameters in find_holes() and inspect output.
- [hinge_leaf] Add a top-view render that clearly shows countersinks (e.g. a section view).
- [hinge_leaf] Have find_holes report countersink/counterbore diameter, angle and depth.
- [hinge_leaf] Warn in the hole docs that 2D `at` uses the bbox face, which may not be the face you mean.
- [hinge_leaf] Add a through-hole option for a cylinder cut along its axis, or an example of a hinge knuckle.
- [pipe_flange] Add a 'flange' or revolve-based example in cad examples for axisymmetric parts.
- [pipe_flange] Mention in docs that cylinder(at=...) z is the start of the cylinder with default align='min'.
- [pipe_flange] Add a flange/bolt-circle example to the docs
- [pipe_flange] cad init in a non-empty dir works well; mention that it overwrites model.py
