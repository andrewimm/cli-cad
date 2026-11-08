# S01 stress run

seed 1, 1000 cases, 5 workers, 36.5 s; cad 0.1.0, OCP 8.0.1.1.0, macOS-26.5.1-arm64-arm-64bit

**Outcome classes:** defect 4, pass 996

| category | defect | pass |
|---|---|---|
| edge_touch | 0 | 110 |
| face_touch | 0 | 130 |
| full_overlap | 0 | 120 |
| nearly_coincident | 0 | 140 |
| nearly_tangent | 0 | 140 |
| partial_overlap | 4 | 216 |
| small_intersection | 0 | 140 |

**Findings by kind:**

- defect:union:failed_on_valid_input:INVALID_SHAPE: 4

| category | cases | median ms | p95 ms | max ms |
|---|---|---|---|---|
| edge_touch | 110 | 115.1 | 154.4 | 790.6 |
| face_touch | 130 | 120.9 | 150.3 | 855.1 |
| full_overlap | 120 | 138.4 | 181.2 | 907.6 |
| nearly_coincident | 140 | 161.1 | 212.2 | 794.7 |
| nearly_tangent | 140 | 112.3 | 197.1 | 816.2 |
| partial_overlap | 220 | 180.2 | 265.2 | 978.2 |
| small_intersection | 140 | 185.5 | 238.1 | 945.3 |

Defect reproductions: `failures/<id>/repro.py` (and `minimal_repro.py` where reduced) for 4 case(s), e.g. S01-1-0127, S01-1-0173, S01-1-0241, S01-1-0279
