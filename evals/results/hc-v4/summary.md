# Eval run hc-v4

model `sonnet`, git `6bf8f7e`, label `hc-v4`

- attempts: 18, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 10.5, mean failed builds 0.056, mean turns 11.167
- cost: total $3.051 (mean $0.17); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| folding_arm | 1.0 | 1.0 | 13.333 | 3.333 (0) | 0.333 | 3 | 12 |  |
| param_hole_pattern | 1.0 | 1.0 | 8.667 | 3 (0) | 0 | 2 | 8 |  |
| robot_leg | 1.0 | 1.0 | 14 | 3.333 (0.333) | 0.333 | 2 | 13 |  |
| sensor_cradle | 1.0 | 1.0 | 7.667 | 1.333 (0) | 1 | 2.333 | 10.667 |  |
| servo_envelope_bracket | 1.0 | 1.0 | 12.667 | 2 (0) | 1 | 3 | 14 |  |
| split_shaft_clamp | 1.0 | 1.0 | 6.667 | 1 (0) | 1 | 2 | 9.333 |  |

## cad error codes seen

- INVALID_ARGUMENT: 9
- VALIDATION_FAILED: 3
- BOOLEAN_FAILED: 2

## Feedback issues

- [folding_arm] api_confusing/low: cad measure --holes without a part name errors with 'revision has 3 parts; name one' for multi-part assemblies; a default of all parts would be friendlier.
- [folding_arm] docs_unclear/low: Docs do not say that rotating a Part by a Parameter in build() is the intended way to model pose, nor whether sweep checks pairs only (it reports only the closest pair, not every pair's minimum).
- [folding_arm] other/low: cad sweep prints only the single closest pair per pose, so the forearm-vs-arm gap (0.4 mm headroom) was not visible; I had to trust the min threshold.
- [folding_arm] docs_unclear/low: cad measure --holes with several parts errors 'name one'; docs do not mention a part argument is required for multi-part projects.
- [folding_arm] other/low: cad sweep reports only the single closest pair per step, not every pair (arm<->forearm gap not shown).
- [folding_arm] api_confusing/low: cad measure --holes without a part name fails on multi-part assemblies ('name one'); inspect shows all parts but measure needs a part.
- [param_hole_pattern] other/low: Shell heredoc file creation was blocked by the sandbox/permission layer; had to use the editor Write tool instead. Not a cad problem.
- [param_hole_pattern] docs_unclear/low: Docs do not state explicitly that Parameter() returns a plain number usable in arithmetic (it is implied by 'returns a plain number'); worked fine for center=(plate_width/2, ...).
- [robot_leg] api_confusing/low: cad measure with several parts requires a part name (error 'name one'); no all-parts option for --holes/--thickness.
- [robot_leg] docs_unclear/low: Y sign conventions for XZ-plane slabs (offset=-y0, negative distance) and picking a 3D hole start point outside the part need care.
- [robot_leg] api_confusing/medium: hole() with a 3D 'at' on a Y-axis hole whose start point lies outside the material (Y=0 vs a slab at Y -5.5..-0.5) fails with a generic BOOLEAN_FAILED 'hole cut failed' and no hint; the 2D form at=(x,z) works.
- [robot_leg] other/low: In this session, sed -i on files in the working dir required approval; unrelated to cad but slowed edits.
- [robot_leg] api_confusing/low: cad measure --holes without a part name errors on multi-part assemblies (must name a part); inspect/clearance work without one.
- [robot_leg] api_confusing/low: Rotation sign: rotate about y turns +Z toward +X, so a link hanging along -Z needs a negative angle to swing the foot toward +X. Easy to get backwards; verified via measure --holes at 90 deg.
- [robot_leg] render_missing/low: cad sweep --render only rendered the requested view for the whole assembly under a long filename; render dirs are per revision (r2..r8), not named by angle.
- [sensor_cradle] docs_unclear/low: Reference parts are returned from build() alongside the cradle; it was not obvious whether the task's 'one part named cradle' rule counts reference envelopes. Docs say they are skipped on export, which resolved it.
- [sensor_cradle] query_missing/low: No direct check for 'keep-out region empty' (e.g. the volume above mid-plane or the 8 mm screw-head path); I verified by reasoning from the bbox and by modelling references. Modelling the keep-outs as reference parts would let cad clearance check them.
- [sensor_cradle] other/low: Shell heredoc writes to project files needed approval in the sandbox; had to use the file Write tool. Not a cad issue.
- [sensor_cradle] query_missing/low: I did not model the sensor as a reference part, so cad clearance was not used; contact with the sensor (support) and the no-go regions were verified only by construction (cut with exact envelope cylinder, top at Z=25).
- [sensor_cradle] docs_unclear/low: Unclear whether reference=True envelope parts count as extra parts for a 'one part named cradle' requirement; build output lists 4 parts.
- [sensor_cradle] docs_unclear/low: Cylinder 'at' with axis='x' and align='min': it is not obvious that at gives the axis position (Y,Z) and the start X; I had to confirm from the clearance output.
- [servo_envelope_bracket] other/low: cad clearance flags the intended bottom/top contacts as VIOLATIONs with --min, though per-face gaps show 'contact' for those faces only. Hard to tell allowed from forbidden contact at a glance.
- [servo_envelope_bracket] other/low: cad clearance flags intended contacts (servo bottom/top, clamp on posts) as VIOLATION with --min 0.5; no way to whitelist allowed face contacts.
- [servo_envelope_bracket] other/medium: cad clearance flags intended bottom/top face contact (and bracket<->clamp seating contact) as VIOLATION with --min 0.5; no way to say 'contact allowed on these faces'.
- [servo_envelope_bracket] other/low: Shell environment refused sed -i / braces in heredocs without approval; had to use Write for edits (environment, not cad).
- [split_shaft_clamp] api_confusing/low: `cad measure --holes` without a part name errors out on multi-part revisions ('name one') instead of listing all parts.
- [split_shaft_clamp] docs_unclear/low: Not obvious from docs whether p.holes(..., direction='-z') with 2D `at` starts at the part's top face for a part located below Z=0; verified via measure --holes (it did).
- [split_shaft_clamp] api_missing/low: No dedicated hex-nut pocket helper; had to extrude a regular_polygon cut at an offset plane (worked fine).
- [split_shaft_clamp] api_confusing/low: `cad measure --holes` without a part name errors on multi-part revisions ('name one'), while `cad inspect` works for all parts. Render with --section on multi-part revisions merges all parts into one file named clamp_top_clamp_bottom_*.
- [split_shaft_clamp] query_missing/low: No direct check that two parts do not intersect (interference volume) or that the hex pocket flats are parallel to X; I relied on construction and a section render.
- [split_shaft_clamp] api_confusing/medium: `cad clearance` errors with 'revision has 2 parts; name one' when no --part is given, although the docs say it checks every pair of parts. I could not get the pairwise touch/overlap check for the two halves, so 'must not intersect' was not verified numerically.
- [split_shaft_clamp] workaround/low: p.holes() is for holes entering from a face. I used extrude(Profile.circle, op='cut') at a Z offset to get the exact Z ranges for the through holes and the nut pockets.

## Suggestions

- [folding_arm] cad sweep: print the min gap for every pair, not just the closest.
- [folding_arm] Let cad measure --holes/--thickness default to all parts.
- [folding_arm] Add an example for a multi-part moving assembly.
- [folding_arm] cad sweep should print min gap for every part pair
- [folding_arm] measure --holes without a part could loop over all parts
- [folding_arm] Let measure/query default to all parts
- [folding_arm] Report sweep per-pair min gap summary, not just the closest pair
- [param_hole_pattern] Add a parametric-plate-with-hole_pattern example to the docs, showing center derived from a Parameter.
- [param_hole_pattern] cad set leaves params.toml behind; a 'cad set --reset' / 'cad unset' command would be handy.
- [param_hole_pattern] Add a one-line note in the docs that box(align=('min','min','min')) is the way to put a corner at the origin, next to the hole_pattern example.
- [param_hole_pattern] Mention in the hole_pattern docs that center accepts expressions derived from Parameters, e.g. (w/2, h/2), as a typical use.
- [robot_leg] Let measure accept --all-parts.
- [robot_leg] Note in docs that positive rotation about Y swings a downward link toward -X (I had to negate knee_angle).
- [robot_leg] cad sweep could also produce one combined contact sheet.
- [robot_leg] Make BOOLEAN_FAILED for holes hint that a 3D start point not touching the material produces no cut; suggest the 2D at form.
- [robot_leg] Add an assembly example with a motion parameter on a rotated link layered along Y.
- [robot_leg] Let measure --holes/--thickness default to all parts.
- [robot_leg] Name sweep renders by parameter value (e.g. knee_angle_45_front.png).
- [robot_leg] A rotate_about helper with a 'point toward' hint or example for hanging links.
- [sensor_cradle] Add a keepout/envelope check helper that reports intersection with arbitrary boxes/cylinders.
- [sensor_cradle] Have cad clearance flag when a reference envelope touches a part, so it is clear whether contact is a support or an interference.
- [sensor_cradle] Provide a way to declare keep-out regions (e.g. cable cylinder, lift-out box) as reference parts with an example, and a check that a part touches a reference (distance 0) while not intersecting it.
- [sensor_cradle] Document that reference parts are excluded from deliverable part counts/exports.
- [sensor_cradle] Add a 'cad clearance' check that reports the contact area/points for 'must touch' requirements.
- [sensor_cradle] Offer a keep-out volume as a first-class reference check.
- [servo_envelope_bracket] Let clearance mark specific faces of a reference part as allowed-contact, or print a per-face pass/fail against a min gap.
- [servo_envelope_bracket] Allow 'cad measure --thickness' to report ligaments of holes in a named list.
- [servo_envelope_bracket] Allow cad clearance to declare permitted contact faces or pairs.
- [servo_envelope_bracket] A check for a vertical clear column above a point (e.g. screw-head or shaft path) would help.
- [servo_envelope_bracket] Let cad clearance accept per-face allowed-contact rules (e.g. --allow-contact servo.bottom,servo.top) so the pass/fail exit code is meaningful for envelope tasks.
- [servo_envelope_bracket] A built-in check for 'vertical column above a point is empty of all parts' (screw head / shaft keep-out) would help.
- [split_shaft_clamp] Let measure/inspect default to all parts when a revision has several.
- [split_shaft_clamp] Add a nut_pocket()/hex pocket feature with across-flats and orientation args.
- [split_shaft_clamp] Add an assembly-level interference check (cad clearance for non-reference parts) in docs for 'parts must not intersect'.
- [split_shaft_clamp] Add `cad interference` (or include in `cad clearance`) reporting overlap volume between non-reference parts.
- [split_shaft_clamp] Make measure --holes iterate over all parts by default.
- [split_shaft_clamp] Report hex pocket across-flats/orientation in find_holes-like output for polygon pockets.
- [split_shaft_clamp] Make `cad clearance` default to all pairs when a project has multiple parts.
- [split_shaft_clamp] Document a hex-pocket recipe (regular_polygon across_flats, angle=0 gives flats parallel to the u axis).
- [split_shaft_clamp] Let the 'cad measure --holes' output include hex pocket (non-circular) recesses.
