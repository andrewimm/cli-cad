# Eval run text-nameplate

model `sonnet`, git `9d32319`, label `text-nameplate`

- attempts: 3, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 8.333, mean failed builds 0, mean turns 8.333
- cost: total $0.384 (mean $0.128); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| engraved_nameplate | 1.0 | 1.0 | 8.333 | 1 (0) | 1 | 3.333 | 8.333 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| engraved_nameplate/a1 | True | 3.7 | 12.1 | None | 25.7 | 8 | 4 | 3 | 0  | False |
| engraved_nameplate/a2 | True | 3.5 | 11.0 | None | 24.6 | 9 | 5 | 4 | 0  | False |
| engraved_nameplate/a3 | True | 4.0 | 11.4 | None | 24.1 | 8 | 4 | 3 | 0  | False |

## cad error codes seen


## Feedback issues

- [engraved_nameplate] docs_unclear/low: Docs do not say whether `at=` positions the text's cap-height box or the baseline by default; I passed align=('center','center') to be safe and did not verify the exact vertical centring numerically.
- [engraved_nameplate] query_missing/low: No direct query for text bounding box / extents of engraved or embossed text, so centring (0,4) and (0,-8) was only checked visually.
- [engraved_nameplate] docs_unclear/low: The docs example for engrave/emboss does not show that `at` is the text anchor, so centring on (x, y) requires align=('center','center'). I passed it explicitly. I did not verify whether the default is already centred.

## Suggestions

- [engraved_nameplate] Add a query for the bbox of faces created by a text feature (e.g. emboss1.end).
- [engraved_nameplate] State the default vertical alignment of text in the docs.
- [engraved_nameplate] State the default `align` for text in `cad docs text`.
- [engraved_nameplate] Add a `cad measure --text` or query that reports the text bounding box and centre, so centring can be checked numerically.
- [engraved_nameplate] Add a query/measure to report text extents (bbox of engraved/emboss features) so centring and cap height can be verified numerically rather than only by render.
- [engraved_nameplate] Show the align=('center','center') default behaviour explicitly in the docs example, since centring on `at` depends on it.
