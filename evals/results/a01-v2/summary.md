# Eval run a01-v2

model `sonnet`, git `af455c4`, label `a01-v2`

- attempts: 5, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 7, mean failed builds 0, mean turns 7
- cost: total $0.489 (mean $0.098); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| onboarding_plate | 1.0 | 1.0 | 7 | 1 (0) | 0 | 2 | 7 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| onboarding_plate/a1 | True | 3.7 | 13.1 | 16.4 | 24.3 | 7 | 4 | 2 | 0  | True |
| onboarding_plate/a2 | True | 3.9 | 13.5 | 16.2 | 25.5 | 7 | 4 | 2 | 0  | True |
| onboarding_plate/a3 | True | 3.4 | 13.5 | 16.2 | 25.7 | 7 | 4 | 2 | 0  | True |
| onboarding_plate/a4 | True | 3.1 | 13.1 | 16.2 | 24.5 | 7 | 4 | 2 | 0  | True |
| onboarding_plate/a5 | True | 2.9 | 12.9 | 16.2 | 25.4 | 7 | 4 | 2 | 0  | True |

## cad error codes seen


## Feedback issues

- [onboarding_plate] other/low: Hole 'at' reported as z=0 (bottom) in inspect although holes are drilled from the top; minor confusion about hole start point.
- [onboarding_plate] docs_unclear/low: TASK.md leaves plate thickness and hole diameter/position unspecified; I chose 4 mm thick, 4 mm holes at (+-24, +-14). The tool cannot help with such choices, but nothing in the docs suggests typical defaults.
- [onboarding_plate] docs_unclear/low: Task did not specify hole diameter/positions/thickness; I chose 4 mm holes on a 50x30 grid, 4 mm thick. No guidance on the tool's side about printable defaults (min wall, etc.). Inspect reports hole 'at' z=0 with depth 4, slightly ambiguous about the hole start face.
- [onboarding_plate] other/low: Hole depth in inspect reported 'at z=0, depth 4' for holes drilled from the top; start point shown as z=0 is slightly ambiguous.
- [onboarding_plate] docs_unclear/low: The task did not specify hole diameter, plate thickness or hole positions; I picked 4 mm holes, 4 mm thick, 50x30 mm spacing. The tool gave no hint about printable defaults such as minimum wall or hole size.
- [onboarding_plate] other/low: inspect reports hole 'at' z=0 with depth 4, which is ambiguous (bottom face rather than entry point).

## Suggestions

- [onboarding_plate] Mention in the getting-started block that hole_pattern exists (centred grid) for the common 4-hole plate.
- [onboarding_plate] Show hole start/depth direction more clearly in inspect output.
- [onboarding_plate] Mention in the getting-started block that hole_pattern(d, spacing, count) is the quickest way to make 4 corner holes.
- [onboarding_plate] Print the STL path and a printability note (watertight, manifold) from export.
- [onboarding_plate] Show a complete minimal plate-with-holes example in cad --help or the init template comment.
- [onboarding_plate] Offer a printability check (min wall/edge distance) in inspect or export.
- [onboarding_plate] Note in the template that box is centred in X/Y with bottom on Z=0 (it is only in a comment).
- [onboarding_plate] Mention in the getting-started block that hole_pattern is centred and spacing is centre-to-centre.
- [onboarding_plate] Show the hole start face in inspect output.
- [onboarding_plate] Add a printability check on export (min wall, min hole diameter) or a note on it.
- [onboarding_plate] Show a complete minimal plate-with-holes example in the cad --help getting-started block.
- [onboarding_plate] Have inspect state whether a hole's 'at' is the entry point or the center of its axis.
