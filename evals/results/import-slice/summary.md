# Eval run import-slice

model `sonnet`, git `ca7ded0`, label `import-slice`

- attempts: 3, **pass rate 1.0**, mean check score 1.0
- self-reported success 1.0 (over-claimed: 0)
- mean cad calls 16.667, mean failed builds 0, mean turns 14.667
- cost: total $0.596 (mean $0.199); implementation peeks: 0

| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |
|---|---|---|---|---|---|---|---|---|
| vendor_servo_mount | 1.0 | 1.0 | 16.667 | 2 (0) | 1 | 4 | 14.667 |  |

## Onboarding timeline (seconds from agent start)

| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |
|---|---|---|---|---|---|---|---|---|---|---|
| vendor_servo_mount/a1 | True | 3.0 | 9.5 | None | 40.0 | 19 | 9 | 5 | 2 {'INVALID_ARGUMENT': 2} | False |
| vendor_servo_mount/a2 | True | 2.8 | 8.7 | None | 39.5 | 16 | 8 | 4 | 1 {'NOT_FOUND': 1} | False |
| vendor_servo_mount/a3 | True | 3.2 | 8.8 | None | 42.0 | 15 | 9 | 3 | 0  | False |

## cad error codes seen

- INVALID_ARGUMENT: 2
- NOT_FOUND: 1

## Feedback issues

- [vendor_servo_mount] query_missing/medium: No direct way to get the bounding box / outline of a face or of the ear region of an imported part; I inferred ear x-extents and body width from face areas and centroids (e.g. 278.16 mm2 = 22.8 x 12.2). edges().at_z does not exist.
- [vendor_servo_mount] api_missing/low: No way to section the imported servo at a Z height to get its footprint below the ears.
- [vendor_servo_mount] docs_unclear/medium: No direct way to get the ears' outline or body cross-section; I had to infer ear extents from face areas/centroids (cad query facing) and bbox. A 'cad measure servo --section z=-1' or per-z outline would help.
- [vendor_servo_mount] query_missing/low: cad clearance output for a reference part lists ~20 face lines, mostly 'open'; noisy for the simple check of 'is the clearance 0.5'.
- [vendor_servo_mount] query_missing/medium: No direct way to get the case-body footprint below the ears of an imported solid; I inferred the body X range (-17.3..5.5) from pixels in a section render plus face-area arithmetic.
- [vendor_servo_mount] docs_unclear/low: cad clearance output for a touching pair lists ~20 per-face lines, mostly 'gap open'; hard to scan.

## Suggestions

- [vendor_servo_mount] Add face/selection bbox output to cad query.
- [vendor_servo_mount] Add a z-slice outline query.
- [vendor_servo_mount] Add a way to query the XY outline/bbox of a slab of a part (z range), e.g. cad measure servo --bbox --zrange -2.5:0.
- [vendor_servo_mount] Filter 'gap open' lines in cad clearance by default.
- [vendor_servo_mount] cad slice names the output after the directory (workspace.gcode.3mf) rather than the part.
- [vendor_servo_mount] Cross-section bbox/outline at a given Z
- [vendor_servo_mount] Face bounding boxes in cad query output
- [vendor_servo_mount] Compact clearance summary (only faces with finite gap)
