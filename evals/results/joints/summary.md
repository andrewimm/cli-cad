# Eval run joints

model `sonnet`, git `091d98f`, label `joints`

- attempts: 3, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 39.333, mean failed builds 0.333, mean turns 18.667
- cost: total $0.765 (mean $0.255); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| lamp_arm | 1.0 | 1.0 | 39.333 | 11.333 (0.333) | 1 | 7 | 18.667 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| lamp_arm/a1 | True | 3.3 | 27.2 | None | 68.1 | 48 | 12 | 8 | 10 {'USAGE': 10} | False |
| lamp_arm/a2 | True | 2.8 | 32.6 | None | 69.2 | 32 | 12 | 6 | 9 {'UNKNOWN_REFERENCE': 1, 'VALIDATION_FAILED': 1, 'USAGE': 7} | False |
| lamp_arm/a3 | True | 3.0 | 26.2 | None | 68.3 | 38 | 14 | 7 | 9 {'USAGE': 9} | False |

## cad error codes seen

- USAGE: 26
- UNKNOWN_REFERENCE: 1
- VALIDATION_FAILED: 1

## Feedback issues

- [lamp_arm] api_confusing/medium: `cad sweep` with a negative range start (-45:45:15) fails with 'arguments are required: values' because argparse reads it as a flag. A comma list with negatives fails too. It only works with `--` after the options, e.g. `cad sweep shoulder --min 0.5 -- -45:45:15`. The help doesn't mention this, and the error message is misleading.
- [lamp_arm] api_confusing/low: `cad set` persists poses into params.toml, so a checking pose can be left in the deliverable. I had to reset every parameter to 0 by hand. After the reset, params.toml holds explicit zeros rather than being absent.
- [lamp_arm] docs_unclear/low: `extrude(..., plane='XZ', offset=d)` puts the sketch at Y=-d and positive distances go toward -Y. The docs explain this, but it is easy to get wrong. I had to confirm the Y slabs with `cad measure --bbox` and `--holes`.
- [lamp_arm] docs_unclear/low: Joint docs say to use `part.faces("hinge.wall")` for a hole axis, but a hole made with cylinder(op=cut) exposes `<name>.side`, not `.wall` (UNKNOWN_REFERENCE; the hint did list .side).
- [lamp_arm] api_confusing/medium: `cad sweep PARAM -45:45:15` fails because the negative start is parsed as an option; `--` must come after the other flags (`cad sweep p --min 0.5 -- -45:45:15`). The error only said 'values required'.
- [lamp_arm] api_confusing/low: The XZ-plane extrude offset/sign convention (offset=-y0, negative distance toward +Y) is easy to get wrong. A first-pass turret post, a cylinder, overlapped the lower arm because I forgot its Y extent.
- [lamp_arm] api_confusing/medium: `cad sweep PARAM -45:45:15` (and quoted comma lists starting with a minus) fail with 'the following arguments are required: values' because argparse reads the negative start as an option. Ranges with negative values (every symmetric joint range) can't be swept directly.
- [lamp_arm] workaround/medium: Because of the sweep issue I had to `cad set <joint> <value>` and run `cad clearance` per extreme pose, then reset to 0.
- [lamp_arm] docs_unclear/low: Joint positive direction follows the right-hand rule about the auto-picked +Y axis, so the elbow went the wrong way (lowered the head). `cad joints` wording ('far end moves +Z (up)') caught it, but the docs don't say to check this or that direction='-y' is the usual fix for a Y-axis hinge.
- [lamp_arm] other/low: `cad set` writes joint values to params.toml, so a verification pose persists into the deliverable unless reset to 0 afterwards.

## Suggestions

- [lamp_arm] Make `cad sweep` accept negative ranges directly, for example by using nargs handling or allowing `--values`.
- [lamp_arm] Add a `cad set --reset` or `cad set --temp` so inspection poses don't persist in params.toml.
- [lamp_arm] Let `cad clearance` and `cad sweep` print only violations, or the overall minimum, to keep output short.
- [lamp_arm] Accept negative sweep ranges directly, or say in the error and help how to pass them.
- [lamp_arm] Document hole face names (.side) in the joints section.
- [lamp_arm] Let `cad joints` run with a hint when the parameter-driven pose is non-zero, and add a `cad render --pose yaw=90,...` option that doesn't alter the active revision.
- [lamp_arm] Make sweep accept negative starts (e.g. `--` handling or `START..STOP`), and offer `cad sweep --all-limits` to test each joint's limits.
- [lamp_arm] Offer a `cad sweep --all` that sweeps every joint to its limit extremes and checks clearances.
- [lamp_arm] Warn in `cad set` output that the value was persisted to params.toml.
