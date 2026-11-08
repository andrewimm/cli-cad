# S05 stress run

seed 1, 200 cases, 1 workers, 29.5 s; cad 0.1.0, OCP 8.0.1.1.0, macOS-26.5.1-arm64-arm-64bit

**Outcome classes:** controlled 45, pass 155

| category | controlled | pass |
|---|---|---|
| disappearing_features | 3 | 17 |
| holes_near_edges | 1 | 19 |
| merging_features | 20 | 0 |
| oversized_fillets | 18 | 2 |
| tangent_features | 3 | 17 |
| thin_walls | 0 | 20 |
| valid | 0 | 80 |

**Findings by kind:**

- controlled:split_reported: 21

## Analysis

```json
{
  "outcomes_by_category": {
    "valid": {
      "ok": 80
    },
    "tangent_features": {
      "ok": 18,
      "failed": 2
    },
    "holes_near_edges": {
      "ok": 20
    },
    "disappearing_features": {
      "ok": 17,
      "failed": 3
    },
    "merging_features": {
      "ok": 19,
      "failed": 1
    },
    "thin_walls": {
      "ok": 20
    },
    "oversized_fillets": {
      "failed": 18,
      "ok": 2
    }
  },
  "error_codes": {
    "oversized_fillets:FILLET_FAILED": 18,
    "disappearing_features:FILLET_FAILED": 3,
    "tangent_features:FILLET_FAILED": 2,
    "merging_features:REFERENCE_LOST": 1
  },
  "set_and_build_ms": {
    "median": 94.3,
    "p95": 219.1,
    "max": 376.7
  }
}
```
