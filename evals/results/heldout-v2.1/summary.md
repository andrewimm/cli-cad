# Eval run heldout-v2.1

model `sonnet`, git `7c2b98e`, label `heldout-v2.1`

- attempts: 6, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 6.833, mean failed builds 0, mean turns 9.833
- cost: total $0.834 (mean $0.139); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| hex_standoff | 1.0 | 1.0 | 5.5 | 1 (0) | 1 | 1 | 8 |  |
| hinge_leaf | 1.0 | 1.0 | 10.5 | 2 (0) | 1.5 | 1.5 | 13.5 |  |
| pipe_flange | 1.0 | 1.0 | 4.5 | 1 (0) | 1 | 1 | 8 |  |

## cad error codes seen


## Feedback issues

- [hex_standoff] docs_unclear/low: Profile.regular_polygon's 'diameter' is not stated to be circumscribed (vertex-to-vertex) vs across-flats, nor what angle=0 orientation is. I had to build and check the bbox (vertices ended up on X, flats at Y=+-4, which is what I wanted).
- [hex_standoff] api_missing/low: No across-flats option for regular_polygon; I had to compute d/cos(30deg) by hand.
- [hex_standoff] docs_unclear/medium: Profile.regular_polygon's `diameter` is not documented as circumscribed vs. across-flats, and `angle=0` orientation (vertex on +U) is not stated. I computed 8/cos30 and confirmed via bbox (Y=+-4).
- [hinge_leaf] error_unhelpful/high: With a 2D `at`, holes() starts at the part's bbox top (Z=6, the knuckle top), not the plate top (Z=2). The 3.5 mm through-hole still cut the plate, but the countersink was silently lost because it sat in air. There was no warning (no HOLE_MISSED / CUT_NO_EFFECT), and cad inspect still showed 3 valid holes. I only found it by querying for cone faces, since the render looked plausible.
- [hinge_leaf] docs_unclear/medium: The docs say a 2D `at` starts on the bbox face it enters. They don't warn that this breaks for parts with a taller feature elsewhere, such as a knuckle or boss. The countersink-specific consequence isn't mentioned.
- [hinge_leaf] render_missing/low: The iso render at default size can't distinguish countersunk from plain holes. A section view or close-up through a hole would have shown it. I did not try `--section`.
- [hinge_leaf] api_confusing/medium: With a 2D `at`, hole()/holes() start at the top of the whole part's bbox (Z=6, the knuckle top), not the plate top (Z=2). The countersink was silently placed in mid-air and the holes became plain straight holes (first build, inspect showed depth 2.0 and no warning). Only a section render revealed it. Fix was a 3D start point (x, y, 2).
- [hinge_leaf] docs_unclear/low: Docs say `at` 2D starts 'on the bbox face it enters' but do not warn that this goes wrong when a taller feature (knuckle) is added before the holes.
- [hinge_leaf] render_missing/low: `--section x=-12` rendered a front view that showed the exterior of the retained half, not the cut face, so it was useless; a section plane parallel to the view direction is not obvious. y=-3 front worked well.
- [pipe_flange] docs_unclear/low: Not stated whether hole(at=(0,0)) with no depth on a stepped part (disc+hub) drills through the whole part; it did (bbox-top start, through all), but I had to verify via inspect.
- [pipe_flange] other/low: cad init . names the project after the directory ('workspace'), not the part; harmless.

## Suggestions

- [hex_standoff] Document regular_polygon diameter semantics and angle=0 orientation; add an across_flats= option.
- [hex_standoff] Add a chamfer/fillet example for 'edges of the end faces excluding the hole' in the docs.
- [hex_standoff] Document regular_polygon diameter semantics (circumscribed) and angle=0 orientation; consider an across_flats= option.
- [hex_standoff] Show a hex-prism example in the docs.
- [hinge_leaf] Warn (e.g. COUNTERSINK_NO_EFFECT) when a countersink/counterbore does not intersect the material, or when depth-limited features leave no cut.
- [hinge_leaf] Let holes accept `start='face:<ref>'` or a face reference such as p.faces('plate.top') to define where the hole starts.
- [hinge_leaf] Report countersink and counterbore details in find_holes()/inspect: top diameter, angle, and depth.
- [hinge_leaf] Document the 2D-`at` pitfall next to the countersink example, and show the 3D-start form for plates with taller features.
- [hinge_leaf] Warn (e.g. HOLE_START_OFF_SURFACE) when a hole's start point is not on material, especially when a countersink/counterbore is requested and ends up outside the solid.
- [hinge_leaf] Allow holes to take a face reference as the start surface, e.g. at=(x, y) on p.faces('plate.top').
- [hinge_leaf] Report countersink/counterbore parameters in the `cad inspect` hole listing.
- [pipe_flange] Add a revolve-based flange example to docs
- [pipe_flange] Mention in the hole docs that depth=None goes through stepped parts
- [pipe_flange] Add a pipe-flange/revolve-style example to `cad examples list` for round parts with a bolt circle.
