# S03 stress run

seed 1, 6 cases, 6 workers, 5.7 s; cad 0.1.0, OCP 8.0.1.1.0, macOS-26.5.1-arm64-arm-64bit

**Outcome classes:** pass 6

| category | pass |
|---|---|
| bracket | 1 |
| clearance_pair | 1 |
| small_holes | 1 |
| thin_shell | 1 |
| tiny_features | 1 |
| turned_groove | 1 |

| category | cases | median ms | p95 ms | max ms |
|---|---|---|---|---|
| bracket | 1 | 5162.9 | 5162.9 | 5162.9 |
| clearance_pair | 1 | 718.8 | 718.8 | 718.8 |
| small_holes | 1 | 2839.5 | 2839.5 | 2839.5 |
| thin_shell | 1 | 1102.5 | 1102.5 | 1102.5 |
| tiny_features | 1 | 1983.6 | 1983.6 | 1983.6 |
| turned_groove | 1 | 1518.4 | 1518.4 | 1518.4 |

## Analysis

```json
{
  "bracket": {
    "0.001": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "4.4e-16",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "3.1e-15",
      "tessellated": true
    },
    "0.01": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "4.4e-16",
      "area_rel_dev": "3.9e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "9.2e-15",
      "tessellated": true
    },
    "0.1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "6.5e-16",
      "area_rel_dev": "5.8e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "2.4e-15",
      "tessellated": true
    },
    "0.5": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "1.3e-15",
      "tessellated": true
    },
    "1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "2.6e-15",
      "tessellated": true
    },
    "10": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "6.5e-16",
      "area_rel_dev": "3.9e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "2.4e-15",
      "tessellated": true
    },
    "100": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.1e-15",
      "area_rel_dev": "3.9e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "2.8e-15",
      "tessellated": true
    },
    "1000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "4.1e-15",
      "area_rel_dev": "1.2e-15",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "8.7e-16",
      "tessellated": true
    },
    "10000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.7e-14",
      "area_rel_dev": "4.8e-15",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "1.3e-14",
      "tessellated": true
    }
  },
  "thin_shell": {
    "0.001": {
      "built": false,
      "valid": null,
      "error": "INVALID_SHAPE"
    },
    "0.01": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "2.9e-15",
      "area_rel_dev": "4.4e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "0.1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "2.7e-15",
      "area_rel_dev": "6.6e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "1.4e-16",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "0.5": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "10": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.7e-15",
      "area_rel_dev": "4.4e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "100": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.7e-15",
      "area_rel_dev": "4.4e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "1000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "7.0e-16",
      "area_rel_dev": "2.2e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "10000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.7e-15",
      "area_rel_dev": "4.4e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "thickness_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    }
  },
  "clearance_pair": {
    "0.001": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.1e-16",
      "area_rel_dev": "2.3e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "1.1e-14",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "0.01": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.1e-16",
      "area_rel_dev": "1.1e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "1.1e-14",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "0.1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "2.3e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "1.6e-14",
      "solids_match": true,
      "step_volume_rel_err": "2.3e-16",
      "tessellated": true
    },
    "0.5": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "0.0e+00",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "10": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "5.3e-15",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "100": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "4.5e-16",
      "area_rel_dev": "2.3e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "5.3e-15",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "1000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.1e-16",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "5.3e-15",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "10000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "4.5e-16",
      "area_rel_dev": "1.1e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "gap_rel_dev": "5.3e-15",
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    }
  },
  "small_holes": {
    "0.001": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.1e-14",
      "area_rel_dev": "1.9e-14",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "0.01": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "6.5e-16",
      "area_rel_dev": "4.3e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "0.1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.5e-15",
      "area_rel_dev": "1.1e-15",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "0.5": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "10": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.8e-15",
      "area_rel_dev": "8.6e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "100": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.6e-16",
      "area_rel_dev": "2.1e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "1000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.1e-15",
      "area_rel_dev": "1.5e-15",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    },
    "10000": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.3e-15",
      "area_rel_dev": "6.4e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "0.0e+00",
      "tessellated": true
    }
  },
  "turned_groove": {
    "0.001": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.7e-16",
      "area_rel_dev": "1.7e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "5.0e-16",
      "tessellated": true
    },
    "0.01": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "1.7e-16",
      "area_rel_dev": "3.5e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "3.3e-16",
      "tessellated": true
    },
    "0.1": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "3.3e-16",
      "area_rel_dev": "3.5e-16",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "6.7e-16",
      "tessellated": true
    },
    "0.5": {
      "built": true,
      "valid": true,
      "volume_rel_dev": "0.0e+00",
      "area_rel_dev": "0.0e+00",
      "bbox_abs_dev_n": "0.0e+00",
      "holes_match": true,
      "solids_match": true,
      "step_volume_rel_err": "1.7e-16",
      "tessellated": true
    },
    "1": {
      "built": true,

```
