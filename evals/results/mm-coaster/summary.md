# Eval run mm-coaster

model `sonnet`, git `3aef587`, label `mm-coaster`

- attempts: 3, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 10, mean failed builds 0, mean turns 9.333
- cost: total $0.382 (mean $0.127); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| multimaterial_coaster | 1.0 | 1.0 | 10 | 1 (0) | 1 | 5.333 | 9.333 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| multimaterial_coaster/a1 | True | 6.3 | 15.0 | 15.9 | 25.3 | 9 | 4 | 5 | 0  | True |
| multimaterial_coaster/a2 | True | 6.8 | 14.3 | 15.0 | 26.5 | 12 | 5 | 6 | 0  | True |
| multimaterial_coaster/a3 | True | 6.5 | 15.4 | 16.2 | 29.7 | 9 | 4 | 5 | 0  | True |

## cad error codes seen


## Feedback issues

- [multimaterial_coaster] docs_unclear/low: It is not obvious which 3MF mode fits 'both parts in one 3MF, printed in one go'. 'objects' (the default) gives two objects, and 'multimaterial' gives one object with material regions. I used the default.
- [multimaterial_coaster] api_missing/low: I found no way to set the 3MF mode in cad.toml [export]. It is only a CLI flag.
- [multimaterial_coaster] query_missing/low: I found no direct check that the two parts touch without overlapping. cad clearance only covers reference parts. I relied on the bboxes, the volumes and the section render.
- [multimaterial_coaster] docs_unclear/low: The task says 'one 3MF with both parts' but it is not obvious whether to use objects mode (default) or multimaterial mode. I chose the default (two objects, each with its own material). The docs do not say which one a slicer user should pick for a recess plus insert.
- [multimaterial_coaster] api_confusing/low: cad.toml [export] has no documented key for the 3MF mode. A later 'cad export --format 3mf' without the flag silently overwrote the multimaterial file with an objects-mode file.
- [multimaterial_coaster] render_missing/low: Section render paints every cut face the same red, so the PLA/TPU boundary is only a thin line and the two materials can't be told apart in the cut.
- [multimaterial_coaster] docs_unclear/low: The docs don't say which 3MF mode fits 'one file, both parts, one print'. I used the default (objects: one object per part). I didn't exercise multimaterial mode, and cad.toml has no documented key for it.

## Suggestions

- [multimaterial_coaster] Add a per-project 3mf_mode option in cad.toml.
- [multimaterial_coaster] Add a 'cad measure --contact' or an overlap/contact report between parts.
- [multimaterial_coaster] Print the 3MF overlap-check result in the export output even when it passes.
- [multimaterial_coaster] Document an [export] 3mf_mode key in cad.toml.
- [multimaterial_coaster] Add a recipe for 'recess plus insert': cut the recess in one part and add a matching cylinder as a second part.
- [multimaterial_coaster] Have cad inspect or cad clearance report contact and overlap between parts, to confirm that the parts touch without overlapping.
- [multimaterial_coaster] Colour section cut faces by part material.
- [multimaterial_coaster] Document a cad.toml [export] key for the 3MF mode.
- [multimaterial_coaster] Add a cad measure/query that reports touching or overlapping parts and their contact area, so flush-fit insets can be checked numerically.
