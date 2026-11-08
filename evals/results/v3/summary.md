# Eval run v3

model `sonnet`, git `4a10191`, label `v3`

- attempts: 18, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 5.444, mean failed builds 0.278, mean turns 9.944
- cost: total $2.516 (mean $0.14); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| angled_port | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8 |  |
| enclosure_lid | 1.0 | 1.0 | 6 | 1 (0) | 1 | 1 | 8.5 |  |
| l_bracket_ribs | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8 |  |
| modify_bracket | 1.0 | 1.0 | 4 | 1 (0) | 1 | 1 | 11.5 |  |
| phone_stand | 1.0 | 1.0 | 10.5 | 5 (2) | 1 | 1 | 19 |  |
| plate_4_holes | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8 |  |
| servo_mount | 1.0 | 1.0 | 4 | 1 (0) | 1 | 1 | 10 |  |
| shaft_coupler | 1.0 | 1.0 | 6 | 1.5 (0.5) | 1 | 1 | 8.5 |  |
| standoff_tray | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |

## cad error codes seen

- VALIDATION_FAILED: 3
- NO_PROJECT: 3
- NOT_FOUND: 2
- INVALID_ARGUMENT: 1

## Feedback issues

- [angled_port] docs_unclear/low: Not stated whether an angled hole's end face is perpendicular to its axis (it is, as the render shows), so the flat end's lower corner dips below the 'end point' Z=10 and the top start face leaves a sliver; the user must reason about this themselves.
- [angled_port] api_confusing/low: find_holes reports depth 18.38 for the angled hole (longest wall side) versus the 17.32 drilled axis length; needs interpretation.
- [angled_port] other/low: cad init in a directory that already had model.py kept it, but the shell tool required approval for file creation via redirect; unrelated to cad.
- [angled_port] docs_unclear/low: For an angled hole the start point on the top face has to be computed by hand (x0 = x_target + h*tan(a)) and the depth as h/cos(a). The docs example helps, but there is no 'hole to a target point' option.
- [angled_port] query_missing/low: find_holes reports the angled hole 'depth' as 18.38, which is the longest side of the flat-ended cylinder, not the axial 17.32 I drilled. It is documented but easy to misread. There was no direct way to confirm that the axis hits (-10,0,10) other than the reported position, which did match.
- [enclosure_lid] docs_unclear/low: box.distance_to(lid) returns 0 when the lid rests on the rim, so it can't confirm the lip clearance. I used `cad measure lid.lip --distance box.cavity`, which gave 0.25. The docs example only shows `box.shell1.inner`, and I had to guess that an extrude cut's name works as a reference.
- [enclosure_lid] docs_unclear/low: Whether shell() gives the inner cavity corners radius (outer r - wall) was not stated. I avoided relying on it by building the lip from Profile.offset(), but the lip clearance to the shell's inner wall is only guaranteed if the shell's inner radius is 3.5. The measured 0.25 mm min distance confirms it.
- [modify_bracket] other/low: The wall hole Z (22) is hardcoded in my edit; the original expressed it as thickness + wall_height*0.6, which would have moved to Z=34 with the new height. A 'keep the same absolute position' edit needs care.
- [modify_bracket] docs_unclear/low: Hole-drilling 2D 'at' semantics for +y (x, z) are documented in a table and worked first time; no real problems. Minor: the wall hole z was a derived expression (thickness + wall_height*0.6) so changing wall_height would have silently moved it; I hard-coded Z=22 per the task.
- [phone_stand] geometry_failure/medium: Profile.rect_corners(...) + Profile.rect_corners(...) + Profile.polygon(...) with overlapping/touching shapes, extruded once, produced 2 solids (solid_count=2) instead of one fused solid, with no warning. Only assert_valid(solids=1) revealed it. Extruding each shape as its own 'add' feature fixed it.
- [phone_stand] error_unhelpful/low: The VALIDATION_FAILED hint says an added feature 'does not touch the body', but here a single extrude of a combined profile was the cause, and the pieces did overlap. The message gave no clue about which solids were separate.
- [phone_stand] api_confusing/medium: Combining overlapping Profile shapes with `+` (base rect + lip rect + sloped polygon) and extruding gave a Part reporting solid_count=2 (valid=True) with no warning; the pieces were apparently not fused. Extruding each piece as a separate feature fused correctly.
- [phone_stand] error_unhelpful/low: When assert_valid fails the build, print() output from the script is not shown, so debugging prints are lost; I had to comment out the assert to see them.
- [plate_4_holes] other/low: cad init names the project after the directory ('workspace'); harmless but part name comes from Part().
- [shaft_coupler] other/low: Running `cad build` in a directory with a hand-written cad.toml worked only after the files existed; the NO_PROJECT hint is fine, but nothing else was problematic.
- [shaft_coupler] docs_unclear/low: Docs do not say whether a radial hole whose depth stops at the axis (12.5) vs. past it is preferred; find_holes reports the depth as only the visible wall portion (e.g. 8.5 / 10) which is confusing relative to the depth I requested.
- [shaft_coupler] docs_unclear/low: Radial hole direction: 'direction=-x' means drilled toward -X from the +X side. Table clarifies this, but 'entering from +X' vs '+x direction' is easy to confuse.
- [shaft_coupler] docs_unclear/low: Selecting only the outer circular edges needed circular(radius=12.5); max('z') alone would also have picked the bore rims. Not shown in a recipe.
- [shaft_coupler] other/low: cad init in a directory with a pre-existing TASK.md worked, but the project name defaulted to 'workspace' rather than the task/part name.
- [standoff_tray] docs_unclear/low: `cad init` in a dir with an existing model.py worked, but the name defaulted to the directory name; minor. Also the model had to be written before/after init with no hint on ordering.

## Suggestions

- [angled_port] Add a hole() helper for angled holes taking a point on the axis plus a tilt angle, or a start-at-surface option for vector directions (computing the entry point automatically).
- [angled_port] Have find_holes also report axial length along the axis.
- [angled_port] Add hole(..., to=(x,y,z)) or an angle= parameter (tilt from vertical plus azimuth) so angled holes don't need trig.
- [angled_port] Report axial depth and the start point for angled holes in find_holes.
- [angled_port] Let the section render optionally draw the hole axes.
- [enclosure_lid] Document that a cut feature's name is usable as a reference in --distance.
- [enclosure_lid] Add a recipe for a lid with a lip using Profile.offset.
- [enclosure_lid] Document the inner-corner radius that shell() produces.
- [enclosure_lid] Add a 'two-part enclosure with lip' recipe; Profile.offset made this easy and is worth showing.
- [l_bracket_ribs] cad init could default the project name to something other than the directory name when it is generic
- [l_bracket_ribs] A triangle/gusset helper (rib between two faces) would be convenient
- [l_bracket_ribs] A rib/gusset helper (triangle between two faces) would be convenient.
- [l_bracket_ribs] Document that the YZ plane profile (u=Y, v=Z) with symmetric=True is the idiom for ribs; the example already helps.
- [modify_bracket] Could show a front-view render with dimension annotations or hole centre coordinates to verify hole positions visually.
- [modify_bracket] Optionally let `cad inspect` print the hole's Z height/centre rather than only the lowest-coordinate end, which for a Y-axis hole shows y=16 (start of the wall hole) - fine but slightly surprising.
- [phone_stand] Make Profile union fuse overlapping shapes into one face, or warn (e.g. DISCONNECTED_BODIES) when an extrude yields multiple solids.
- [phone_stand] Make assert_valid / inspect report each solid's volume and bbox when there is more than one solid.
- [phone_stand] Add a helper for a slanted plate, e.g. Profile.slab(start, angle, length, thickness).
- [phone_stand] Make Profile `+` of overlapping shapes produce a single fused face, or warn when the result is multiple solids (DISCONNECTED_BODIES).
- [phone_stand] Show captured print() output also on failed builds.
- [phone_stand] Add a helper for a thick slanted plate (start point, angle, length, thickness) to avoid manual normal math.
- [plate_4_holes] Optional: a hole-position helper taking inset-from-edge (e.g. holes at 6 mm in from edges) would avoid manual arithmetic.
- [plate_4_holes] Add a one-line 'minimal complete project' example (cad.toml + model.py) at the top of cad docs.
- [plate_4_holes] Optionally let `cad init` accept an existing directory containing TASK.md without side effects (I wrote cad.toml by hand).
- [servo_mount] A Profile.rect-style cut helper on Part (e.g. p.cut_rect(w, h, at)) would save the extrude(..., through=True) idiom for simple pockets.
- [servo_mount] A Profile-based cut helper like part.pocket_rect(w,h,at) or box(op='cut') through-all shortcut would be handy.
- [servo_mount] cad init in a dir with no model.py wasn't needed, but a one-line 'minimal cad.toml + model.py' example in docs would help.
- [shaft_coupler] Let chamfer accept a selection like p.edges().circular() with an explicit note on how radius filter matches (diameter vs radius).
- [shaft_coupler] Allow hole(..., depth='to_axis') or up_to a reference for radial set screws.
- [shaft_coupler] Add a recipe for chamfering only the outer rim edges of a bored cylinder.
- [shaft_coupler] Add a 'hole to axis' option, e.g. depth='to_axis' or 'to_center', for radial holes that should reach a bore.
- [shaft_coupler] Let find_holes report a hole's depth beyond the point where it opens into another bore, or document that it reports only the wall extent.
- [standoff_tray] Show a minimal tray/wall example (extrude of rect-minus-rect with offset=) in docs recipes.
- [standoff_tray] cad init could default the project name to something other than the directory name when it is generic ('workspace').
