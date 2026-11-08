# Eval run mm-coaster-v2

model `sonnet`, git `1308220`, label `mm-coaster-v2`

- attempts: 3, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 7.667, mean failed builds 0, mean turns 9.333
- cost: total $0.353 (mean $0.118); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| multimaterial_coaster | 1.0 | 1.0 | 7.667 | 1 (0) | 1 | 2.667 | 9.333 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| multimaterial_coaster/a1 | True | 6.4 | 14.3 | 15.1 | 23.9 | 8 | 4 | 3 | 0  | True |
| multimaterial_coaster/a2 | True | 6.6 | 14.8 | 15.6 | 21.1 | 7 | 5 | 2 | 0  | True |
| multimaterial_coaster/a3 | True | 6.2 | 14.4 | 15.1 | 21.7 | 8 | 4 | 3 | 0  | True |

## cad error codes seen


## Feedback issues

- [multimaterial_coaster] docs_unclear/low: The `cad docs materials` section never states that the insert's flush top face and the coaster's recess floor/wall count as 'touching' rather than overlapping; I had to run `cad clearance` to confirm it (it reported touching, 0 mm).
- [multimaterial_coaster] other/low: Section render shows both parts in similar tints, so the PLA/TPU boundary is only visible as a thin dark line; hard to confirm flush top visually (numbers from cad clearance confirmed it).

## Suggestions

- [multimaterial_coaster] Put a minimal recess + inlay example in the docs; the task here is the canonical case.
- [multimaterial_coaster] Have `cad export` print a one-line confirmation of the 3MF mode used (multimaterial vs objects), and mention when it comes from cad.toml.
- [multimaterial_coaster] A one-line 'inlay in a recess' example in the materials docs would speed up the first attempt.
- [multimaterial_coaster] Mention in the Materials docs that a cylinder cut with at=(0,0,z) is the idiomatic way to make a recess and a matching insert part.
- [multimaterial_coaster] Section renders could use distinct colours per part material.
