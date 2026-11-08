# Eval run new-tasks-smoke

model `sonnet`, git `cdd7c38`, label `new-tasks-smoke`

- attempts: 4, **pass rate 0.75**, mean check score 0.975
- self-reported success 1.0 (over-claimed: 1)
- mean cad calls 9.5, mean failed builds 0, mean turns 11
- cost: total $0.714 (mean $0.178); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| param_hole_pattern | 1.0 | 1.0 | 10 | 4 (0) | 0 | 2 | 9 |  |
| robot_leg | 1.0 | 1.0 | 16 | 4 (0) | 1 | 4 | 19 |  |
| servo_envelope_bracket | 0.0 | 0.9 | 5 | 1 (0) | 1 | 1 | 8 | {'min_thickness': 1} |
| split_shaft_clamp | 1.0 | 1.0 | 7 | 1 (0) | 1 | 1 | 8 |  |

## cad error codes seen


## Feedback issues

- [param_hole_pattern] docs_unclear/low: hole_pattern docs say the grid is centred on `center` but do not state clearly that center is in absolute part coordinates (it is, since my plate corner is at the origin and center=(w/2,h/2) worked); only inferred from the example.
- [param_hole_pattern] other/low: `cad set` leaves a params.toml with an override equal to the default after resetting; no `cad unset`/reset noticed.
- [robot_leg] docs_unclear/low: Docs don't describe how to build a multi-part assembly with a motion parameter; I had to infer that returning a dict of Parts and rotating one part by a Parameter works. Rotation sign for 'swing toward +X' (rotate -a about y) had to be verified by measurement.
- [robot_leg] api_confusing/low: XZ plane offset=d places the sketch at Y=-d and extrudes toward -Y; computing Y layers needs care (negative offsets for +Y positions).
- [robot_leg] query_missing/medium: No one-shot clearance sweep across a parameter range (had to set angle, rebuild and measure distances manually). Only checked angles 0, 60, 90 by distance; clearance is guaranteed by the Y gap by construction.
- [servo_envelope_bracket] query_missing/medium: No built-in way to declare an envelope/keep-out body and check clearance of parts against it (side-face 0.5 mm clearance, 7 mm shaft column); I verified by hand arithmetic from the model dimensions only.
- [servo_envelope_bracket] other/low: Bash heredoc writes into the workspace needed approval in my sandbox; had to use the file Write tool. Not a cad problem.
- [split_shaft_clamp] docs_unclear/low: Cutting a pocket from a given Z face needs extrude(plane='XY', offset=z) with a positive distance going +Z; this is inferable but not stated for pockets opening on a bottom face. A hex-pocket recipe would help.
- [split_shaft_clamp] other/low: Feature names containing a minus sign (e.g. 'screw-10') are accepted but produce awkward ref names like 'screw-10.side'.

## Suggestions

- [param_hole_pattern] State explicitly that hole_pattern center is in part coordinates, and the count=(nx, ny) order.
- [param_hole_pattern] Add a cad unset/reset for parameter overrides.
- [robot_leg] Add a docs section on assemblies/motion parameters and a 'cad sweep PARAM a:b:n --measure ...' command.
- [robot_leg] Allow rotate to take an axis-through-point more explicitly in docs with a sign example for each axis.
- [servo_envelope_bracket] Add a helper to build a reference 'envelope' Part that is excluded from export, with `cad measure --distance` between it and each part.
- [servo_envelope_bracket] Add a vertical-column clearance query (cylinder of given diameter above a point) reporting any intersecting parts.
- [servo_envelope_bracket] Document multi-part assemblies' section render naming (the sheet combines all parts into one image).
- [split_shaft_clamp] Add a hex nut pocket / captive nut recipe to the docs.
- [split_shaft_clamp] Add a half-bore / split-part example.
- [split_shaft_clamp] Offer a 'cad check' for interference between all parts in a multi-part project.
