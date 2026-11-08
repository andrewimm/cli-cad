"""Deterministic headless renderer.

A small software rasteriser (NumPy z-buffer) so that rendering works anywhere
Python runs: no GPU, display server or OpenGL context is required, and the same
inputs always produce the same pixels.  The public entry point is
:func:`render_views`; the backend is isolated behind :func:`rasterize` so a GPU
renderer (e.g. wgpu) can replace it without changing the API or metadata.

Camera conventions (Z up, right-handed, orthographic):

=========  ==================  ===========  ==============
view       camera looks from   screen up    screen right
=========  ==================  ===========  ==============
front      -Y                  +Z           +X
back       +Y                  +Z           -X
right      +X                  +Z           +Y
left       -X                  +Z           -Y
top        +Z                  +Y           +X
bottom     -Z                  -Y           +X
iso        (+1, -1, +1)        ~+Z          (+1, +1, 0)/√2
=========  ==================  ===========  ==============

Arbitrary views: ``"az=30,el=20"`` (azimuth degrees from front toward right,
elevation degrees above the horizon) or ``"dir=1,-2,0.5"`` (direction from the
model toward the camera).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .errors import INVALID_ARGUMENT, CadError
from .tessellate import Mesh, tessellate

RENDERER_VERSION = "softraster-1"

STANDARD_VIEWS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "front": ((0, -1, 0), (0, 0, 1)),
    "back": ((0, 1, 0), (0, 0, 1)),
    "right": ((1, 0, 0), (0, 0, 1)),
    "left": ((-1, 0, 0), (0, 0, 1)),
    "top": ((0, 0, 1), (0, 1, 0)),
    "bottom": ((0, 0, -1), (0, -1, 0)),
    "iso": ((1, -1, 1), (0, 0, 1)),
    "iso_back": ((-1, 1, 1), (0, 0, 1)),
    "iso_left": ((-1, -1, 1), (0, 0, 1)),
    "iso_bottom": ((1, -1, -1), (0, 0, 1)),
}
DEFAULT_VIEWS = ("iso", "front", "right", "top")
ALL_VIEWS = ("iso", "front", "back", "left", "right", "top", "bottom")
STYLES = ("shaded_edges", "shaded", "lines")

PALETTE = [
    (0.62, 0.69, 0.78),  # steel blue-grey
    (0.85, 0.62, 0.42),  # copper
    (0.55, 0.75, 0.55),  # sage
    (0.80, 0.55, 0.65),  # rose
    (0.75, 0.72, 0.50),  # olive
    (0.55, 0.65, 0.85),  # periwinkle
]


# --------------------------------------------------------------------------- camera


@dataclass(frozen=True)
class Camera:
    name: str
    eye: np.ndarray  # unit vector from target toward the camera
    up: np.ndarray  # unit screen-up vector (orthogonal to eye)
    right: np.ndarray  # unit screen-right vector

    @staticmethod
    def from_vectors(name: str, eye, up=(0, 0, 1)) -> "Camera":
        e = np.asarray(eye, dtype=float)
        if np.linalg.norm(e) < 1e-12:
            raise CadError(INVALID_ARGUMENT, f"view {name!r}: camera direction has zero length")
        e = e / np.linalg.norm(e)
        u = np.asarray(up, dtype=float)
        if abs(np.dot(u / max(np.linalg.norm(u), 1e-12), e)) > 0.999:
            u = np.array([0.0, 1.0, 0.0]) if abs(e[1]) < 0.9 else np.array([0.0, 0.0, 1.0])
        u = u - np.dot(u, e) * e
        u = u / np.linalg.norm(u)
        forward = -e
        r = np.cross(forward, u)
        return Camera(name, e, u, r / np.linalg.norm(r))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "projection": "orthographic",
            "direction_to_camera": _rl(self.eye),
            "view_direction": _rl(-self.eye),
            "screen_up": _rl(self.up),
            "screen_right": _rl(self.right),
            "screen_axes": {"right": _axis_label(self.right), "up": _axis_label(self.up)},
        }


def parse_view(spec: str | dict | Camera) -> Camera:
    """'iso' | 'front' | ... | 'az=30,el=20' | 'dir=x,y,z[,up=x,y,z]' | {'direction':..., 'up':...}."""
    if isinstance(spec, Camera):
        return spec
    if isinstance(spec, dict):
        return Camera.from_vectors(spec.get("name", "custom"), spec["direction"], spec.get("up", (0, 0, 1)))
    s = spec.strip().lower()
    if s in STANDARD_VIEWS:
        e, u = STANDARD_VIEWS[s]
        return Camera.from_vectors(s, e, u)
    kv: dict[str, str] = {}
    for part in _split_spec(s):
        if "=" not in part and ":" not in part:
            raise CadError(INVALID_ARGUMENT, f"unknown view {spec!r}", hint=f"use one of {sorted(STANDARD_VIEWS)}, 'az=30,el=20' or 'dir=1,-1,1'")
        k, v = part.replace(":", "=", 1).split("=", 1)
        kv[k.strip()] = v.strip()
    up = tuple(float(c) for c in kv["up"].split(",")) if "up" in kv else (0.0, 0.0, 1.0)
    if "dir" in kv:
        d = tuple(float(c) for c in kv["dir"].split(","))
        if len(d) != 3:
            raise CadError(INVALID_ARGUMENT, f"view {spec!r}: dir needs 3 components")
        return Camera.from_vectors(_safe_name(spec), d, up)
    if "az" in kv or "el" in kv:
        az = math.radians(float(kv.get("az", 0)))
        el = math.radians(float(kv.get("el", 0)))
        d = (math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))
        return Camera.from_vectors(_safe_name(spec), d, up)
    raise CadError(INVALID_ARGUMENT, f"cannot parse view {spec!r}")


def _split_spec(s: str) -> list[str]:
    # "dir=1,-1,1,up=0,0,1" -> ["dir=1,-1,1", "up=0,0,1"]; also accepts ';'
    parts, cur = [], ""
    for tok in s.replace(";", ",").split(","):
        if ("=" in tok or ":" in tok) and cur:
            parts.append(cur)
            cur = tok
        else:
            cur = f"{cur},{tok}" if cur else tok
    if cur:
        parts.append(cur)
    return parts


def _safe_name(spec: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_." else "_" for c in spec.strip())
    return keep.strip("_") or "custom"


def _rl(v) -> list[float]:
    return [round(float(c), 6) + 0.0 for c in v]


def _axis_label(v) -> str:
    v = np.asarray(v)
    i = int(np.argmax(np.abs(v)))
    if abs(v[i]) > 0.999:
        return ("+" if v[i] > 0 else "-") + "XYZ"[i]
    return "(" + ", ".join(f"{c:+.3f}" for c in v) + ")"


# --------------------------------------------------------------------------- scene


@dataclass
class SceneItem:
    name: str
    mesh: Mesh
    color: tuple[float, float, float]
    bounds: tuple | None = None  # exact BRep (min, max); mesh bounds are used if absent


def _parse_color(c, default) -> tuple[float, float, float]:
    if c is None:
        return default
    if isinstance(c, str):
        h = c.lstrip("#")
        named = {"red": "d9534f", "green": "5cb85c", "blue": "5b8bd9", "grey": "a0a8b0", "gray": "a0a8b0",
                 "white": "f0f0f0", "black": "303030", "orange": "e8a050", "yellow": "e0d060"}
        h = named.get(c.lower(), h)
        if len(h) != 6:
            raise CadError(INVALID_ARGUMENT, f"cannot parse colour {c!r}", hint="use '#rrggbb' or (r, g, b) in 0..1")
        return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    t = tuple(float(x) for x in c)
    if max(t) > 1:
        t = tuple(x / 255 for x in t)
    return t  # type: ignore[return-value]


def build_scene(model: Any, deflection: float | None = None, mesh_cache: dict | None = None) -> list[SceneItem]:
    """Accept a Part, list/tuple of Parts, dict name->Part or raw TopoDS_Shape."""
    from .part import Part

    items: list[tuple[str, Any, Any]] = []
    if isinstance(model, Part):
        items.append((model.name, model.shape, model.color))
    elif isinstance(model, dict):
        for k, p in model.items():
            items.append((k, p.shape if isinstance(p, Part) else p, getattr(p, "color", None)))
    elif isinstance(model, (list, tuple)):
        for p in model:
            items.append((getattr(p, "name", "shape"), p.shape if isinstance(p, Part) else p, getattr(p, "color", None)))
    else:
        items.append(("shape", model, None))
    scene = []
    for i, (name, shape, color) in enumerate(items):
        key = (id(shape), deflection)
        mesh = mesh_cache.get(key) if mesh_cache is not None else None
        if mesh is None:
            mesh = tessellate(shape, deflection)
            if mesh_cache is not None:
                mesh_cache[key] = mesh
        from . import _occ

        scene.append(SceneItem(name, mesh, _parse_color(color, PALETTE[i % len(PALETTE)]), _occ.bbox(shape)))
    return scene


# --------------------------------------------------------------------------- rasteriser


def rasterize(
    scene: list[SceneItem],
    cam: Camera,
    width: int,
    height: int,
    *,
    style: str = "shaded_edges",
    background=(1.0, 1.0, 1.0),
    supersample: int = 2,
    margin: float = 0.08,
    edge_color=(0.12, 0.12, 0.14),
    fit_bounds: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[Image.Image, dict]:
    """Render ``scene`` from ``cam``.  Returns (image, framing metadata)."""
    if style not in STYLES:
        raise CadError(INVALID_ARGUMENT, f"unknown style {style!r}", hint=f"use one of {STYLES}")
    ss = max(1, int(supersample))
    W, H = width * ss, height * ss
    allv = np.concatenate([it.mesh.vertices for it in scene]) if scene else np.zeros((0, 3))
    if len(allv) == 0:
        raise CadError(INVALID_ARGUMENT, "nothing to render: the model has no tessellated faces")
    R = np.stack([cam.right, cam.up, -cam.eye])  # rows: screen x, screen y, depth (into screen)

    # framing: fit the projected extent of the model (or fit_bounds corners)
    if fit_bounds is not None:
        lo, hi = fit_bounds
        pts = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    else:
        pts = allv
    proj = pts @ R.T
    umin, vmin = proj[:, 0].min(), proj[:, 1].min()
    umax, vmax = proj[:, 0].max(), proj[:, 1].max()
    du, dv = max(umax - umin, 1e-9), max(vmax - vmin, 1e-9)
    scale = min(W * (1 - 2 * margin) / du, H * (1 - 2 * margin) / dv)  # px per mm (supersampled)
    cu, cv = (umin + umax) / 2, (vmin + vmax) / 2
    depth_c = float((proj[:, 2].min() + proj[:, 2].max()) / 2)
    center_world = R.T @ np.array([cu, cv, depth_c])

    def to_screen(v: np.ndarray):
        p = v @ R.T
        sx = W / 2 + (p[:, 0] - cu) * scale
        sy = H / 2 - (p[:, 1] - cv) * scale
        return sx, sy, p[:, 2]

    color = np.empty((H, W, 3), dtype=np.float32)
    color[:] = background
    zbuf = np.full((H, W), np.inf, dtype=np.float64)
    idbuf = np.full((H, W), -1, dtype=np.int64)

    key = cam.right * -0.45 + cam.up * 0.65 + cam.eye * 0.6
    key /= np.linalg.norm(key)
    fill = cam.right * 0.6 + cam.up * -0.2 + cam.eye * 0.75
    fill /= np.linalg.norm(fill)

    face_base = 0
    for item in scene:
        m = item.mesh
        if len(m.triangles) == 0:
            continue
        sx, sy, sz = to_screen(m.vertices)
        n = m.normals
        if style == "lines":
            shade = np.ones((len(n), 3)) * np.array(background)
        else:
            lam = 0.30 + 0.55 * np.clip(n @ key, 0, None) + 0.25 * np.clip(n @ fill, 0, None) + 0.12 * np.abs(n @ cam.eye)
            # gentle specular so curved surfaces read as curved
            h = (key + cam.eye) / np.linalg.norm(key + cam.eye)
            spec = 0.18 * np.clip(n @ h, 0, None) ** 24
            shade = np.clip(lam[:, None] * np.array(item.color)[None, :] + spec[:, None], 0, 1)
        _raster_triangles(sx, sy, sz, m.triangles, shade, m.face_ids + face_base, color, zbuf, idbuf)
        face_base += int(m.face_ids.max()) + 1 if len(m.face_ids) else 0

    if style in ("shaded_edges", "lines"):
        diag = float(np.linalg.norm(allv.max(0) - allv.min(0)))
        lin = max(it.mesh.linear_deflection for it in scene)
        bias = 4 * lin + 2e-4 * diag + 1.5 / scale
        lw = max(1.0, 1.1 * ss)
        # silhouettes and depth discontinuities from the buffers
        _silhouettes(zbuf, idbuf, color, edge_color, jump=max(0.01 * diag, 3.0 / scale))
        for item in scene:
            _raster_edges(item.mesh.edges, to_screen, zbuf, color, edge_color, bias, lw)

    img = Image.fromarray((np.clip(color, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    if ss > 1:
        img = img.resize((width, height), Image.Resampling.LANCZOS)
    framing = {
        "mm_per_pixel": round(1.0 / (scale / ss), 6),
        "view_center_world": _rl(center_world),
        "visible_extent_mm": [round(width * ss / scale, 4), round(height * ss / scale, 4)],
        "pixel_to_world": "world = view_center_world + (px - width/2) * mm_per_pixel * screen_right "
        "- (py - height/2) * mm_per_pixel * screen_up  (+ any offset along view_direction)",
        "_scale_px_per_mm": scale / ss,
        "_cu": cu,
        "_cv": cv,
    }
    return img, framing


def _raster_triangles(sx, sy, sz, tris, shade, fids, color, zbuf, idbuf, chunk_fragments: int = 600_000) -> None:
    """Vectorised scanline rasterisation with a deterministic z-buffer resolve.

    Fragments (pixel centres inside a triangle) are generated per row span, so
    cost is proportional to covered pixels rather than triangle bounding boxes.
    """
    H, W = zbuf.shape
    P = np.stack([sx, sy], axis=1)
    A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    area = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (C[:, 0] - A[:, 0]) * (B[:, 1] - A[:, 1])
    ys = np.stack([A[:, 1], B[:, 1], C[:, 1]], axis=1)
    r0 = np.clip(np.ceil(ys.min(1) - 0.5), 0, H).astype(np.int64)
    r1 = np.clip(np.floor(ys.max(1) - 0.5), -1, H - 1).astype(np.int64)
    nrows = np.where(np.abs(area) > 1e-12, np.maximum(r1 - r0 + 1, 0), 0)
    order = np.nonzero(nrows)[0]
    if len(order) == 0:
        return
    # chunk triangles so the number of (triangle,row) spans stays bounded
    est = nrows[order] * np.maximum(1, np.ceil(np.ptp(np.stack([A[order, 0], B[order, 0], C[order, 0]], 1), axis=1))).astype(np.int64)
    bounds = np.searchsorted(np.cumsum(est), np.arange(chunk_fragments, est.sum() + chunk_fragments, chunk_fragments))
    start = 0
    for end in list(bounds) + [len(order)]:
        end = int(min(max(end, start + 1), len(order)))
        if start >= len(order):
            break
        _raster_chunk(order[start:end], A, B, C, area, r0, nrows, sz, tris, shade, fids, color, zbuf, idbuf)
        start = end


def _raster_chunk(idx, A, B, C, area, r0, nrows, sz, tris, shade, fids, color, zbuf, idbuf) -> None:
    H, W = zbuf.shape
    t = np.repeat(idx, nrows[idx])
    first = np.repeat(np.cumsum(nrows[idx]) - nrows[idx], nrows[idx])
    row = r0[t] + (np.arange(len(t)) - first)
    yc = row + 0.5
    xl = np.full(len(t), np.inf)
    xr = np.full(len(t), -np.inf)
    for P0, P1 in ((A, B), (B, C), (C, A)):
        x0, y0, x1, y1 = P0[t, 0], P0[t, 1], P1[t, 0], P1[t, 1]
        dy = y1 - y0
        ok = (np.minimum(y0, y1) <= yc + 1e-9) & (yc <= np.maximum(y0, y1) + 1e-9) & (np.abs(dy) > 1e-12)
        with np.errstate(divide="ignore", invalid="ignore"):
            x = np.where(ok, x0 + (yc - y0) * (x1 - x0) / np.where(ok, dy, 1), np.nan)
        xl = np.where(ok, np.minimum(xl, x), xl)
        xr = np.where(ok, np.maximum(xr, x), xr)
    c0 = np.clip(np.ceil(xl - 0.5 - 1e-7), 0, W).astype(np.int64)
    c1 = np.clip(np.floor(xr - 0.5 + 1e-7), -1, W - 1).astype(np.int64)
    n = np.maximum(c1 - c0 + 1, 0)
    n[~np.isfinite(xl)] = 0
    tf = np.repeat(t, n)
    if len(tf) == 0:
        return
    rf = np.repeat(row, n)
    firstf = np.repeat(np.cumsum(n) - n, n)
    cf = np.repeat(c0, n) + (np.arange(len(tf)) - firstf)
    px, py = cf + 0.5, rf + 0.5
    a = area[tf]
    w0 = ((B[tf, 0] - px) * (C[tf, 1] - py) - (C[tf, 0] - px) * (B[tf, 1] - py)) / a
    w1 = ((C[tf, 0] - px) * (A[tf, 1] - py) - (A[tf, 0] - px) * (C[tf, 1] - py)) / a
    w2 = 1.0 - w0 - w1
    tv = tris[tf]
    z = w0 * sz[tv[:, 0]] + w1 * sz[tv[:, 1]] + w2 * sz[tv[:, 2]]
    pix = rf * W + cf
    # nearest fragment per pixel (lexsort is stable -> deterministic ties)
    o = np.lexsort((z, pix))
    pix_o = pix[o]
    keep = np.ones(len(o), dtype=bool)
    keep[1:] = pix_o[1:] != pix_o[:-1]
    sel = o[keep]
    zf = zbuf.reshape(-1)
    win = z[sel] < zf[pix[sel]]
    sel = sel[win]
    p = pix[sel]
    zf[p] = z[sel]
    idbuf.reshape(-1)[p] = fids[tf[sel]]
    tvs = tv[sel]
    col = w0[sel, None] * shade[tvs[:, 0]] + w1[sel, None] * shade[tvs[:, 1]] + w2[sel, None] * shade[tvs[:, 2]]
    color.reshape(-1, 3)[p] = col


def _silhouettes(zbuf, idbuf, color, edge_color, jump: float) -> None:
    bg = ~np.isfinite(zbuf)
    zf = np.where(bg, np.nan, zbuf)
    mark = np.zeros(zbuf.shape, dtype=bool)
    for axis in (0, 1):
        lo_sl = (slice(None, -1), slice(None)) if axis == 0 else (slice(None), slice(None, -1))
        hi_sl = (slice(1, None), slice(None)) if axis == 0 else (slice(None), slice(1, None))
        a, b, ia, ib = zf[lo_sl], zf[hi_sl], idbuf[lo_sl], idbuf[hi_sl]
        bga, bgb = np.isnan(a), np.isnan(b)
        with np.errstate(invalid="ignore"):
            disc = (bga ^ bgb) | ((ia != ib) & (np.abs(a - b) > jump)) | (np.abs(a - b) > 4 * jump)
        disc &= ~(bga & bgb)
        # mark the nearer (foreground) pixel of each discontinuity
        with np.errstate(invalid="ignore"):
            a_front = np.where(bgb, True, np.where(bga, False, a <= b))
        ma = disc & a_front
        mb = disc & ~a_front
        if axis == 0:
            mark[:-1, :] |= ma
            mark[1:, :] |= mb
        else:
            mark[:, :-1] |= ma
            mark[:, 1:] |= mb
    color[mark] = edge_color


def _raster_edges(edges, to_screen, zbuf, color, edge_color, bias, lw) -> None:
    if not edges:
        return
    H, W = zbuf.shape
    xs, ys, zs = [], [], []
    for pl in edges:
        sx, sy, sz = to_screen(pl)
        for i in range(len(pl) - 1):
            L = math.hypot(sx[i + 1] - sx[i], sy[i + 1] - sy[i])
            n = max(2, int(L * 2) + 1)
            t = np.linspace(0, 1, n)
            xs.append(sx[i] + t * (sx[i + 1] - sx[i]))
            ys.append(sy[i] + t * (sy[i + 1] - sy[i]))
            zs.append(sz[i] + t * (sz[i + 1] - sz[i]))
    X, Y, Z = np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)
    r = lw / 2
    offs = [(dx, dy) for dx in np.arange(-r, r + 1e-9, 0.5) for dy in np.arange(-r, r + 1e-9, 0.5) if dx * dx + dy * dy <= r * r + 1e-9]
    # an edge sample is visible if nothing in the depth buffer is clearly in front of it
    ix = np.clip(X.astype(np.int64), 0, W - 1)
    iy = np.clip(Y.astype(np.int64), 0, H - 1)
    vis = (Z <= zbuf[iy, ix] + bias) | ~np.isfinite(zbuf[iy, ix])
    X, Y = X[vis], Y[vis]
    for dx, dy in offs:
        jx = np.clip((X + dx).astype(np.int64), 0, W - 1)
        jy = np.clip((Y + dy).astype(np.int64), 0, H - 1)
        color[jy, jx] = edge_color


# --------------------------------------------------------------------------- annotation


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def _nice_length(target: float) -> float:
    if target <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(target))
    for m in (1, 2, 5, 10):
        if m * e >= target * 0.999:
            return m * e
    return 10 * e


def annotate(img: Image.Image, cam: Camera, framing: dict, title: str, bbox_size: Sequence[float]) -> Image.Image:
    W, H = img.size
    d = ImageDraw.Draw(img)
    fs = max(11, int(H / 45))
    f = _font(fs)
    sx, sy, sz = bbox_size
    line1 = f"{title}  |  view: {cam.name}  (right={_axis_label(cam.right)}, up={_axis_label(cam.up)})"
    line2 = f"orthographic  |  1 px = {framing['mm_per_pixel']:.4g} mm  |  bbox {sx:.4g} x {sy:.4g} x {sz:.4g} mm (X x Y x Z)"
    d.text((8, 6), line1, fill=(40, 40, 40), font=f)
    d.text((8, 8 + fs + 2), line2, fill=(90, 90, 90), font=f)

    # axis triad (bottom-left)
    L = max(24, int(H / 12))
    ox, oy = 14 + L, H - 14 - L
    cols = {"X": (210, 50, 50), "Y": (40, 160, 60), "Z": (50, 90, 220)}
    for name, axis in (("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))):
        a = np.array(axis, dtype=float)
        u, v = float(a @ cam.right), float(a @ cam.up)
        ex, ey = ox + u * L, oy - v * L
        if math.hypot(u, v) < 0.15:
            toward = float(a @ cam.eye) > 0
            d.ellipse((ox - 5, oy - 5, ox + 5, oy + 5), outline=cols[name], width=2)
            if toward:
                d.ellipse((ox - 1.5, oy - 1.5, ox + 1.5, oy + 1.5), fill=cols[name])
            d.text((ox + 7, oy + 4), name + ("(out)" if toward else "(in)"), fill=cols[name], font=f)
            continue
        d.line((ox, oy, ex, ey), fill=cols[name], width=3)
        d.text((ex + 3 * np.sign(u) - (fs * 0.3 if u < 0 else 0), ey - fs / 2 - 2 * np.sign(v)), name, fill=cols[name], font=f)

    # scale bar (bottom-right)
    mmpp = framing["mm_per_pixel"]
    bar_mm = _nice_length(W * 0.18 * mmpp)
    bar_px = bar_mm / mmpp
    x1, y = W - 16, H - 18
    x0 = x1 - bar_px
    d.line((x0, y, x1, y), fill=(40, 40, 40), width=3)
    d.line((x0, y - 5, x0, y + 5), fill=(40, 40, 40), width=2)
    d.line((x1, y - 5, x1, y + 5), fill=(40, 40, 40), width=2)
    label = f"{bar_mm:g} mm"
    tw = d.textlength(label, font=f)
    d.text(((x0 + x1) / 2 - tw / 2, y - fs - 8), label, fill=(40, 40, 40), font=f)
    return img


# --------------------------------------------------------------------------- public API


def scene_bounds(scene: list[SceneItem]) -> tuple[np.ndarray, np.ndarray]:
    los, his = [], []
    for it in scene:
        lo, hi = (np.asarray(it.bounds[0]), np.asarray(it.bounds[1])) if it.bounds else it.mesh.bounds
        los.append(lo)
        his.append(hi)
    return np.min(los, axis=0), np.max(his, axis=0)


def render_one(
    scene: list[SceneItem],
    cam: Camera,
    *,
    size: tuple[int, int] = (1024, 768),
    style: str = "shaded_edges",
    background=(1.0, 1.0, 1.0),
    title: str = "model",
    annotate_images: bool = True,
    supersample: int = 2,
    metadata: dict | None = None,
) -> tuple[Image.Image, dict]:
    """Render one view; returns the image and its metadata dict (without the image path)."""
    lo, hi = scene_bounds(scene)
    img, framing = rasterize(scene, cam, size[0], size[1], style=style, background=background, supersample=supersample)
    if annotate_images:
        img = annotate(img, cam, framing, title, [float(c) for c in (hi - lo)])
    meta = {
        "image": {"width": size[0], "height": size[1], "format": "png"},
        "camera": cam.to_dict(),
        "framing": {k: v for k, v in framing.items() if not k.startswith("_")},
        "model": {
            "name": title,
            "parts": [it.name for it in scene],
            "bbox": {"min": _rl(lo), "max": _rl(hi), "size": _rl(hi - lo)},
            "units": "mm",
            **(metadata or {}),
        },
        "style": style,
        "renderer": RENDERER_VERSION,
        "conventions": "right-handed, Z up; front view looks from -Y toward +Y",
    }
    return img, meta


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.png")
    img.save(tmp, format="PNG")
    os.replace(tmp, path)


def parse_views(views: Sequence[str] | str) -> list[Camera]:
    if isinstance(views, str):
        views = list(ALL_VIEWS) if views.strip() == "all" else _split_views(views)
    out = []
    for v in views:
        if isinstance(v, str) and v.strip() == "all":
            out.extend(parse_view(x) for x in ALL_VIEWS)
        else:
            out.append(parse_view(v))
    return out


def render_views(
    model: Any,
    views: Sequence[str] | str = DEFAULT_VIEWS,
    out_dir: str | os.PathLike = "renders",
    *,
    size: tuple[int, int] = (1024, 768),
    style: str = "shaded_edges",
    background: str | Sequence[float] = "#ffffff",
    prefix: str | None = None,
    annotate_images: bool = True,
    supersample: int = 2,
    deflection: float | None = None,
    sheet: bool = True,
    metadata: dict | None = None,
    mesh_cache: dict | None = None,
) -> list[dict]:
    """Render ``model`` from each view to ``<out_dir>/<prefix>_<view>.png``.

    ``model`` is a Part, a list/dict of Parts, or a raw OCCT shape.  Each PNG
    gets a sibling ``.json`` with camera, framing and model metadata.  With
    ``sheet=True`` a ``<prefix>_sheet.png`` contact sheet of all views is
    written too.  Returns one dict per image.
    """
    cams = parse_views(views)
    out = Path(out_dir)
    scene = build_scene(model, deflection, mesh_cache)
    title = prefix or "+".join(it.name for it in scene)
    prefix = prefix or _safe_name(title)
    bg = _parse_color(background, (1.0, 1.0, 1.0))
    results, images = [], []
    for cam in cams:
        img, meta = render_one(scene, cam, size=size, style=style, background=bg, title=title,
                               annotate_images=annotate_images, supersample=supersample, metadata=metadata)
        path = out / f"{prefix}_{cam.name}.png"
        save_png(img, path)
        meta["image"]["path"] = str(path)
        mpath = path.with_suffix(".json")
        mpath.write_text(json.dumps(meta, indent=2))
        results.append({"view": cam.name, "path": str(path), "metadata_path": str(mpath), "camera": meta["camera"], "framing": meta["framing"]})
        images.append((cam.name, img))
    if sheet and len(images) > 1:
        sp = out / f"{prefix}_sheet.png"
        save_png(contact_sheet(images, size), sp)
        results.append({"view": "sheet", "path": str(sp), "views": [n for n, _ in images]})
    return results


def _split_views(s: str) -> list[str]:
    """'iso,front,az=30,el=20,dir=1,-1,1' -> ['iso', 'front', 'az=30,el=20', 'dir=1,-1,1']."""
    out: list[str] = []
    for tok in (t.strip() for t in s.split(",")):
        if not tok:
            continue
        prev = out[-1] if out else ""
        join = False
        if "=" in prev:
            try:
                float(tok)
                join = True
            except ValueError:
                key = tok.split("=", 1)[0]
                join = (key == "el" and "az=" in prev and "el=" not in prev) or \
                       (key == "az" and "el=" in prev and "az=" not in prev) or \
                       (key == "up" and "up=" not in prev)
        if join:
            out[-1] = f"{prev},{tok}"
        else:
            out.append(tok)
    return out


def contact_sheet(images: list[tuple[str, Image.Image]], size: tuple[int, int]) -> Image.Image:
    n = len(images)
    cols = 2 if n <= 4 else 3
    rows = math.ceil(n / cols)
    w, h = size[0] // 2, size[1] // 2
    sheet = Image.new("RGB", (cols * w, rows * h), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, (name, img) in enumerate(images):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(img.resize((w, h), Image.Resampling.LANCZOS), (x, y))
        d.rectangle((x, y, x + w - 1, y + h - 1), outline=(200, 200, 200))
    return sheet
