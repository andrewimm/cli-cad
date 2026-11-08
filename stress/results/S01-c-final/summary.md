# S01 stress run

seed 1, 1000 cases, 6 workers, 9.1 s; cad 0.1.0, OCP 8.0.1.1.0, macOS-26.5.1-arm64-arm-64bit

**Outcome classes:** pass 1000

| category | pass |
|---|---|
| edge_touch | 110 |
| face_touch | 130 |
| full_overlap | 120 |
| nearly_coincident | 140 |
| nearly_tangent | 140 |
| partial_overlap | 220 |
| small_intersection | 140 |

| category | cases | median ms | p95 ms | max ms |
|---|---|---|---|---|
| edge_touch | 110 | 9.3 | 11.6 | 583.1 |
| face_touch | 130 | 10.6 | 13.6 | 570.4 |
| full_overlap | 120 | 10.0 | 14.1 | 594.8 |
| nearly_coincident | 140 | 11.4 | 16.4 | 585.1 |
| nearly_tangent | 140 | 10.0 | 19.8 | 578.5 |
| partial_overlap | 220 | 17.6 | 62.2 | 616.6 |
| small_intersection | 140 | 16.5 | 19.8 | 597.9 |
