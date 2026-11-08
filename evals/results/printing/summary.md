# Eval run printing

model `sonnet`, git `475bf1d`, label `printing`

- attempts: 3, **pass rate 0.667**, mean check score 0.952
- self-reported success 1.0 (over-claimed: 1)
- mean cad calls 18, mean failed builds 0.333, mean turns 13
- cost: total $0.691 (mean $0.23); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| printed_pipe_clamp | 0.667 | 0.952 | 18 | 1.333 (0.333) | 1 | 8.667 | 13 | {'python': 1} |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| printed_pipe_clamp/a1 | False | 3.7 | 22.1 | None | 48.5 | 17 | 8 | 8 | 2 {'NO_PROJECT': 2} | False |
| printed_pipe_clamp/a2 | True | 3.5 | 19.5 | None | 46.6 | 20 | 8 | 9 | 0  | False |
| printed_pipe_clamp/a3 | True | 3.3 | 18.2 | None | 44.2 | 17 | 8 | 9 | 1 {'NOT_FOUND': 1} | False |

## cad error codes seen

- NO_PROJECT: 2
- NOT_FOUND: 1

## Feedback issues

- [printed_pipe_clamp] docs_unclear/low: Docs do not say that cad slice reports one combined time/weight for all parts on one plate; per-part numbers are not shown.
- [printed_pipe_clamp] docs_unclear/low: Not stated that kind='nut' puts the pocket on the exit side of a through-drill (it does, at the part bottom); verified via section render.
- [printed_pipe_clamp] query_missing/low: cad inspect lists nut pockets neither as holes nor with dimensions unless I read --features; I verified the hex pocket via measure --section z=1.5 instead.
- [printed_pipe_clamp] docs_unclear/low: Docs don't say which end the nut pocket goes for screw_hole(kind='nut') (it is at the far end of the drill direction, which worked here), nor that bottom_chamfer on a print_on part chamfers the printed bed face.
- [printed_pipe_clamp] query_missing/low: screw_hole kind=nut does not list the hex pocket in `cad inspect` holes (only the 4.5 clearance hole); I verified the pocket via a z-section and a section render.
- [printed_pipe_clamp] docs_unclear/low: Docs don't say where the nut pocket ends up, or that a 3D 'at' (x,y,30) is needed for the counterbore on a part that doesn't start at Z=0; worked by trial.
- [printed_pipe_clamp] other/low: cad slice reports one combined time/weight for both parts, not per part, so PRINT.md gives the combined figure.

## Suggestions

- [printed_pipe_clamp] Report per-part print time/grams in cad slice output.
- [printed_pipe_clamp] Add a pipe-clamp example with split halves, nut pockets and counterbores.
- [printed_pipe_clamp] Document which side screw_hole(kind='nut') places the pocket.
- [printed_pipe_clamp] List nut pockets and counterbores in cad inspect's hole summary with across-flats and depth.
- [printed_pipe_clamp] cad slice with several parts could report per-part time/grams by default as well as the combined plate.
- [printed_pipe_clamp] Give a worked two-half clamp example (split bore, print_on).
- [printed_pipe_clamp] List nut pockets in cad inspect holes (AF, depth, Z range).
- [printed_pipe_clamp] Per-part time/grams in cad slice output.
- [printed_pipe_clamp] Screw-length fit check for head/nut stack.
