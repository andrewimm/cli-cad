# Eval run baseline-hard

model `sonnet`, git `ea11430`, label `baseline-hard`

- attempts: 6, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 5.833, mean failed builds 0, mean turns 9.333
- cost: total $0.79 (mean $0.132); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| angled_port | 1.0 | 1.0 | 7.5 | 1 (0) | 1.5 | 3.5 | 11 |  |
| phone_stand | 1.0 | 1.0 | 5.5 | 1 (0) | 1 | 1.5 | 8.5 |  |
| standoff_tray | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8.5 |  |

## cad error codes seen

- NOT_FOUND: 2

## Feedback issues

- [angled_port] api_missing/medium: p.hole() only accepts axis-aligned directions (+/-x,y,z); no arbitrary or tilted direction vector, so the angled port needed a workaround (rotated cylinder cut).
- [angled_port] docs_unclear/low: Rotation sign convention for Part.rotate (which way +angle about Y tilts +Z) is not stated; I had to verify via cad inspect (axis reported [0.5,0,0.866]).
- [angled_port] render_missing/low: No section/cut-away render, so internal blind-hole bottoms and the intersection of the two ports can't be seen directly.
- [angled_port] docs_unclear/low: cad.toml format / init in an existing dir (`cad init . --name x`) is not documented in `cad docs`; I guessed a wrong cad.toml first.
- [angled_port] other/low: Reported depth of the tilted hole (19.05) includes the drill-cylinder overshoot/rim extent, not the 17.32 axis length from the entry point to the target; hole depth reporting for angled holes is ambiguous.
- [angled_port] api_missing/medium: Part.hole() only accepts axis-aligned directions; no way to drill an angled blind hole. Needed a separate tool cylinder, rotate it, and cut it.
- [angled_port] render_missing/medium: No section/cutaway render, so the internal intersection of the two ports and blind bottoms could not be seen visually; front/top views show only external faces.
- [angled_port] docs_unclear/low: Docs do not state the sign convention for rotate() about y (I assumed right-hand, +Z toward +X) or whether rotate() on a tool Part before cut() is fine; verified only through find_holes axis output.
- [angled_port] other/low: find_holes reports the through hole along Y starting at y=-15 with depth 30, and the angled hole's depth 19.05 includes the portion of the tool that extends above the top face; reported depth is not the drilled depth along the axis from the top face.
- [phone_stand] docs_unclear/low: cad.toml format is not shown in `cad docs`; I guessed a [project] name/script layout. The build worked, but I could not confirm it is the intended schema (I did not run `cad init` to compare).
- [phone_stand] docs_unclear/low: The YZ-plane extrude with symmetric=True centring on X=0 is implied by the docs but not stated. The bbox confirmed it.
- [phone_stand] docs_unclear/low: Plane 'YZ' extrude with symmetric=True: had to infer from docs that u=Y, v=Z and the extrusion is centred on X=0; worked first try but a side-profile example would help.
- [standoff_tray] docs_unclear/low: cad.toml format is not documented in `cad docs`; I guessed [project] name/entry and it built, but I did not confirm the schema (cad init would have generated it).
- [standoff_tray] api_confusing/low: No obvious way to make a hollow wall ring other than box-cut-box in separate Parts; shell() with open top would also remove the floor thickness semantic. Worked, but several temp Parts were needed.
- [standoff_tray] docs_unclear/low: Not obvious from docs that a 3D 'at' point for p.holes lets you start a blind hole from a standoff top (z=7) rather than the bbox top; I had to infer it from the 'at' rules. Worked on first try.
- [standoff_tray] api_missing/low: No direct way to make a hollow open box / wall ring (box with wall thickness); I built an outer box minus an inner box via a helper Part.

## Suggestions

- [angled_port] Allow hole(direction=(dx,dy,dz)) with a 3D start point, and optionally hole(..., through_point=...) / angle_from_vertical.
- [angled_port] Add a cad render --section option (plane + offset).
- [angled_port] Document rotate sign convention (right-hand rule) and cad.toml schema.
- [angled_port] Add a hole-bottom / blind depth query along the axis.
- [angled_port] Allow hole(direction=(dx,dy,dz)) with arbitrary vectors, and a start point on the axis.
- [angled_port] Add a section render (cut plane) option.
- [angled_port] Document cylinder-tool-and-cut pattern for angled features in the recipes.
- [phone_stand] Document the cad.toml schema in `cad docs`.
- [phone_stand] Add a Profile helper for a thick line/plate defined by a start point, angle, length and thickness, which would avoid the manual trigonometry.
- [phone_stand] Add a docs example of a sloped plate in the YZ plane.
- [phone_stand] Add a 'side-profile extrude' example (polygon in YZ, symmetric in X).
- [phone_stand] Provide a Profile helper for a thick slanted bar (start point, angle, length, thickness).
- [standoff_tray] Document the cad.toml schema in cad docs.
- [standoff_tray] Add a Profile-based ring/frame helper, or allow p.box(..., op='cut') with at= directly (it likely exists, I did not try it).
- [standoff_tray] Allow cylinder(..., op='add') directly on the part, avoiding temp Parts.
- [standoff_tray] Add a Part.box option or helper for open-top trays (shell with a thickness on a box is possible but I used cut).
- [standoff_tray] Allow p.cut with a primitive directly, without making a helper Part.
