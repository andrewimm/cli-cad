"""JSON shapes (informal JSON Schema) of the CLI envelope and key results."""

_ERROR = {
    "type": "object",
    "required": ["code", "message"],
    "properties": {
        "code": {"type": "string", "description": "stable machine-readable code, e.g. FILLET_FAILED"},
        "message": {"type": "string"},
        "hint": {"type": "string", "description": "what to change"},
        "feature": {"type": "string", "description": "feature id that failed"},
        "details": {"type": "object", "description": "location (file/line), candidates, failing edges..."},
    },
}

_WARNING = {"type": "object", "properties": {"code": {"type": "string"}, "message": {"type": "string"},
                                              "feature": {"type": "string"}, "part": {"type": "string"}}}

SCHEMAS = {
    "envelope": {
        "description": "Every command run with --json prints one object of this shape on stdout.",
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "command": {"type": "string"},
            "result": {"type": "object", "description": "command-specific; see the other schemas"},
            "warnings": {"type": "array", "items": _WARNING},
            "error": _ERROR,
            "exit_code": {"type": "integer"},
            "duration_ms": {"type": "number"},
        },
    },
    "error": _ERROR,
    "build": {
        "type": "object",
        "properties": {
            "revision": {"type": "integer"},
            "cached": {"type": "boolean", "description": "true if an identical revision (same sources+params) was reused"},
            "parts": {"type": "object", "additionalProperties": {
                "type": "object", "properties": {"valid": {"type": "boolean"}, "solids": {"type": "integer"},
                                                 "volume": {"type": "number"}, "faces": {"type": "integer"},
                                                 "holes": {"type": "integer"}, "bbox_size": {"type": "array"}}}},
            "parameters": {"type": "object"},
            "warnings": {"type": "array", "items": _WARNING},
            "stdout": {"type": "string", "description": "what the script printed"},
        },
    },
    "inspect": {
        "type": "object",
        "properties": {
            "revision": {"type": "integer"},
            "parameters": {"type": "object"},
            "parts": {"type": "object", "additionalProperties": {
                "type": "object",
                "properties": {
                    "valid": {"type": "boolean"}, "solids": {"type": "integer"}, "volume": {"type": "number"},
                    "area": {"type": "number"}, "center_of_mass": {"type": "array"},
                    "bbox": {"type": "object", "properties": {"min": {}, "max": {}, "size": {}, "center": {}}},
                    "hole_list": {"type": "array", "items": {"type": "object", "properties": {
                        "diameter": {}, "axis": {}, "position": {"description": "centre of the hole end with the lowest axial coordinate"},
                        "depth": {}, "names": {}}}},
                    "feature_list": {"type": "array"}, "references": {"type": "object"}, "feature_graph": {"type": "array"},
                    "warnings": {"type": "array"},
                }}},
        },
    },
    "render": {
        "type": "object",
        "properties": {
            "revision": {"type": "integer"},
            "out_dir": {"type": "string"},
            "images": {"type": "array", "items": {"type": "object", "properties": {
                "view": {}, "path": {}, "metadata": {"description": "path of the JSON sidecar with camera & framing"},
                "cached": {}, "mm_per_pixel": {}, "screen_axes": {}}}},
            "sheet": {"type": ["string", "null"], "description": "contact sheet with all views in one PNG"},
        },
    },
    "render_metadata": {
        "description": "Sidecar <image>.json written next to every PNG",
        "type": "object",
        "properties": {
            "camera": {"properties": {"direction_to_camera": {}, "view_direction": {}, "screen_up": {}, "screen_right": {},
                                      "projection": {"const": "orthographic"}}},
            "framing": {"properties": {"mm_per_pixel": {}, "view_center_world": {}, "visible_extent_mm": {}, "pixel_to_world": {}}},
            "model": {"properties": {"name": {}, "parts": {}, "bbox": {}, "revision": {}}},
        },
    },
    "query": {
        "type": "object",
        "properties": {"selection": {"type": "string"}, "kind": {"enum": ["face", "edge"]}, "count": {"type": "integer"},
                       "items": {"type": "array", "description": "face: type, area, centroid, normal, radius?, names?; edge: type, length, midpoint, start, end, direction?, radius?"}},
    },
    "feedback": {
        "description": "Structured feedback agents return after an evaluation task (see evals/)",
        "type": "object",
        "required": ["task", "success", "issues", "suggestions"],
        "properties": {
            "task": {"type": "string"},
            "success": {"type": "boolean", "description": "self-reported; graded independently"},
            "issues": {"type": "array", "items": {"type": "object", "properties": {
                "category": {"enum": ["api_missing", "api_confusing", "error_unhelpful", "docs_unclear", "render_missing",
                                      "query_missing", "geometry_failure", "workaround", "other"]},
                "description": {"type": "string"}, "severity": {"enum": ["low", "medium", "high"]}}}},
            "suggestions": {"type": "array", "items": {"type": "string"}},
        },
    },
}
