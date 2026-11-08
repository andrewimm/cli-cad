# S01 stress run

seed 1, 1000 cases, 8 workers, 21.7 s; cad 0.1.0, OCP 8.0.1.1.0, macOS-26.5.1-arm64-arm-64bit

**Outcome classes:** defect 34, pass 966

| category | defect | pass |
|---|---|---|
| edge_touch | 0 | 110 |
| face_touch | 0 | 130 |
| full_overlap | 0 | 120 |
| nearly_coincident | 27 | 113 |
| nearly_tangent | 0 | 140 |
| partial_overlap | 7 | 213 |
| small_intersection | 0 | 140 |

**Findings by kind:**

- defect:intersect:nonempty_for_touching: 27
- defect:intersect:failed_on_valid_input:NO_BODY: 4
- defect:union:unexpected_solid_count: 4
- defect:identity:union+intersect: 2
- defect:identity:cut: 2
- defect:cut:failed_on_valid_input:NO_BODY: 1

| category | cases | median ms | p95 ms | max ms |
|---|---|---|---|---|
| edge_touch | 110 | 85.7 | 112.4 | 663.9 |
| face_touch | 130 | 93.3 | 193.2 | 726.1 |
| full_overlap | 120 | 104.0 | 140.3 | 804.7 |
| nearly_coincident | 140 | 134.9 | 174.3 | 750.0 |
| nearly_tangent | 140 | 81.8 | 159.6 | 702.7 |
| partial_overlap | 220 | 128.9 | 196.0 | 853.0 |
| small_intersection | 140 | 148.4 | 169.7 | 769.0 |

Defect reproductions: `failures/<id>/repro.py` (and `minimal_repro.py` where reduced) for 34 case(s), e.g. S01-1-0211, S01-1-0222, S01-1-0231, S01-1-0251, S01-1-0272, S01-1-0282, S01-1-0337, S01-1-0866
