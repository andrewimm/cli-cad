# Eval run hc-baseline

model `sonnet`, git `f08a2f5`, label `hc-baseline`

- attempts: 18, **pass rate 0.833**, mean check score 0.983
- self-reported success 1.0 (over-claimed: 3)
- mean cad calls 9.944, mean failed builds 0.222, mean turns 10.889
- cost: total $2.983 (mean $0.166); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| folding_arm | 1.0 | 1.0 | 17 | 4 (0) | 1 | 4 | 16 |  |
| param_hole_pattern | 1.0 | 1.0 | 9.333 | 4 (0) | 0 | 2 | 8 |  |
| robot_leg | 1.0 | 1.0 | 17.667 | 4.667 (0) | 0.667 | 3.667 | 12.333 |  |
| sensor_cradle | 1.0 | 1.0 | 4.333 | 1.333 (0.333) | 0.667 | 1 | 9.333 |  |
| servo_envelope_bracket | 0.0 | 0.9 | 5 | 1.333 (0.333) | 1 | 1 | 10 | {'min_thickness': 3} |
| split_shaft_clamp | 1.0 | 1.0 | 6.333 | 1.667 (0.667) | 1 | 1 | 9.667 |  |

## cad error codes seen

- NO_PROJECT: 9

## Feedback issues

- [folding_arm] docs_unclear/low: The docs never describe multi-part assemblies explicitly (returning a dict of parts, part placement in world coordinates, how parameters like fold_angle interact with rotate). I inferred it from the 'return a Part, list or {name: Part}' line.
- [folding_arm] query_missing/medium: No way to check clearance across a parameter sweep in one command; I had to rebuild per angle with -p and measure --distance each time. Min distance of arm/forearm is the same at every angle by construction (stacked), so I verified 0 and 120 only.
- [folding_arm] docs_unclear/low: Docs do not describe assemblies explicitly (returning a list of Parts places them in a shared world frame), nor how to show a parameterised pose; I inferred it from the 'return a list of Parts' line.
- [folding_arm] query_missing/low: No sweep tool: checking clearance across fold angles needed repeated `cad build -p` and `cad measure --distance` runs; renders per angle land in renders/rN with no label of the parameter value.
- [folding_arm] docs_unclear/low: Docs do not say how to express a parameter-driven rotation of one part inside a multi-part assembly. I had to guess that translate/rotate on a Part mutate in place and that rotate(center=...) or build-at-origin then translate works.
- [folding_arm] query_missing/medium: No built-in sweep check over a parameter range. I rebuilt manually at 0/60/90/120 with -p and ran measure --distance each time. Only 4 angles were checked, so clearance at the other angles is argued from the stacking, not measured.
- [folding_arm] other/low: Renders are per revision directory (renders/rN), so the renders for different fold angles end up in separate revision folders. No option to name or label them with the parameter value.
- [param_hole_pattern] docs_unclear/low: Docs say hole_pattern 'centres the grid' about center=(0,0) with the example using a plate centred at origin; it wasn't explicit whether center is absolute world XY (it is, as verified via inspect) so I had to verify for a corner-origin plate.
- [param_hole_pattern] docs_unclear/low: hole_pattern's center is in plate coordinates only via a one-line note ('centres the grid ... (±24, ±14)'); it was not obvious that center= is an absolute XY position, which matters for plates with a corner at the origin. Confirmed by inspect.
- [robot_leg] docs_unclear/low: Docs do not describe assemblies/multi-part output beyond 'return a list of Parts'; had to guess that a Parameter-driven rotate() on one part works as the articulation, and that rotate about Y needs a negative angle to swing -Z toward +X (right-hand rule, derived by reasoning, then verified through find_holes).
- [robot_leg] query_missing/medium: No built-in all-pairs clearance check across parts or sweep over a parameter; I verified clearance by reasoning (links sit in separate Y layers) plus one distance measure at 90 deg.
- [robot_leg] docs_unclear/low: The rotate() sign convention for Part.rotate about Y vs. the task's 'positive angle swings foot toward +X' needed a numeric check; I had to negate the angle (-knee_angle). Verified via find_holes at 90 deg (foot at x=110).
- [robot_leg] query_missing/medium: No built-in sweep/min-distance check across a parameter range; I had to rebuild with -p at several angles and call measure --distance manually. Clearance is guaranteed here by Y layering, not by a sweep.
- [robot_leg] api_confusing/low: XZ plane extrudes toward -Y and offset=d places the sketch at Y=-d, so placing a slab at a given Y range (e.g. Y 0..5.5) requires offset=-ymax and positive distance; counter-intuitive.
- [robot_leg] other/low: cad measure --holes output has no explicit angle-sorted/flat format; also measure --distance prints full part info each time (noisy).
- [robot_leg] api_confusing/low: Rotation sign for rotate(angle, axis='y') is easy to get wrong: positive angle sends -Z toward -X, so knee_angle needed rotate(-knee_angle). Docs state the right-hand rule but a worked example for 'swing a hanging link toward +X' would help. I verified it via find_holes positions.
- [robot_leg] docs_unclear/medium: Not stated whether Profile.slot length is overall or center-to-center (it is overall, found by checking bbox). Also the XZ plane extrusion direction (-Y) plus offset sign (offset=-ymid puts mid-plane at Y=ymid) takes care to get right.
- [robot_leg] query_missing/medium: No built-in multi-part clearance or sweep check across parameter values. I ran cad set + cad measure --distance manually at 0, 45 and 90 degrees. Only the distance between parts is reported, not a pairwise matrix.
- [robot_leg] workaround/low: There is no hole-along-Y-through-everything helper that takes a 2D position on a part with several features. I cut cylinders with op='cut' on axis y instead. cad set leaves params.toml behind, so I ran cad unset to restore the default angle.
- [robot_leg] other/low: Multi-part assemblies have no placement or joint concept. The rotation of the lower link is baked into the part geometry, so its part coordinates change with the parameter.
- [sensor_cradle] query_missing/medium: No way to declare the sensor envelope as a keep-out/reference solid and have inspect report interference/contact/clearance against it; I relied on cutting an envelope cylinder and did not run a numeric contact check or view a section render.
- [sensor_cradle] other/low: Hole positions given as 2D (x,y) worked fine; no problems with the build.
- [sensor_cradle] query_missing/low: No way to declare the sensor envelope as a reference body and check keep-out/contact/clearance from the CLI; I verified by reasoning about the geometry (cut cylinder R15 at Z=25 gives exact tangent contact). I did not open the renders in detail.
- [sensor_cradle] query_missing/low: No way to declare the sensor envelope / keep-out volumes and check clearance or touching in the CLI; I verified by reasoning and one render. I did not try building envelope Parts for distance_to/interference.
- [sensor_cradle] other/low: find_holes reports the sensor-seat cylindrical cut as a 'hole' d=30, which is noise when looking for screw holes.
- [servo_envelope_bracket] other/low: Shell redirection/heredoc file creation was blocked by the harness approval; had to use the Write tool. Not a cad issue.
- [servo_envelope_bracket] query_missing/low: No built-in way to check a requirement like 'clear vertical column above a point' or 'min clearance from an envelope box'; I verified by reasoning from dimensions rather than a query. Envelope boxes would need to be built as helper Parts to use distance_to.
- [servo_envelope_bracket] other/low: Compound shell commands (heredocs followed by several cad calls) were blocked by the sandbox approval, so I had to write files with the Write tool. This is environment friction, not a cad bug.
- [servo_envelope_bracket] query_missing/low: I did not run cad measure --distance between the parts and the servo envelope, and I did not run any clearance or keepout check. The envelope is not a model object, so I checked the numbers by hand.
- [servo_envelope_bracket] query_missing/low: No way to import/declare the servo envelope as a reference body, so clearance (>=0.5 mm) and contact checks against it were done by hand arithmetic rather than with distance_to/interference.
- [split_shaft_clamp] docs_unclear/low: Hex pocket orientation (flats parallel to X) had to be inferred from the regular_polygon note (angle=0 -> flats at v=±AF/2); I did not verify it numerically, only in a section render.
- [split_shaft_clamp] query_missing/low: No obvious CLI to measure the interference/distance between two parts of the same project in one command; I relied on construction (touching at Z=0) instead.
- [split_shaft_clamp] docs_unclear/low: Hex orientation: had to infer that regular_polygon angle=0 (corner on +u) gives flats parallel to X; docs say flats at v=±af, which was enough but needed a moment of thought.
- [split_shaft_clamp] api_confusing/low: cylinder(axis='x', align=...) semantics for where 'at' sits along the axis were only briefly described; used align='min' starting beyond the part and a long length.
- [split_shaft_clamp] query_missing/low: find_holes/inspect does not report the half-bore (open half-cylinder) as a hole, so the 8.2 mm bore could only be verified visually via section render.
- [split_shaft_clamp] docs_unclear/low: Cylinder 'align' semantics for axis='x' with at= were inferred (align='min' starts at the 'at' point along the axis); worked but not shown in an example.

## Suggestions

- [folding_arm] Add 'cad sweep fold_angle=0:120:30 --measure-distance a,b' for assembly clearance checks.
- [folding_arm] Document assembly conventions and that renders are stored per revision (so different angles need different builds).
- [folding_arm] Add an assembly/motion docs section with an example sweeping a parameter and checking min distance.
- [folding_arm] Include parameter values in render folder names or metadata.
- [folding_arm] Let `cad measure --distance` print only a summary rather than the full part report.
- [folding_arm] Add an assembly section to the docs showing a posed/articulated multi-part example.
- [folding_arm] Add `cad sweep fold_angle 0:120:10 --distance a b` or similar for pairwise clearance over a parameter range.
- [folding_arm] Include parameter values in render filenames or the directory name.
- [param_hole_pattern] State explicitly that hole_pattern center is in world coordinates, and show an example with a corner-origin box.
- [param_hole_pattern] Document that hole_pattern center is in absolute plate coordinates (not relative to the part) with an example for corner-origin plates.
- [param_hole_pattern] Add a docs example of hole_pattern on a corner-origin plate with center=(w/2, h/2).
- [param_hole_pattern] Offer a center='part' option for hole_pattern.
- [robot_leg] Add a 'cad check clearance' for all part pairs, optionally sweeping a parameter range.
- [robot_leg] Document the Profile.slot angle semantics and that 'length' is overall end-to-end.
- [robot_leg] Allow render to take -p knee_angle=45 without rewriting params.toml.
- [robot_leg] Add a box-with-Y-range helper or an extrude option taking absolute start/end coordinates along the normal.
- [robot_leg] Add `cad measure A --distance B -p knee_angle=0:90:15` sweep support.
- [robot_leg] Document that rotate on a returned Part list member mutates in place and how assemblies use parameters for motion.
- [robot_leg] Add an assembly example, such as a hinge or linkage, that uses a rotating parameter and separate parts.
- [robot_leg] Add a cad check or measure --all-pairs command that prints the pairwise distance matrix and can sweep a parameter over a range.
- [robot_leg] State in the docs whether Profile.slot length is overall, and add a pivot-aware rotate example.
- [robot_leg] Render all parts in one image at several parameter values with one command, for example render -p knee_angle=0,45,90.
- [sensor_cradle] Allow named keep-out solids in cad.toml checked by inspect (interference, contact distance, vertical-path clearance for screw heads).
- [sensor_cradle] Allow non-part 'envelope' bodies for distance/interference checks and render overlays.
- [sensor_cradle] Allow a keepout/envelope declaration in the project that cad inspect checks automatically.
- [sensor_cradle] Let find_holes filter by through/vertical or diameter.
- [servo_envelope_bracket] Add a way to declare keep-out/envelope volumes in the project and check clearance/interference against them via cad measure.
- [servo_envelope_bracket] A 'cad check' for min wall thickness would be useful.
- [servo_envelope_bracket] Let a project declare reference or envelope solids that are excluded from export but available to measure --distance and interference.
- [servo_envelope_bracket] Add a helper that reports the minimum wall thickness around holes.
- [servo_envelope_bracket] Allow declaring non-exported 'envelope' parts for distance/interference checks and rendering.
- [servo_envelope_bracket] Add a column-clearance query (is a vertical cylinder of D at (x,y) free of all parts).
- [split_shaft_clamp] Add a worked example for split/two-part assemblies with hex nut pockets.
- [split_shaft_clamp] inspect could report hex pocket (non-circular recess) dimensions and flat orientation.
- [split_shaft_clamp] Add a worked example for a split/two-part assembly with a bore and nut pockets.
- [split_shaft_clamp] Let hole() take a 'name' collision-free pattern; names with negative numbers like screw_t-10 are ugly.
- [split_shaft_clamp] Report partial/open cylindrical cuts (half bores) in find_holes or a separate 'cylindrical cuts' list.
- [split_shaft_clamp] Add a hex-pocket / nut-trap helper or doc example showing regular_polygon across_flats orientation relative to a given axis.
