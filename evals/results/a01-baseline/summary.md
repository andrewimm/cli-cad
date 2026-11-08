# Eval run a01-baseline

model `sonnet`, git `0ff5867`, label `a01-baseline`

- attempts: 5, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 10.4, mean failed builds 0, mean turns 8.6
- cost: total $0.65 (mean $0.13); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| onboarding_plate | 1.0 | 1.0 | 10.4 | 1 (0) | 0 | 5 | 8.6 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| onboarding_plate/a1 | True | 3.4 | 15.4 | 16.3 | 25.7 | 11 | 5 | 5 | 0  | True |
| onboarding_plate/a2 | True | 3.0 | 16.0 | 18.7 | 27.6 | 11 | 6 | 5 | 0  | True |
| onboarding_plate/a3 | True | 3.2 | 15.1 | 16.0 | 26.7 | 9 | 6 | 5 | 0  | True |
| onboarding_plate/a4 | True | 2.5 | 17.6 | 18.4 | 28.0 | 11 | 6 | 5 | 0  | True |
| onboarding_plate/a5 | True | 2.7 | 16.0 | 17.1 | 26.2 | 10 | 5 | 5 | 0  | True |

## cad error codes seen


## Feedback issues

- [onboarding_plate] docs_unclear/low: The docs excerpt I read did not show hole_pattern's signature; I learned it only from the plate_with_holes example (diameter first, spacing=, count=). I did not read the rest of the docs.
- [onboarding_plate] docs_unclear/low: The task gave no hole diameter or positions; I chose 4 mm holes on a 50x30 grid, 4 mm thick plate. Nothing in the tool could help with this.
- [onboarding_plate] other/low: The hole position in `cad measure --holes` is reported at z=0 (the bottom face) for a drill-from-top hole. This is slightly surprising but harmless.
- [onboarding_plate] docs_unclear/low: Task says 'printable' but nothing in docs says what that implies (min wall, hole size, STL units/watertightness). I assumed 4 mm thickness and 4 mm holes 6 mm from the edges.
- [onboarding_plate] other/low: Hole position in `measure --holes` is reported at z=0 (hole start/bottom) with no clear indication of which end; minor.
- [onboarding_plate] docs_unclear/low: The docs excerpt I read never described hole_pattern/hole signatures; I only learned hole_pattern(diameter, spacing=, count=) from `cad examples show plate_with_holes`. I did not read the full docs beyond the first ~150 lines.
- [onboarding_plate] other/low: Hole at position z=0 with depth 4 reported; fine, but no explicit 'through' indicator in measure --holes.
- [onboarding_plate] docs_unclear/low: hole_pattern is not described in `cad docs` output I read (head -150); I only learned its signature (diameter, spacing, count, name) from the bundled plate_with_holes example. Whether spacing is centre-to-centre and whether the pattern is centred was inferred and confirmed only via measure --holes.
- [onboarding_plate] other/low: I did not render the result; I relied on inspect/measure --holes numbers only.

## Suggestions

- [onboarding_plate] Put a minimal 'plate with 4 holes -> STL' recipe in `cad --help` or at the top of `cad docs`.
- [onboarding_plate] Say in the docs that hole_pattern is centred on the part origin.
- [onboarding_plate] Put a minimal 'plate with holes' snippet at the top of `cad --help` or in the output of `cad init`.
- [onboarding_plate] Have `cad init` print the exact commands for build, inspect, export and where the STL ends up.
- [onboarding_plate] Have `cad --help` or `cad init` point to `cad docs` and `cad examples` explicitly.
- [onboarding_plate] Add a minimal 'plate with 4 holes' snippet at the top of the docs Quick start.
- [onboarding_plate] Add a `cad export --format stl` note about watertightness / printability check output.
- [onboarding_plate] Put a minimal 'plate with holes -> STL' quickstart at the top of `cad --help` / docs.
- [onboarding_plate] Mention in `cad init` output that `cad examples` exists.
- [onboarding_plate] Add a printability check (min wall, flat bottom) hint after export.
- [onboarding_plate] Put a minimal 'plate with 4 holes' script in the top of `cad --help` or `cad docs`.
- [onboarding_plate] Document hole_pattern in the main API table.
- [onboarding_plate] Make `cad init` print a hint that it keeps an existing model.py.
