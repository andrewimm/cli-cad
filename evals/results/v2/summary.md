# Eval run v2

model `sonnet`, git `89b56c5`, label `v2`

- attempts: 18, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 5.611, mean failed builds 0.167, mean turns 9.444
- cost: total $2.455 (mean $0.136); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| angled_port | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |
| enclosure_lid | 1.0 | 1.0 | 6.5 | 1 (0) | 1 | 1 | 8.5 |  |
| l_bracket_ribs | 1.0 | 1.0 | 6.5 | 2 (1) | 1 | 1 | 9 |  |
| modify_bracket | 1.0 | 1.0 | 5 | 1.5 (0) | 1 | 1 | 11 |  |
| phone_stand | 1.0 | 1.0 | 8.5 | 2 (0.5) | 2.5 | 1 | 15 |  |
| plate_4_holes | 1.0 | 1.0 | 6 | 1 (0) | 1 | 2 | 8.5 |  |
| servo_mount | 1.0 | 1.0 | 4 | 1 (0) | 1 | 1 | 9.5 |  |
| shaft_coupler | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8 |  |
| standoff_tray | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 7.5 |  |

## cad error codes seen

- NO_PROJECT: 5
- VALIDATION_FAILED: 1

## Feedback issues

- [angled_port] docs_unclear/low: The docs contain an angled-hole example that is almost exactly this task. I copied its pattern, so the task was easy. A new user would still need to work out the sign convention (start point offset toward +X, direction toward -X) without help.
- [angled_port] query_missing/low: find_holes() reports the angled hole's 'position' as the lowest-coordinate end and its 'depth' as the longest side (18.376). Neither directly confirms that the flat bottom is centred on (-10,0,10). I had to check this from the section render.
- [angled_port] docs_unclear/low: The docs contain an angled-hole example that is almost exactly this task. I adapted it, which was easy, but the sign convention (the start point sits at +X when the drill direction is (-s,0,-c)) is only implied by the example. The perpendicular flat bottom of an angled blind hole is also not described.
- [angled_port] query_missing/low: find_holes() reports depth 18.38 for port B, the longest wall side. The drilled axial length is 17.32. This is documented, but it makes the number hard to check against the spec.
- [angled_port] other/low: cad init in a non-empty directory writes a model.py stub and the project name 'workspace'. This is fine, but I had to overwrite model.py.
- [enclosure_lid] docs_unclear/low: `cad init` in a directory that already has a model.py did not leave my file as the entry in a way I could rely on. I wrote model.py before init, and init kept it as documented, so this worked. However, a shell heredoc write was blocked by the sandbox, which is not a cad problem.
- [enclosure_lid] query_missing/low: The lip's face names are ambiguous: both inner and outer lip walls carry names like lip.front and lip.side, so a name cannot pick the outer wall. `cad measure lid.lip` returned all 17 faces, and I had to read centroids to tell inner from outer. The clearance check still worked via --distance box.cavity.side (0.25 mm).
- [l_bracket_ribs] docs_unclear/low: Plane 'YZ' offset + symmetric semantics for ribs had to be inferred from the example (offset=X of the mid-plane); the doc example happened to cover it, which helped.
- [l_bracket_ribs] other/low: `cad init` was not needed since I wrote cad.toml by hand, but the docs don't state the minimal required cad.toml keys explicitly beyond the example.
- [modify_bracket] docs_unclear/low: For a 2D `at` with direction '+y', the docs excerpt I read did not state explicitly which axis order the 2D point uses (x,z); I inferred it from the existing model and confirmed with cad inspect.
- [modify_bracket] other/low: The hole Z=22 had to be hard-coded (or computed as thickness + 18); the original used wall_height*0.6, which would have given Z=34 after the height change. Easy trap when only the parameter is changed.
- [modify_bracket] docs_unclear/low: For axis-aligned non-Z holes, the 2D 'at' coordinate order/meaning (x,z for +y direction) was inferred rather than clearly stated; I relied on inspect output to confirm it.
- [modify_bracket] other/low: The original wall hole Z was derived from thickness + wall_height*0.6, so changing wall_height silently moves the hole; I had to hardcode Z=22 to keep it as the task required.
- [phone_stand] query_missing/low: No direct way to measure the angle between two faces or the thickness of a slanted plate; I verified the 65 degree backrest only via the bbox height (6 + 100*sin65 = 96.63) and the render.
- [phone_stand] docs_unclear/low: The YZ plane's (u, v) = (Y, Z) mapping is documented, but there is no example of a slanted-plate profile computed from an angle and length. I computed the polygon corners by hand with trig.
- [phone_stand] geometry_failure/medium: Combining overlapping/touching profiles with Profile + (rect base + rect lip + polygon back rest) and extruding produced a part with solid_count=2 (volume was correct, render looked fine) with no warning from build. Only assert_valid(solids=1) caught it. Replacing the union with one hand-computed outline polygon gave 1 solid.
- [phone_stand] error_unhelpful/medium: VALIDATION_FAILED 'expected 1 solid(s), found 2' does not say which solids/where they are; I had to guess. No query to list solids with bbox/volume.
- [phone_stand] query_missing/low: No way to list solids (bbox, volume) of a multi-solid part, nor a section/point-in-solid check.
- [phone_stand] docs_unclear/low: Docs do not say how to draw an inclined slab of given thickness/length; had to compute the rotated rectangle corners by hand. A Profile.rotated_rect / polyline-with-thickness helper would help.
- [plate_4_holes] docs_unclear/low: Hole record names list both 'holes1.wall' and 'holes1.wall.N'; unclear whether the shared name is a combined selector. Minor.
- [plate_4_holes] docs_unclear/low: cad init . names the project after the directory ('workspace') and writes a placeholder model.py; the docs say it keeps an existing model.py but don't say it creates one otherwise, so I had to overwrite it.
- [shaft_coupler] docs_unclear/low: `cad init .` in a directory that already has model.py worked, but it printed no hint that it kept my script; project name defaults to the directory name ('workspace') rather than the part name.
- [shaft_coupler] other/low: The docs example for radial holes (at=(12.5,0,10), depth=12.5, direction -x) fit this task directly, so no real difficulty. The hole depth reported by find_holes (8.5, 10) reflects the wall length to the bore, which is useful but slightly surprising.
- [shaft_coupler] docs_unclear/low: Docs did not say whether a radial hole with depth=12.5 from the surface at radius 12.5 stops at the axis; the example in the docs made it clear, but reaching the 5 mm bore needed my own reasoning (hole ends at the axis, so it breaks into both bores).
- [shaft_coupler] query_missing/low: No direct check that a set-screw hole actually intersects a bore; I relied on find_holes() and a section render. find_holes() reports the set-screw hole depth truncated to the visible wall (8.5 / 10) which is correct but slightly surprising.
- [standoff_tray] docs_unclear/low: The docs describe the wall ring via Profile subtraction and extrude offset, which worked first try; no real problems. `cad init` in a dir with no model.py wrote a default model.py that I had already overwritten, so behavior with existing files was fine.
- [standoff_tray] other/low: Sandbox required Write tool for model.py rather than shell heredoc; not a cad issue.

## Suggestions

- [angled_port] Add an optional 'tilt' or 'angle_from_vertical' argument to hole(), or a helper such as direction_from_angle, so users don't have to compute sin/cos by hand.
- [angled_port] Have find_holes() also report the start and end centre points of each hole bottom, not only the lowest-coordinate end.
- [angled_port] Let `cad init` run without overwriting or complaining when a model script is already present. The first call was fine. I only mention it because the project name defaulted to the directory name ('workspace').
- [angled_port] Add an angled-hole option such as tilt_deg/plane, or a helper that takes a target point on the axis plus an angle. That would avoid hand-computing the start point on the top face.
- [angled_port] Report both the axial length and the longest-wall length in find_holes() for slanted holes.
- [angled_port] Add a 'hole end point' query that gives the bottom-centre of a blind hole, so you can verify it reaches (-10,0,10).
- [enclosure_lid] Add an enclosure/lid example to `cad examples` showing the Profile.offset lip recipe in the docs end to end.
- [enclosure_lid] Let `cad build` print interference/distance between parts automatically when multiple parts exist.
- [enclosure_lid] Give ring-shaped extrusions distinct names for outer and inner walls (e.g. .outer_side / .inner_side).
- [enclosure_lid] Add an example or recipe for a lid with a lip, and for a box built from an extruded outline plus a cut. Profile.offset covered this well.
- [enclosure_lid] Add a built-in `cad check` for assembly clearance and interference between parts.
- [l_bracket_ribs] Add a rib/gusset recipe with explicit YZ-plane (y,z) coordinates for 'inside corner' cases.
- [l_bracket_ribs] Allow inspect to print a volume breakdown per feature to cross-check hand calculations.
- [l_bracket_ribs] A Profile helper for right triangles (e.g. Profile.right_triangle(leg_u, leg_v, corner)) would avoid hand-computing polygon vertices for gussets.
- [l_bracket_ribs] A rib/gusset helper that takes two faces (base.top, wall.front) and leg lengths would be convenient.
- [modify_bracket] State the 2D `at` axis order for every drill direction in a table.
- [modify_bracket] cad inspect could report hole positions relative to named faces.
- [modify_bracket] Document the 2D 'at' axis order for each hole direction in a table.
- [modify_bracket] cad inspect could print a through/blind flag for holes.
- [phone_stand] Add Profile.polyline_thick or a 'slanted plate from point, angle, length, thickness' helper.
- [phone_stand] Add a face-to-face angle query, e.g. cad measure --angle A B.
- [phone_stand] Add a dimensioned/annotated side view or a 2D section outline export for checking.
- [phone_stand] Make Profile union fuse overlapping regions into a single face (or warn when it can't).
- [phone_stand] Warn at build time (DISCONNECTED_BODIES) for the first extrude too when result has >1 solid.
- [phone_stand] Add p.solids() / cad query for solids with bbox and volume.
- [phone_stand] Add Profile.rect with angle/rotation about a point, or Profile.stroke(polyline, thickness).
- [plate_4_holes] Show a minimal end-to-end example (box + fillet vertical edges + holes) near the top of cad docs.
- [plate_4_holes] Have `cad init` print the entry-script path and a minimal template.
- [plate_4_holes] Mention in the docs that fillet-before-hole is fine and ordering doesn't matter for named references.
- [servo_mount] An example of a plate with rectangular cut-out plus holes would make this even faster to find.
- [servo_mount] Make 'cad build' print hole count by diameter to cross-check quickly.
- [servo_mount] A worked example in the docs for 'rect cut-out plus holes in a plate' is already effectively present; maybe note that holes() positions are 2D and the cut-out uses extrude(through=True) with a dummy distance.
- [shaft_coupler] Let `cad init` take --name, or default the project name to the first Part name.
- [shaft_coupler] Add a chamfer/fillet example that selects outer circular edges by radius (edges().circular(radius=...)).
- [shaft_coupler] Add a per-hole 'breaks_into' / connectivity query for holes.
- [shaft_coupler] Let hole() accept depth='to_axis' or target a named feature for radial holes.
- [standoff_tray] Add a `cad check` assertion helper or expected-values option to verify hole depth/top Z from the CLI.
- [standoff_tray] Show a named-feature example for loops creating multiple cylinders (standoffs) fused with a base.
- [standoff_tray] Add a Part.cylinder-with-hole/boss helper or a feature-level 'standoff' primitive.
- [standoff_tray] A ring/frame helper (rect wall of given thickness) would avoid manual Profile subtraction.
