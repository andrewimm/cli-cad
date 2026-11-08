# Eval run sweep

model `sonnet`, git `a9194a6`, label `sweep`

- attempts: 3, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 12, mean failed builds 0, mean turns 11
- cost: total $0.445 (mean $0.148); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| towel_hook | 1.0 | 1.0 | 12 | 1.667 (0) | 1.333 | 4 | 11 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| towel_hook/a1 | True | 2.6 | 23.7 | None | 44.8 | 12 | 6 | 4 | 0  | False |
| towel_hook/a2 | True | 2.8 | 14.3 | None | 32.7 | 12 | 6 | 4 | 0  | False |
| towel_hook/a3 | True | 3.0 | 15.4 | None | 35.6 | 12 | 5 | 4 | 0  | False |

## cad error codes seen


## Feedback issues

- [towel_hook] api_confusing/medium: Drilling a hole with a 2D `at` and direction -y starts from the +Y side, so the hole at z=20 drilled through the hook's vertical rod (reported depth 46.75) instead of only the plate. Had to use a 3D start point on the front face (y=5) with depth=5. The 2D-at 'first enters material' rule is surprising when another feature is in the path.
- [towel_hook] docs_unclear/low: Plate-front countersinks drilled from the +Y side need a note on how to restrict them to one feature when the part has other geometry in the drilling line.
- [towel_hook] query_missing/low: cad measure --holes reports countersunk holes as plain d=4.5 with a depth of 2.75 and position y=0; it does not show the countersink diameter/angle or the entry face.
- [towel_hook] api_confusing/medium: A 2D `at` with direction='-y' and no depth drills through everything, including the hook rod rising behind the plate at the same X/Z (hole at z=20 cut through the vertical rod at y=45). The 2D 'first enters material' rule plus 'through everything' is easy to misuse when other features sit in line behind the plate. I only noticed because measure --holes reported depth 46.7.
- [towel_hook] docs_unclear/low: Hole 'position' in measure --holes is reported at y=0 (the back face) with axis +Y, depth 2.7 for a countersunk 5 mm plate; the depth semantic (excludes countersink?) is not documented.
- [towel_hook] docs_unclear/low: Hole direction semantics for a countersink on the +Y (front) face: had to infer that direction='-y' drills from the +Y side and puts the countersink on the front. Table helps but a plate-on-wall example would be clearer.
- [towel_hook] query_missing/low: measure --holes reports hole depth 3.0 and position y=0 for a countersunk hole in a 5 mm plate, without mentioning the countersink dimensions; hard to verify countersink diameter numerically.

## Suggestions

- [towel_hook] Warn when a hole drilled from a 2D `at` passes through unexpectedly large material (e.g. depth far larger than the nearest wall).
- [towel_hook] Report countersink/counterbore parameters in measure --holes.
- [towel_hook] Allow holes() to take a target feature or face (e.g. on=plate.front) to limit where they start.
- [towel_hook] Warn when a through hole cuts a feature other than the one it enters (or add a 'stop at first exit' option).
- [towel_hook] Document sweep profile orientation for a path starting along +Y (circle is symmetric so it did not matter here).
- [towel_hook] Report countersink/counterbore diameter and angle in measure --holes.
- [towel_hook] Add a wall-plate-with-hook recipe using Path.polyline(radius=).
