# Eval run heldout2-baseline

model `sonnet`, git `ea11430-dirty`, label `heldout2-baseline`

- attempts: 4, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 8, mean failed builds 0, mean turns 11
- cost: total $0.575 (mean $0.144); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| cable_clip | 1.0 | 1.0 | 11.5 | 2 (0) | 1 | 2 | 13.5 |  |
| nema17_mount | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8.5 |  |

## cad error codes seen


## Feedback issues

- [cable_clip] api_confusing/high: hole() with a 2D position starts at the part's bounding-box face. In this part the ring makes the bbox taller than the tab, so the countersink was cut at z=17.19 (in air) and the holes were plain 4 mm through holes. The build gave no warning, because the through hole still cut material. I only found it by looking at the top render and querying cone faces.
- [cable_clip] docs_unclear/medium: The docs say a 2D point starts the hole at the bbox face it enters, but they do not warn that this is the whole part's bbox, not the local surface under the hole. They also do not say what happens to a countersink that starts above the material.
- [cable_clip] other/low: The shell sandbox blocked redirects (cat > file), so I used the Write tool for files. This is an environment matter, not a tool problem.
- [cable_clip] api_confusing/medium: hole()/holes() with a 2D position start at the part's bbox top face. Here the ring makes the bbox top Z=17.19, so the 2D-position countersink silently landed in mid-air: no countersink was cut, no warning (the through hole still worked). I only noticed because the top render showed plain holes and a cone-face query returned 0. Fix was to pass 3D start points (x, y, 3).
- [nema17_mount] docs_unclear/low: Profile.slot's angle convention (angle=90 -> along Y) and that length is end-to-end are not stated in the docs; I assumed it and confirmed via the render and volume check.
- [nema17_mount] query_missing/low: find_holes()/inspect do not report slots (non-circular cuts), so slot position and size could only be checked visually or via volume.
- [nema17_mount] docs_unclear/low: cad.toml format is not documented in `cad docs`; `cad init` would create it but I wrote it by hand (guessed [project] name/entry keys) and it worked.
- [nema17_mount] docs_unclear/low: Profile.slot angle convention (angle=90 = along Y) and whether length is end-to-end are not stated in docs; I verified via render.
- [nema17_mount] api_missing/low: No dedicated cut-slot helper like hole(); slots need extrude(op='cut') with a manually chosen depth.

## Suggestions

- [cable_clip] Warn (e.g. COUNTERSINK_NO_EFFECT) when a countersink or counterbore produces no cone or cylinder face, or starts above the material.
- [cable_clip] Offer a face-relative hole start, e.g. at=(x, y) plus on_face='tab.top'.
- [cable_clip] Make find_holes report countersink or counterbore info, so asserts can check it.
- [cable_clip] Warn (e.g. COUNTERSINK_NO_EFFECT) when a countersink/counterbore start plane doesn't intersect material at the hole position.
- [cable_clip] Add a hole option to start at a named face (at_face='tab.top') or at the nearest surface below.
- [cable_clip] Render the countersink cone faces in a distinguishable way, or include a section view tip in docs.
- [nema17_mount] State the Profile.slot angle convention and that length is overall in the docs.
- [nema17_mount] Report slots in find_holes/inspect, or add a separate slot query.
- [nema17_mount] Add a hole-from-bottom counterbore example (direction='+z' starting at the bottom face).
- [nema17_mount] Document cad.toml keys and slot angle/length semantics.
- [nema17_mount] Add p.slot_cut(length, width, at, angle, depth=None).
