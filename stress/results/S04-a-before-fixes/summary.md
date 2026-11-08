# S04 stress run

seed 1, 16 cases, 4 workers, 3036.6 s; cad 0.1.0, OCP 8.0.1.1.0, macOS-26.5.1-arm64-arm-64bit

**Outcome classes:** limitation 5, pass 11

| category | limitation | pass |
|---|---|---|
| bosses | 2 | 2 |
| holes_individual | 1 | 3 |
| holes_pattern | 0 | 4 |
| ribs | 2 | 2 |

**Findings by kind:**

- limitation:timeout>1500s: 5

| category | cases | median ms | p95 ms | max ms |
|---|---|---|---|---|
| bosses | 4 | 780821.6 | 1500402.8 | 1500402.8 |
| holes_individual | 4 | 482349.2 | 1500271.3 | 1500271.3 |
| holes_pattern | 4 | 5579.0 | 21403.3 | 21403.3 |
| ribs | 4 | 794077.1 | 1500248.8 | 1500248.8 |

## Analysis

```json
{
  "rows": {
    "holes_pattern@10": {
      "construct_s": 0.13,
      "boolean_s": 0.01,
      "measure_s": 0.01,
      "references_s": 0.08,
      "tools_s": 0.0,
      "validate_s": 0.01,
      "tessellate_s": 0.02,
      "render_s": 0.32,
      "step_s": 0.03,
      "peak_rss_mb": 503.9,
      "faces": 16,
      "triangles": 2092,
      "found": 10,
      "volume_rel_err": "8.8e-16"
    },
    "holes_individual@10": {
      "construct_s": 0.56,
      "boolean_s": 0.03,
      "measure_s": 0.05,
      "references_s": 0.35,
      "tools_s": 0.0,
      "validate_s": 0.01,
      "tessellate_s": 0.01,
      "render_s": 0.28,
      "step_s": 0.01,
      "peak_rss_mb": 475.3,
      "faces": 16,
      "triangles": 2092,
      "found": 10,
      "volume_rel_err": "8.8e-16"
    },
    "bosses@10": {
      "construct_s": 0.87,
      "boolean_s": 0.02,
      "measure_s": 0.05,
      "references_s": 0.66,
      "simplify_s": 0.01,
      "validate_s": 0.01,
      "tessellate_s": 0.01,
      "render_s": 0.32,
      "step_s": 0.01,
      "peak_rss_mb": 573.0,
      "faces": 26,
      "triangles": 2052,
      "found": 10,
      "volume_rel_err": "2.8e-16"
    },
    "ribs@10": {
      "construct_s": 1.15,
      "boolean_s": 0.03,
      "measure_s": 0.03,
      "references_s": 0.97,
      "simplify_s": 0.01,
      "validate_s": 0.02,
      "tessellate_s": 0.01,
      "render_s": 0.54,
      "step_s": 0.01,
      "peak_rss_mb": 531.4,
      "faces": 56,
      "triangles": 172,
      "found": 10,
      "volume_rel_err": "8.0e-16"
    },
    "holes_pattern@100": {
      "construct_s": 0.84,
      "boolean_s": 0.06,
      "measure_s": 0.09,
      "references_s": 0.58,
      "tools_s": 0.0,
      "validate_s": 0.01,
      "tessellate_s": 0.19,
      "render_s": 0.38,
      "step_s": 0.02,
      "peak_rss_mb": 613.8,
      "faces": 106,
      "triangles": 20812,
      "found": 100,
      "volume_rel_err": "1.1e-15"
    },
    "holes_individual@100": {
      "construct_s": 31.22,
      "boolean_s": 0.63,
      "measure_s": 4.54,
      "references_s": 16.34,
      "tools_s": 0.01,
      "validate_s": 0.62,
      "tessellate_s": 0.19,
      "render_s": 0.38,
      "step_s": 0.03,
      "peak_rss_mb": 538.9,
      "faces": 106,
      "triangles": 20812,
      "found": 100,
      "volume_rel_err": "1.1e-15"
    },
    "bosses@100": {
      "construct_s": 60.06,
      "boolean_s": 0.44,
      "measure_s": 4.53,
      "references_s": 44.97,
      "simplify_s": 0.11,
      "validate_s": 0.52,
      "tessellate_s": 0.18,
      "render_s": 0.45,
      "step_s": 0.02,
      "peak_rss_mb": 536.1,
      "faces": 206,
      "triangles": 20412,
      "found": 100,
      "volume_rel_err": "8.3e-15"
    },
    "ribs@100": {
      "construct_s": 86.8,
      "boolean_s": 1.06,
      "measure_s": 2.63,
      "references_s": 73.92,
      "simplify_s": 0.4,
      "validate_s": 1.75,
      "tessellate_s": 0.06,
      "render_s": 0.32,
      "step_s": 0.07,
      "peak_rss_mb": 446.3,
      "faces": 506,
      "triangles": 1612,
      "found": 100,
      "volume_rel_err": "7.4e-15"
    },
    "holes_pattern@500": {
      "construct_s": 4.24,
      "boolean_s": 0.37,
      "measure_s": 0.44,
      "references_s": 2.81,
      "tools_s": 0.01,
      "validate_s": 0.16,
      "tessellate_s": 2.75,
      "render_s": 0.6,
      "step_s": 0.19,
      "peak_rss_mb": 1064.0,
      "faces": 506,
      "triangles": 104012,
      "found": 500,
      "volume_rel_err": "1.0e-14"
    },
    "holes_individual@500": {
      "construct_s": 927.13,
      "boolean_s": 23.71,
      "measure_s": 124.55,
      "references_s": 468.93,
      "tools_s": 0.11,
      "validate_s": 45.61,
      "tessellate_s": 2.97,
      "render_s": 0.62,
      "step_s": 0.23,
      "peak_rss_mb": 1011.3,
      "faces": 506,
      "triangles": 104012,
      "found": 500,
      "volume_rel_err": "1.0e-14"
    },
    "bosses@500": {
      "status": "timeout",
      "wall_s": 1500.4
    },
    "ribs@500": {
      "status": "timeout",
      "wall_s": 1500.1
    },
    "holes_pattern@1000": {
      "construct_s": 8.86,
      "boolean_s": 0.9,
      "measure_s": 0.87,
      "references_s": 5.63,
      "tools_s": 0.02,
      "validate_s": 0.54,
      "tessellate_s": 8.56,
      "render_s": 0.79,
      "step_s": 0.59,
      "peak_rss_mb": 2584.4,
      "faces": 1006,
      "triangles": 208012,
      "found": 1000,
      "volume_rel_err": "8.6e-15"
    },
    "holes_individual@1000": {
      "status": "timeout",
      "wall_s": 1500.3
    },
    "bosses@1000": {
      "status": "timeout",
      "wall_s": 1500.2
    },
    "ribs@1000": {
      "status": "timeout",
      "wall_s": 1500.2
    }
  },
  "construct_time_growth_exponent_last_step": {
    "holes_pattern": 1.06,
    "holes_individual": 2.11,
    "bosses": 1.84,
    "ribs": 1.88
  }
}
```
