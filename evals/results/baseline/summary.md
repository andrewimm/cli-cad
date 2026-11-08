# Eval run baseline

model `sonnet`, git `88069b3`, label `baseline`

- attempts: 12, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 5, mean failed builds 0, mean turns 9
- cost: total $1.48 (mean $0.123); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| enclosure_lid | 1.0 | 1.0 | 6 | 1 (0) | 1 | 1.5 | 8.5 |  |
| l_bracket_ribs | 1.0 | 1.0 | 4 | 1 (0) | 1 | 1 | 8 |  |
| modify_bracket | 1.0 | 1.0 | 4 | 1 (0) | 1 | 1 | 10.5 |  |
| plate_4_holes | 1.0 | 1.0 | 6 | 1 (0) | 1 | 1.5 | 10 |  |
| servo_mount | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 8 |  |
| shaft_coupler | 1.0 | 1.0 | 5 | 1 (0) | 1 | 1 | 9 |  |

## cad error codes seen


## Feedback issues

- [enclosure_lid] render_missing/medium: Combined render of both parts shows them in one image with the lid hiding the lip; no section/cutaway view to verify the lip clearance visually.
- [enclosure_lid] docs_unclear/low: cad.toml format is not documented in cad docs (I wrote it by guess; cad init was not tried because of shell restrictions). Also 'offset' for extrude is only described as plane offset.
- [enclosure_lid] docs_unclear/low: Extrude with offset and negative distance (lip going down from Z=40): the interaction of offset on XY plane and negative distance was not documented explicitly; I guessed and verified via bbox (37..43).
- [enclosure_lid] query_missing/medium: No direct way to measure lip-to-inner-wall clearance (distance_to is 0 because the lid rests on the rim; cannot restrict to specific faces).
- [enclosure_lid] render_missing/medium: Default render shows only the assembled exterior; no cross-section view to verify the lip and clearance.
- [l_bracket_ribs] docs_unclear/low: The cad.toml format is not documented in `cad docs`; I guessed a minimal [project] table with name/script and it happened to work (I did not use `cad init` because I was writing files directly).
- [l_bracket_ribs] docs_unclear/low: Extrude on the YZ plane with `offset` (offset along +X normal) is only implied by the docs; I had to infer that offset is the start position and distance goes +X.
- [l_bracket_ribs] docs_unclear/low: extrude with offset on the YZ plane and symmetric=False: it was not obvious whether offset is the start face position (I assumed start at X=offset, extruding +X). Verified only via render/volume. The cad.toml schema was not documented in the docs I read; I guessed [project] name/entry (it built).
- [l_bracket_ribs] workaround/low: Shell heredoc file creation needed approval in this environment; used the Write tool instead (not a cad issue).
- [modify_bracket] docs_unclear/low: The 2D 'at' for direction +y/-y is documented as (x, z); it worked first try, but it's not stated whether the hole starts at the bbox face for a +y drill (min y) - confirmed only via inspect (depth 4 at y=16).
- [modify_bracket] other/low: The wall hole Z was hard-coded as 22 because the old expression (thickness + wall_height*0.6) would have moved when wall_height changed to 50. A parameter would be cleaner.
- [plate_4_holes] docs_unclear/low: `cad docs` shows a `cad init` workflow, but not that init can be run in an existing directory (`cad init .`). The cad.toml schema (entry=, not script=) is not documented, so I guessed a wrong format before using init.
- [plate_4_holes] docs_unclear/low: The docs show no cad.toml format (key is `entry`, not `script`). I guessed wrong at first and had to run `cad init` in the workspace to find out; `cad docs` should include a minimal cad.toml.
- [servo_mount] docs_unclear/low: The part name comes from Part('servo_mount') but cad.toml project name is separate ('workspace'); render titles show 'workspace r1'. Not obvious which name is the 'part name'.
- [servo_mount] docs_unclear/low: Docs do not say whether a cut box with default align (z min) at z=0 and the same height as the plate cuts cleanly through coplanar faces; it worked, but I had to check by inspecting.
- [shaft_coupler] docs_unclear/low: Hole `direction` semantics with a 2D `at`: it was not obvious that direction="+z" starts at the bottom face and "-x" enters from the +X side (direction is the drilling direction). I inferred it from the docs and confirmed via inspect.
- [shaft_coupler] docs_unclear/low: Unclear whether `depth` for a radial hole is measured from the bbox face (yes, per inspect output); no guidance on making a blind hole reliably reach a bore.
- [shaft_coupler] docs_unclear/low: hole() with a 3D start point vs 2D point: for direction -x the 2D point is (y, z) and starts at the bbox face; I had to infer that depth=12.5 from the +X face reaches the axis. Not stated whether depth is measured from the bbox face for 2D points (it appears so, inspect reported depth 8.5/10 from the wall).
- [shaft_coupler] docs_unclear/low: Hole direction semantics: docs say 'drilling direction' but it was not obvious that a bore from the bottom face needs direction '+z' with a 3D start point on z=0.

## Suggestions

- [enclosure_lid] Add a section/cutaway render (clip plane).
- [enclosure_lid] Document cad.toml schema.
- [enclosure_lid] Add a helper for offsetting a 2D profile (Profile.offset(d)) so clearance/lip profiles derive from the box cavity.
- [enclosure_lid] Add section/cut-away render views (plane + offset).
- [enclosure_lid] Add face-to-face distance, e.g. cad measure --distance between named faces or face selections.
- [enclosure_lid] Document extrude offset + negative distance semantics with an example.
- [l_bracket_ribs] Document the cad.toml schema in `cad docs`.
- [l_bracket_ribs] Add a recipe for gussets/ribs: a triangle profile on YZ extruded with offset, with a note on (u,v) = (Y,Z).
- [l_bracket_ribs] Optional rib helper e.g. p.gusset(...).
- [l_bracket_ribs] Document the cad.toml format in `cad docs` (or note that `cad init` generates it).
- [l_bracket_ribs] Document extrude offset semantics for non-XY planes with a worked example (e.g. a rib at a given X).
- [l_bracket_ribs] A Profile.triangle / right_triangle helper would be handy for gussets.
- [modify_bracket] cad inspect could print hole positions relative to named features, and a 'cad diff' between revisions would help confirm that only the intended things changed.
- [modify_bracket] Document explicitly which bbox face a 2D 'at' hole starts from for each direction.
- [modify_bracket] Allow holes() positions to be given in a wall-relative frame, or reference an existing feature position so the Z=22 height need not be hardcoded after wall_height changes.
- [plate_4_holes] Document `cad init .` for the current directory and show a sample cad.toml in the docs.
- [plate_4_holes] Add a one-line 'plate with holes and filleted corners' recipe to the docs.
- [plate_4_holes] Document cad.toml in `cad docs`.
- [plate_4_holes] Mention that cad init in an existing dir (with TASK.md) is safe.
- [servo_mount] Add a 'cad init --name' or make init use the part name from the script.
- [servo_mount] Add a rectangular pocket/cutout helper (e.g. p.rect_cut or p.cut_box_through) analogous to hole().
- [servo_mount] Add a docs example for a plate with cutout + holes.
- [servo_mount] Allow a rectangular/slot cut as a hole-like helper (e.g. p.cut_rect(w, d, at)) to avoid box(op='cut') with matching height.
- [shaft_coupler] Add a documented example of cross/radial holes and bores from both ends.
- [shaft_coupler] Offer a `cad query`/inspect check that reports whether a hole intersects another void (hole connectivity).
- [shaft_coupler] Show hole depth in inspect measured from the entry surface plus the entry point.
- [shaft_coupler] Add a 'to_axis' / 'until_bore' option or document how to make a radial hole that stops at a bore.
- [shaft_coupler] Show a worked example for blind holes entering from bottom and side faces in the docs.
