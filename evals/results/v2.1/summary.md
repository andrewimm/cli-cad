# Eval run v2.1

model `sonnet`, git `7c2b98e`, label `v2.1`

- attempts: 18, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 5.556, mean failed builds 0.111, mean turns 8.889
- cost: total $2.36 (mean $0.131); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| angled_port | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |
| enclosure_lid | 1.0 | 1.0 | 8 | 1 (0) | 1 | 1 | 10 |  |
| l_bracket_ribs | 1.0 | 1.0 | 5 | 1.5 (0.5) | 1 | 1 | 9 |  |
| modify_bracket | 1.0 | 1.0 | 5.5 | 1.5 (0) | 1 | 1 | 10.5 |  |
| phone_stand | 1.0 | 1.0 | 6 | 1.5 (0.5) | 1 | 1 | 8 |  |
| plate_4_holes | 1.0 | 1.0 | 6 | 1 (0) | 1 | 2 | 8 |  |
| servo_mount | 1.0 | 1.0 | 4 | 1 (0) | 1 | 1 | 10 |  |
| shaft_coupler | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |
| standoff_tray | 1.0 | 1.0 | 5.5 | 1 (0) | 1.5 | 1 | 8.5 |  |

## cad error codes seen

- NO_PROJECT: 5
- INVALID_ARGUMENT: 1
- NOT_FOUND: 1

## Feedback issues

- [angled_port] docs_unclear/low: Blind-hole depth for an angled hole is measured along the axis; the flat bottom is perpendicular to the axis so one rim edge dips below the target Z. Docs don't say this explicitly (the render shows it, though).
- [angled_port] other/low: cad init in a directory with an existing project name labels the project 'workspace'; harmless.
- [angled_port] docs_unclear/low: For an angled blind hole it is not stated that the flat bottom is perpendicular to the axis and centred on the end point (so the floor's corner dips below the end point's Z). I confirmed this only from a section render. Also, find_holes() reports depth 18.38 for portB, not the 17.32 axial length I drilled, because it measures the longest side of the hole wall.
- [angled_port] other/low: cad init in a directory named 'workspace' sets the project name to 'workspace'. The part name still comes from Part('manifold'), so this only affects labels.
- [enclosure_lid] docs_unclear/low: Not obvious from docs that extrude(..., -3, offset=40) is the way to hang a lip downward; I inferred it from the 'skirt' example. Worked first try.
- [enclosure_lid] query_missing/low: measure --distance returned point_on_self/other at a single closest point; no direct 'wall thickness / clearance per side' report, had to trust one point pair.
- [enclosure_lid] docs_unclear/low: Not obvious up front that a negative extrude distance with offset= is the way to build a downward lip; only inferred from the skirt example. It worked first try.
- [enclosure_lid] other/low: lip face names are ambiguous: opposite faces (outer and inner wall of lip) share the same names like lip.front, so named references select several faces.
- [l_bracket_ribs] api_confusing/low: Feature name with a negative number: name=f'rib{int(x)}' gave 'rib-15' (hyphen). Allowed, but ids with '-' could be awkward in references.
- [l_bracket_ribs] other/low: Verified volume by hand (21012.4 mm3) matches; no problems with the tool. Initial failure was mine (heredoc + chained commands blocked by sandbox), not the tool's.
- [modify_bracket] docs_unclear/low: The 2D 'at' for a +y hole is (x, z), which is inferred from the existing model and not stated explicitly for each direction. The hole inspect output showed start y=16 (the wall face), which confirmed it.
- [modify_bracket] docs_unclear/low: For holes with direction '+y' it was not obvious from docs which 2D coordinates (x,z) are expected; I inferred it from the existing model's at=(0, z) and confirmed via inspect.
- [phone_stand] docs_unclear/low: The slot-cut profile is on the XY plane, but the docs only say through=True cuts 'through the whole part in both directions'. I assumed this also works for a cut whose profile is already in the right plane. It worked, but I did not verify the slot in the top render beyond the build succeeding.
- [phone_stand] other/low: cad inspect shows no feature-level volume or cut-effect confirmation. I found no direct way to confirm the slot removed material besides the volume number and a render.
- [phone_stand] other/low: Shell redirection (heredoc) to create model.py was blocked by the sandbox approval; had to use the file Write tool. Not a cad issue.
- [phone_stand] docs_unclear/low: No example of a slanted plate defined by a start point, angle and length along the slope; I computed the polygon corners with trig by hand.
- [servo_mount] docs_unclear/low: `cad init` is described as creating cad.toml, but I wrote cad.toml by hand to avoid it overwriting anything. A minimal cad.toml example is in the docs, which was enough.
- [shaft_coupler] docs_unclear/low: cad.toml project name defaults to the directory name ('workspace'), while the task wanted the part named 'coupler'; it is only the Part("coupler") name that matters, which the docs say but it is easy to miss.
- [shaft_coupler] api_confusing/low: Radial hole with a 3D start point: 'at' on the surface with depth to the axis worked, but it is not obvious whether depth is measured from the start point (it is) vs. the bbox face for 2D 'at'.
- [shaft_coupler] docs_unclear/low: Unclear whether a radial hole with a 3D start point and depth to the axis is the intended way to 'reach the bore'; I used depth 12.5 (to the axis), which works and leaves the hole ending inside the bore.
- [shaft_coupler] other/low: cad init names the project after the directory ('workspace'); the task asked only for the part name, so this is harmless.
- [standoff_tray] docs_unclear/low: Wall as a frame extrude on XY with offset=2 works, but there is no obvious recipe for 'perimeter wall on top of a floor'; I had to infer it from the Profile subtraction and offset docs.
- [standoff_tray] other/low: cad init in a dir with an existing model.py worked fine, but the project name defaults to the directory name ('workspace'), not the part name.
- [standoff_tray] docs_unclear/low: --section x=26 with the front view shows an uncut silhouette (cut plane is edge-on to the camera); it is not obvious that the section plane must be viewed from a direction not parallel to it. A warning or auto-picked view would help.
- [standoff_tray] other/low: cad init . names the project after the directory ('workspace'), and cad init cannot be combined with a shell heredoc write in sandboxed use; minor.

## Suggestions

- [angled_port] Add a worked example for an angled hole that ends at a given interior point (axis length = height / cos(angle)).
- [angled_port] Let hole() accept an angle/tilt argument in addition to a direction vector.
- [angled_port] Let hole() take an end point as an alternative to depth.
- [angled_port] Add a hole option or helper to drill an angled hole given the end point, angle and top face, so the entry point doesn't have to be computed by hand.
- [angled_port] Report the axial length and the floor centre in find_holes() for angled holes.
- [enclosure_lid] Add an enclosure/lid example showing shell + offset-based lip with clearance.
- [enclosure_lid] Allow a section render of just the lid-box interface zoomed in (zoom/crop option).
- [enclosure_lid] Add an enclosure+lid example to the docs recipes.
- [enclosure_lid] Give inner/outer sub-names to faces of extruded profiles with holes (e.g. lip.outer / lip.inner).
- [l_bracket_ribs] Document that a YZ-plane profile uses (u=Y, v=Z) with offset=X, with a rib example whose corner is given in world Y/Z (the existing web example helped).
- [l_bracket_ribs] Consider validating/sanitising feature names containing '-'.
- [l_bracket_ribs] A worked gusset/rib recipe for the 'wall on base' case (YZ-plane triangle with offset + symmetric) would be handy; the existing web example was enough but needed mental mapping of (u,v)=(Y,Z).
- [modify_bracket] Document the order of 2D 'at' coordinates for each drilling direction in a table.
- [modify_bracket] Let a hole-through-wall report whether it fully penetrates (depth 4.0 shown, but not flagged as through).
- [modify_bracket] Document the 2D 'at' axis order for each hole direction in a small table.
- [modify_bracket] Let cad set persist wall_height default changes; editing the Parameter default was fine though.
- [phone_stand] Add a Profile helper or Part.extrude variant that takes a polyline plus thickness for slanted plates, e.g. a 'slab from line segment'.
- [phone_stand] Report the cut volume removed per feature in inspect --features.
- [phone_stand] Add a Profile helper for an oriented rectangle/strip (start point, angle, length, thickness).
- [phone_stand] A cad query/measure for angle between faces would help verify the 65 degree lean.
- [plate_4_holes] Let box() accept a corner radius or offer a rounded-rect plate shortcut.
- [plate_4_holes] inspect could report the hole positions relative to bbox edges.
- [plate_4_holes] cad init in a dir without model.py could scaffold a template model.py (here I wrote it myself, which was fine).
- [servo_mount] Add a one-line example of a cut-out rectangle (Profile.rect + extrude op='cut', through=True) in the plate-with-holes recipes.
- [servo_mount] Offer a `Part.cutout(profile)` or `box(..., op='cut')` shortcut with an 'in XY, through' default.
- [servo_mount] Allow a Profile.rect cut to be declared with a clearance argument, e.g. Profile.rect(w, h).offset(0.3), which already works; mention it in the cut-out recipe.
- [shaft_coupler] Show a chamfer-on-circular-edges example in the docs (edges().circular(radius=...)).
- [shaft_coupler] cad init in a non-empty dir could say that it keeps an existing model.py.
- [shaft_coupler] Add a documented example of cross holes into a bore (radial set screw).
- [shaft_coupler] Allow hole depth to be 'to axis' or 'until bore' for radial holes.
- [standoff_tray] Add a recipe for a tray/box with wall + bosses + blind holes from boss tops.
- [standoff_tray] Hole feature ids are numbered globally (hole1..4, holes1); allow name= prominently in the holes docs.
- [standoff_tray] Warn when --section plane is parallel to the view direction (cut face invisible).
- [standoff_tray] Provide a boss/standoff helper that adds a cylinder and a blind hole together.
