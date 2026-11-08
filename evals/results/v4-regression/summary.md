# Eval run v4-regression

model `sonnet`, git `6bf8f7e`, label `v4-regression`

- attempts: 14, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 6.5, mean failed builds 0.071, mean turns 9.071
- cost: total $1.73 (mean $0.124); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| angled_port | 1.0 | 1.0 | 6 | 1 (0) | 1 | 2 | 10 |  |
| cable_clip | 1.0 | 1.0 | 6 | 1 (0) | 1 | 2 | 8 |  |
| enclosure_lid | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 7 |  |
| hex_standoff | 1.0 | 1.0 | 7 | 1 (0) | 1 | 2 | 9 |  |
| hinge_leaf | 1.0 | 1.0 | 9 | 1 (0) | 1 | 2 | 9 |  |
| l_bracket_ribs | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 7 |  |
| modify_bracket | 1.0 | 1.0 | 6 | 1 (0) | 1 | 2 | 12 |  |
| nema17_mount | 1.0 | 1.0 | 6 | 1 (0) | 1 | 1 | 7 |  |
| phone_stand | 1.0 | 1.0 | 12 | 3 (1) | 2 | 1 | 17 |  |
| pipe_flange | 1.0 | 1.0 | 6 | 1 (0) | 0 | 2 | 8 |  |
| plate_4_holes | 1.0 | 1.0 | 6 | 1 (0) | 0 | 2 | 8 |  |
| servo_mount | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |
| shaft_coupler | 1.0 | 1.0 | 7 | 1 (0) | 1 | 2 | 9 |  |
| standoff_tray | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |

## cad error codes seen

- VALIDATION_FAILED: 1
- INVALID_ARGUMENT: 1

## Feedback issues

- [angled_port] docs_unclear/low: For angled holes the docs say 'at' is a 3D start point, so the user must compute where the axis meets the top face and the slanted depth (L = h/cos a) by hand. Works fine, but is manual.
- [angled_port] other/low: A tilted flat-bottom hole has a bottom perpendicular to its axis, so one rim dips below the target point (to about Z=8.5 in section). Matches the spec (axis ends at the point) but no query reports the lowest extent of a single hole.
- [cable_clip] docs_unclear/low: cad measure --holes reports a countersunk hole as depth 1.0 (the cylindrical part only) at z=0 with no mention of the countersink; unclear whether countersink dimensions are queryable.
- [hinge_leaf] docs_unclear/low: `cad measure --holes` reports countersunk holes with position z=0 and depth 0.25 (only the cylindrical part), which is confusing; it does not report the countersink diameter/angle.
- [modify_bracket] docs_unclear/low: For a +y hole the 2D 'at' is (x, z); this is only inferable from an example. Through-wall hole depth reports 4.0 and hole names like 'wall_holes.wall.0' are somewhat opaque.
- [nema17_mount] query_missing/low: cad measure --holes does not list slots (non-circular cut-outs), so slot position/length had to be verified visually from the top render.
- [nema17_mount] docs_unclear/low: Profile.slot angle convention (angle=90 -> along Y) is not stated explicitly; I assumed the default is along +u and confirmed via render.
- [phone_stand] geometry_failure/medium: Building the whole side profile as one 2D union (rect + rect + rotated polygon whose corner lies inside the base) and extruding it, then cutting the slot, gave a part with 2 solids, even though the render looked connected and volume was the same. Building base/lip/rest as separate boxes/extrudes unioned in the part gave 1 solid. I did not find the cause.
- [phone_stand] error_unhelpful/medium: assert_valid said 'expected 1 solid(s), found 2' with a hint about features not touching, but gave no indication of which solids/where they are; query has no solids() selector to inspect them.
- [pipe_flange] api_missing/low: No polar/circular hole pattern helper; had to compute bolt-circle positions with math and pass them to holes().
- [servo_mount] other/low: cad measure --holes lists only circular holes; the rectangular cut-out is not reported, so its size/position had to be verified via bbox/volume reasoning and the render.
- [shaft_coupler] docs_unclear/low: Chamfering only the two outer circular edges required a filter chain (convex().perpendicular_to('z').longer_than(70)); the length threshold for 'outer vs bore edges' is a guess based on circumference (78.5 vs 25/15.7). A radius filter would be clearer.
- [shaft_coupler] api_confusing/low: Radial hole depth semantics: unclear whether depth is measured from the surface point given in 'at'; I chose depths that overshoot the bore wall. find_holes reports depth of the wall only (8.5 / 10), which is correct but surprising.

## Suggestions

- [angled_port] Add an option to hole() such as end_at=(x,y,z) or 'to=' so an angled hole can be defined by its end point and direction, with the start computed up to the top face.
- [angled_port] Show a worked example for 'drill down to a given point at an angle' in the hole docs.
- [cable_clip] Report countersink diameter/angle in find_holes()/measure --holes output.
- [cable_clip] Add a cable-clip / tube-along-Y example.
- [enclosure_lid] An explicit interference check (cad clearance between two non-reference parts) mentioned in the docs for this kind of task would help; I verified non-intersection by geometry/section only.
- [hex_standoff] Document that edges().horizontal() selects the end-face edges of a prism (an example for chamfering both ends would help).
- [hinge_leaf] Report countersink/counterbore diameter and angle in `cad measure --holes`.
- [hinge_leaf] Document that the pin hole (hole through knuckle axis) also nicks the plate when the plate overlaps the knuckle radius.
- [l_bracket_ribs] Document in the Sketch planes table that the YZ-plane profile coordinates are world (Y, Z), so a rib offset by X needs no translation (already clear from the ramp example).
- [modify_bracket] State explicitly in the hole docs that for direction +y the 2D 'at' is (x, z).
- [nema17_mount] List slots in measure --holes (or a --slots option) with length/width/orientation.
- [nema17_mount] Document Profile.slot default orientation and angle direction.
- [nema17_mount] A built-in counterbore/hole helper with a face/side argument would avoid manual two-step cuts.
- [phone_stand] Report the bbox/volume of each solid when assert_valid finds multiple solids.
- [phone_stand] Add a solids() selector or `cad measure --solids`.
- [phone_stand] Document that Profile '+' of overlapping shapes may leave disjoint/odd results, or fix it.
- [pipe_flange] Add hole_pattern(..., circle=(diameter, count, start_angle)) for bolt circles.
- [plate_4_holes] A `Profile.rounded_rect` + extrude example next to the box+fillet one would show both routes to rounded plates.
- [servo_mount] Report non-circular through-cutouts (size, centre) in cad measure --holes or cad inspect.
- [servo_mount] Offer a Part.hole(diameter, at, through=True) shortcut for simple through holes.
- [shaft_coupler] Add an edge filter like .circular(radius=...) or .radius(r) to select circular edges by size.
- [shaft_coupler] Offer hole depth='to_axis' or up_to=<face/hole> for set-screw holes that must reach a bore.
- [standoff_tray] Offer a hole feature that takes a list of positions (pattern of blind holes from a face) to avoid manual loops of cylinder cuts.
