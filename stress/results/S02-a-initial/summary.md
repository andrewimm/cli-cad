# S02 stress run

seed 1, 72 cases, 5 workers, 44.4 s; cad 0.1.0, OCP 8.0.1.1.0, macOS-26.5.1-arm64-arm-64bit

**Outcome classes:** controlled 66, defect 2, pass 4

| category | controlled | defect | pass |
|---|---|---|---|
| box/all | 2 | 0 | 0 |
| box/convex | 2 | 0 | 0 |
| box/random_k | 3 | 0 | 0 |
| box/single | 0 | 0 | 1 |
| box/top | 2 | 0 | 0 |
| box/vertical | 2 | 0 | 0 |
| bracket/all | 2 | 0 | 0 |
| bracket/concave | 2 | 0 | 0 |
| bracket/convex | 2 | 0 | 0 |
| bracket/random_k | 1 | 0 | 0 |
| bracket/single | 0 | 0 | 1 |
| bracket/top | 2 | 0 | 0 |
| bracket/vertical | 2 | 0 | 0 |
| convex_profile/all | 2 | 0 | 0 |
| convex_profile/convex | 2 | 0 | 0 |
| convex_profile/random_k | 3 | 0 | 0 |
| convex_profile/single | 1 | 0 | 0 |
| convex_profile/top | 2 | 0 | 0 |
| convex_profile/vertical | 2 | 0 | 0 |
| plate_holes/all | 2 | 0 | 0 |
| plate_holes/convex | 2 | 0 | 0 |
| plate_holes/random_k | 2 | 0 | 1 |
| plate_holes/single | 1 | 0 | 0 |
| plate_holes/top | 2 | 0 | 0 |
| plate_holes/vertical | 2 | 0 | 0 |
| pocket_block/all | 2 | 0 | 0 |
| pocket_block/concave | 2 | 0 | 0 |
| pocket_block/convex | 2 | 0 | 0 |
| pocket_block/random_k | 1 | 0 | 0 |
| pocket_block/single | 1 | 0 | 0 |
| pocket_block/top | 2 | 0 | 0 |
| pocket_block/vertical | 2 | 0 | 0 |
| star_profile/all | 2 | 0 | 0 |
| star_profile/concave | 1 | 0 | 1 |
| star_profile/convex | 2 | 0 | 0 |
| star_profile/random_k | 1 | 0 | 0 |
| star_profile/single | 1 | 0 | 0 |
| star_profile/top | 2 | 0 | 0 |
| star_profile/vertical | 0 | 2 | 0 |

**Findings by kind:**

- defect:solid_count_changed: 2
- defect:stale_selection_accepted: 2
- pass:succeeded_above_rmax: 2

| category | cases | median ms | p95 ms | max ms |
|---|---|---|---|---|
| box/all | 2 | 2656.3 | 2913.9 | 2913.9 |
| box/convex | 2 | 2497.8 | 2735.6 | 2735.6 |
| box/random_k | 3 | 1536.3 | 1843.4 | 1843.4 |
| box/single | 1 | 1395.3 | 1395.3 | 1395.3 |
| box/top | 2 | 1662.0 | 1733.6 | 1733.6 |
| box/vertical | 2 | 1646.3 | 1702.1 | 1702.1 |
| bracket/all | 2 | 3293.8 | 4380.7 | 4380.7 |
| bracket/concave | 2 | 2338.0 | 2751.2 | 2751.2 |
| bracket/convex | 2 | 3011.0 | 3433.5 | 3433.5 |
| bracket/random_k | 1 | 1603.6 | 1603.6 | 1603.6 |
| bracket/single | 1 | 1074.0 | 1074.0 | 1074.0 |
| bracket/top | 2 | 1520.6 | 1975.3 | 1975.3 |
| bracket/vertical | 2 | 2241.6 | 2243.7 | 2243.7 |
| convex_profile/all | 2 | 3623.6 | 4177.8 | 4177.8 |
| convex_profile/convex | 2 | 3328.6 | 3774.9 | 3774.9 |
| convex_profile/random_k | 3 | 1519.7 | 1584.4 | 1584.4 |
| convex_profile/single | 1 | 1107.5 | 1107.5 | 1107.5 |
| convex_profile/top | 2 | 1524.8 | 1809.2 | 1809.2 |
| convex_profile/vertical | 2 | 2414.7 | 2552.8 | 2552.8 |
| plate_holes/all | 2 | 2668.8 | 3567.6 | 3567.6 |
| plate_holes/convex | 2 | 2769.5 | 3036.0 | 3036.0 |
| plate_holes/random_k | 3 | 1743.3 | 1884.2 | 1884.2 |
| plate_holes/single | 1 | 1332.6 | 1332.6 | 1332.6 |
| plate_holes/top | 2 | 1688.8 | 1690.4 | 1690.4 |
| plate_holes/vertical | 2 | 1328.2 | 1502.2 | 1502.2 |
| pocket_block/all | 2 | 3111.5 | 3309.2 | 3309.2 |
| pocket_block/concave | 2 | 1455.1 | 1623.2 | 1623.2 |
| pocket_block/convex | 2 | 2172.5 | 2581.1 | 2581.1 |
| pocket_block/random_k | 1 | 1272.1 | 1272.1 | 1272.1 |
| pocket_block/single | 1 | 903.5 | 903.5 | 903.5 |
| pocket_block/top | 2 | 1561.7 | 1716.2 | 1716.2 |
| pocket_block/vertical | 2 | 1881.5 | 1957.3 | 1957.3 |
| star_profile/all | 2 | 10849.2 | 11636.6 | 11636.6 |
| star_profile/concave | 2 | 2743.3 | 3167.6 | 3167.6 |
| star_profile/convex | 2 | 8030.6 | 8901.1 | 8901.1 |
| star_profile/random_k | 1 | 2466.0 | 2466.0 | 2466.0 |
| star_profile/single | 1 | 2401.2 | 2401.2 | 2401.2 |
| star_profile/top | 2 | 5179.6 | 5562.1 | 5562.1 |
| star_profile/vertical | 2 | 5701.8 | 5848.1 | 5848.1 |

## Analysis

```json
{
  "fillet_attempts": 504,
  "selections_with_no_feasible_radius": 0,
  "by_radius": {
    "0.1 mm": {
      "attempts": 72,
      "succeeded": 72,
      "valid": 72,
      "pass": 72
    },
    "0.5 mm": {
      "attempts": 72,
      "succeeded": 72,
      "valid": 72,
      "pass": 72
    },
    "0.9 rmax": {
      "attempts": 72,
      "succeeded": 72,
      "valid": 72,
      "pass": 70,
      "defect": 2
    },
    "1 mm": {
      "attempts": 72,
      "succeeded": 71,
      "valid": 71,
      "pass": 71,
      "controlled": 1
    },
    "1.1 rmax": {
      "attempts": 72,
      "succeeded": 4,
      "valid": 4,
      "controlled": 68,
      "pass": 4
    },
    "2 mm": {
      "attempts": 72,
      "succeeded": 59,
      "valid": 59,
      "pass": 59,
      "controlled": 13
    },
    "5 mm": {
      "attempts": 72,
      "succeeded": 36,
      "valid": 36,
      "controlled": 36,
      "pass": 36
    }
  },
  "error_quality_score_distribution(0-4)": {
    "4": 118
  },
  "attempt_ms": {
    "median": 104.41,
    "p95": 333.91,
    "max": 769.02
  }
}
```

Defect reproductions: `failures/<id>/repro.py` (and `minimal_repro.py` where reduced) for 2 case(s), e.g. S02-1-0009, S02-1-0051
