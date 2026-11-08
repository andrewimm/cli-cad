# Eval run hc-v5

model `sonnet`, git `a9ad97e`, label `hc-v5`

- attempts: 18, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 10.111, mean failed builds 0, mean turns 11.722
- cost: total $3.112 (mean $0.173); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| folding_arm | 1.0 | 1.0 | 11.333 | 2.333 (0) | 0.667 | 2.333 | 14.333 |  |
| param_hole_pattern | 1.0 | 1.0 | 9.333 | 3.333 (0) | 0 | 2 | 8 |  |
| robot_leg | 1.0 | 1.0 | 15 | 3.333 (0) | 1 | 2.333 | 15 |  |
| sensor_cradle | 1.0 | 1.0 | 6.667 | 1 (0) | 0 | 2.333 | 9.333 |  |
| servo_envelope_bracket | 1.0 | 1.0 | 11.333 | 2 (0) | 0.667 | 2.667 | 14.667 |  |
| split_shaft_clamp | 1.0 | 1.0 | 7 | 1 (0) | 1 | 2.333 | 9 |  |

## cad error codes seen


## Feedback issues

- [folding_arm] other/low: Renders from only fold angles 0 (r1) and 90 (r9) were kept; sweep revisions r2-r8 were built without renders. Rendering at a second angle needed `cad set` then `cad render`, which creates a new revision each time.
- [folding_arm] docs_unclear/low: `cad measure --thickness` prints a long list of sample points rather than a single minimum, so the minimum is hard to read at a glance.
- [folding_arm] docs_unclear/low: Unclear whether sweep's 'closest' line reports only the single closest pair or checks every pair; the output only names arm<->base_block even though the forearm is the moving part, so it is hard to see the forearm was checked.
- [folding_arm] query_missing/low: measure --thickness includes the wall around holes in the base, which the task did not require, and it gives no per-part pass/fail threshold flag.
- [folding_arm] docs_unclear/low: Docs don't say whether 'at least 0.5 mm' passes at exactly 0.5; I used 1.0 mm gaps to be safe.
- [robot_leg] docs_unclear/low: Rotation sign for swinging a downward-pointing link toward +X needs a negative angle about Y; the docs state the rule but I had to derive the sign myself.
- [robot_leg] api_confusing/low: XZ-plane extrude offset/distance sign convention (offset=-y0, negative distance) is non-obvious; the doc example helped.
- [robot_leg] other/low: cad sweep renders are written into per-revision dirs (r2..r13) and clutter the project; no way to name or collect them.
- [robot_leg] docs_unclear/medium: XZ plane offset/extrude sign (offset=d -> Y=-d, positive distance -> -Y) is easy to get wrong; my first base_mount landed at Y -4..2 and overlapped the upper link until I checked bbox.
- [robot_leg] api_confusing/low: Rotating the lower link: positive rotation about y turns -Z toward -X, so the knee needed rotate(-knee). Docs state the rule but a worked example of a hanging link would help.
- [robot_leg] other/low: Shell sandbox rejected heredoc writes to files and commands containing dict braces with quotes; had to use the Write tool.
- [robot_leg] docs_unclear/low: Sign convention for swinging a -Z-pointing link toward +X (rotate about y by -angle) had to be reasoned out and verified via hole positions.
- [sensor_cradle] docs_unclear/low: Docs don't say how to model 'touch but not intrude'; I cut an equal-diameter cylinder Part, giving exact tangent contact. Clearance reports contact correctly.
- [sensor_cradle] other/low: cad clearance lists reference-vs-reference pairs (cable/sensor touching) which is noise.
- [sensor_cradle] other/low: Reference envelopes that deliberately share space (sensor body vs lift-out volume) are reported as 'overlap' by cad clearance, which is noisy; no way to mark reference-vs-reference pairs as ignorable.
- [sensor_cradle] query_missing/low: No dedicated contact check for a cut seat touching the sensor; I had to read the clearance output (it showed 'touching', which worked).
- [servo_envelope_bracket] other/low: Reference-envelope clearance output is verbose; hard to see at a glance that the 6 mm screw-head paths and 7 mm shaft column are clear (no way to declare keep-out columns).
- [servo_envelope_bracket] other/low: I did not visually inspect the PNG renders (only generated them); verification relied on numeric checks (clearance, thickness, holes).
- [servo_envelope_bracket] docs_unclear/low: Doc does not say whether the 7 mm shaft column starts at the servo top (Z=50) or extends from Z=0; I kept the whole column above Z=50 clear.
- [servo_envelope_bracket] query_missing/medium: No built-in check for a vertical screw-head path (6 mm cylinder above a hole) or a shaft column against all parts. I checked it by hand from the coordinates.
- [servo_envelope_bracket] other/low: Reference box clearance output is long and per-face. It was useful for the 0.5 mm side gaps, but a pass/fail summary line would help.
- [servo_envelope_bracket] workaround/low: No visible way to make a hole's ligament check ignore pilot holes; I had to size the clamp plate by trial (2.8 mm ligament at first) using measure --thickness.
- [split_shaft_clamp] docs_unclear/low: Cutting a hex pocket from the bottom face needed extrude with plane XY offset=-12 and positive distance (going +Z); the docs' offset/normal table made this derivable but there is no 'pocket' helper for polygon pockets.
- [split_shaft_clamp] query_missing/low: No direct check that a hex pocket's flats are parallel to X or its across-flats size; I relied on the construction (angle=0 gives flats at v=±AF/2).
- [split_shaft_clamp] other/low: Shell redirection (heredoc) to create model.py was blocked by the sandbox; had to use a file-write tool. Not a cad issue.
- [split_shaft_clamp] docs_unclear/low: For a 3D hole start point, it was not obvious whether depth is measured from that point; I had to try it and check cad measure --holes. Also unclear that a hole starting exactly on a face needs the 3D form.
- [split_shaft_clamp] query_missing/low: No direct check that two parts do not intersect or touch only at a plane (e.g. interference volume); I relied on construction.

## Suggestions

- [folding_arm] Print the minimum wall thickness as a summary line in `cad measure --thickness`.
- [folding_arm] Allow `cad render --param fold_angle=90` without modifying params.toml.
- [folding_arm] Have `cad measure --holes` show hole axis positions in assembly frame consistently (all holes were listed).
- [folding_arm] Make cad sweep print the minimum gap for every pair at every value, not just the closest pair.
- [folding_arm] Add a convenience for a link/slot with pivot holes (stadium plate with end holes).
- [folding_arm] Add a clear note in the docs that a part's rotate() after translate() works about a world-frame centre.
- [folding_arm] Sweep output could list min clearance per part pair at every step, not just the closest pair.
- [param_hole_pattern] Parameter defaults could be shown in `cad docs` next to hole_pattern example with a plate-corner-at-origin case (center=(w/2,h/2)).
- [param_hole_pattern] A Part.hole_pattern/grid helper for rectangular hole arrays would avoid the manual loop.
- [param_hole_pattern] Allow shell heredoc file creation, or document that Write is the way to author model.py.
- [param_hole_pattern] Let hole_pattern accept center='part' (or default to the part bbox centre) so the pattern centring doesn't need a manual plate_width/2 expression.
- [robot_leg] Add a 'revolute link' example (slot-shaped link with pivot holes, Y-layered) to cad examples.
- [robot_leg] Let cad sweep write its renders to a named folder.
- [robot_leg] Report clearance sweeps as the minimum across all pairs, not only the closest pair.
- [robot_leg] Add an assembly example with a hinged link and layered Y slabs.
- [robot_leg] cad sweep could print the foot/hole positions per angle to verify the kinematics.
- [robot_leg] Show part Y-range in build summary.
- [robot_leg] Add a worked example of an articulated two-link assembly with a motion parameter
- [robot_leg] Let sweep report per-pair minimum gaps, not only the closest pair
- [sensor_cradle] Allow cut() with a reference Part directly
- [sensor_cradle] Support keep-out boxes as references and flag any intersection
- [sensor_cradle] Option to ignore reference-vs-reference pairs in cad clearance
- [sensor_cradle] Allow excluding pairs in cad clearance (e.g. ignore reference-vs-reference pairs).
- [sensor_cradle] Add a 'keep-out' reference kind for regions that must stay empty.
- [sensor_cradle] A keep-out volume check (reference part for the lift-out region) would let clearance verify the 'nothing above mid-plane' requirement directly.
- [servo_envelope_bracket] Allow reference keep-out volumes (e.g. screw-head columns) with a cad clearance check against them.
- [servo_envelope_bracket] Warn when a clearance 'touching' pair is intentional versus contact on a side face.
- [servo_envelope_bracket] Add a `cad clearance`-style check for keep-out cylinders or columns defined as reference parts, with a pass/fail result.
- [servo_envelope_bracket] Document the hole-ligament thickness behaviour of `--thickness` (it reported 2.8 mm for a hole near a plate edge, which was helpful).
- [servo_envelope_bracket] Add a worked example of an envelope-based bracket with a removable clamp plate.
- [servo_envelope_bracket] Let cad clearance take a per-pair expectation, e.g. contact allowed only on named faces.
- [split_shaft_clamp] Add a pocket(profile, depth, face=...) helper or polygon pocket option on hole().
- [split_shaft_clamp] Report non-circular pockets in measure --holes.
- [split_shaft_clamp] Add a built-in way to check that a hex pocket's flats are parallel to a given axis (e.g. query on planar face normals grouped by direction).
- [split_shaft_clamp] Add `cad interference` reporting overlap volume between parts and contact area.
- [split_shaft_clamp] Document the hex orientation for regular_polygon in a worked nut-pocket example.
