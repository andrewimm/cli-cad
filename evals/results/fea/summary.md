# Eval run 20261108-091008-fea

model `sonnet`, git `bf65f1a`, label `fea`

- attempts: 3, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 30, mean failed builds 1.333, mean turns 20.667
- cost: total $0.836 (mean $0.279); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| strengthen_arm | 1.0 | 1.0 | 30 | 10 (1.333) | 0 | 3.333 | 20.667 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| strengthen_arm/a1 | True | 4.7 | 8.5 | None | 127.2 | 32 | 14 | 4 | 9 {'VALIDATION_FAILED': 6, 'INVALID_ARGUMENT': 1, 'FILLET_FAILED': 1, 'EMPTY_SELECTION': 1} | False |
| strengthen_arm/a2 | True | 5.0 | 15.7 | None | 142.8 | 28 | 11 | 3 | 6 {'VALIDATION_FAILED': 5, 'FILLET_FAILED': 1} | False |
| strengthen_arm/a3 | True | 9.6 | 27.0 | None | 274.0 | 30 | 16 | 3 | 7 {'VALIDATION_FAILED': 6, 'FILLET_FAILED': 1} | False |

## cad error codes seen

- VALIDATION_FAILED: 17
- FILLET_FAILED: 3
- INVALID_ARGUMENT: 1
- EMPTY_SELECTION: 1

## Feedback issues

- [strengthen_arm] other/medium: cad fea exits 4 / reports BELOW TARGET for 'payload' (plain SF 1.25) even though the away-from-supports SF is 3.6; the peak sits on the horn screw-hole walls (idealised clamp). The task says to judge by the away-from-supports number, but the headline verdict and exit code still use the plain one, so a passing design looks failing.
- [strengthen_arm] api_confusing/low: A tapered beam joined to hub/tip cylinders by a polygon leaves nearly tangent concave kinks; fillet of these failed with a generic FILLET_FAILED (even for radius 6 with hint 'below ~4.5 mm'). I built the beam with exact tangent points to avoid inside corners instead.
- [strengthen_arm] api_confusing/medium: A rectangular beam unioned with hub/tip circles of equal width gives near-tangent concave vertical edges and a tangent junction at the tip; fillet of those failed with FILLET_FAILED even at 3 mm. I switched to a tangent-line hull outline (computed by hand) which has no concave corners at all.
- [strengthen_arm] docs_unclear/medium: 'cad build' exits 4 (validation failed) when the plain safety factor is below target, even though the task says to judge by the away-from-supports value. Final design: pushrod plain SF 3.2, payload plain SF 1.85 (at the clamped screw-hole edge) but away-from-supports SF 4.8.
- [strengthen_arm] error_unhelpful/medium: Filleting all concave edges at radius 3 with a beam wider than the 14 mm tip failed (FILLET_FAILED). The failing edges were listed by coordinates but the cause was not explained, and the 'try a radius below ~1 mm' hint was misleading. After the failed build, `cad fea` silently analysed the previous revision.
- [strengthen_arm] docs_unclear/medium: Pass/fail semantics: at --quality fine the plain payload safety factor at the fixed horn holes is 1.6 while the away-from-supports value is ~3. The CLI exits 4 (VALIDATION_FAILED) on the plain value even though the task rule says to judge away from supports. Results also shift 5-10% between draft/normal/fine near the margin.
- [strengthen_arm] api_missing/low: No tapered / variable-width beam helper; a mass-efficient design (wide at the hub, narrow at the tip) needs profile or loft work.

## Suggestions

- [strengthen_arm] Let Study take an option (or report a second verdict line) so 'ok' is judged on away_from_supports_and_sharp_edges when the peak is flagged PEAK_AT_SUPPORT.
- [strengthen_arm] Provide a Profile helper for the tangent hull of two circles (slot with different end diameters / 'tapered slot').
- [strengthen_arm] Report mass in cad fea / sweep output alongside SF (sweep does, fea does not).
- [strengthen_arm] A Profile helper for the tangent hull of two circles (slot/taper) would avoid hand-computed tangent points.
- [strengthen_arm] Report a per-study pass/fail that uses the away-from-supports value explicitly so build validation matches the stated criterion.
- [strengthen_arm] cad inspect could list concave (sharp inside) edges so the no-sharp-corner requirement can be verified directly.
- [strengthen_arm] Let `cad fea` use the away-from-supports safety factor for ok/exit code when PEAK_AT_SUPPORT applies, or offer a flag for it.
- [strengthen_arm] When a build fails, make `cad fea` refuse to run or state loudly which revision it analyses.
- [strengthen_arm] Let `cad sweep` sweep two parameters (or fillet radius) and report the lightest passing combination under a mass limit.
- [strengthen_arm] Explain FILLET_FAILED causes using the geometry (e.g. edge ends on a tangent or short edge).
