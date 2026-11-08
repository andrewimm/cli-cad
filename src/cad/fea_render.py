"""Pictures of a stress analysis: the part coloured by a result field, with a legend,
numbered hot spots (matching the JSON report), supports and loads.

Fields: ``stress`` (von Mises, MPa), ``safety`` (safety factor bands against the
study's target), ``displacement`` (mm) and ``layers`` (tension pulling the print
layers apart, MPa).  ``deformed`` draws the bent shape, exaggerated so it is
visible, with the original outline faintly behind it.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import ImageDraw

from .errors import INVALID_ARGUMENT, CadError
from .renderer import SceneItem, _arrowhead, _font
from .tessellate import Mesh

VERSION = "fea-render-3"  # part of render cache keys: bump when the picture changes
FIELDS = ("stress", "safety", "displacement", "layers")
SAFETY_BANDS = ((0.0, (0.84, 0.19, 0.17), "below 1: breaks"), (1.0, (0.95, 0.62, 0.15), "1 to target"),
                (None, (0.27, 0.67, 0.36), "target or more"))
SUPPORT = (40, 90, 200)
LOAD = (200, 40, 160)


def turbo(x: np.ndarray) -> np.ndarray:
    """Google's Turbo colormap (polynomial fit), x in [0, 1] -> RGB in [0, 1]: blue low, red high."""
    x = np.clip(np.asarray(x, dtype=float), 0, 1)[..., None]
    r = np.array([0.13572138, 4.61539260, -42.66032258, 132.13108234, -152.94239396, 59.28637943])
    g = np.array([0.09140261, 2.19418839, 4.84296658, -14.18503333, 4.27729857, 2.82956604])
    b = np.array([0.10667330, 12.64194608, -60.58204836, 110.36276771, -89.90310912, 27.34824973])
    powers = x ** np.arange(6)
    return np.clip(np.stack([powers @ r, powers @ g, powers @ b], axis=-1), 0, 1)


def field_values(arrays: dict, field: str) -> tuple[np.ndarray, str]:
    if field == "stress":
        return arrays["von_mises"], "von Mises stress (MPa)"
    if field == "displacement":
        return np.linalg.norm(arrays["displacement"], axis=1), "displacement (mm)"
    if field == "layers":
        return np.maximum(arrays["layer"], 0.0), "tension across layers (MPa)"
    if field == "safety":
        return arrays["safety"], "safety factor"
    raise CadError(INVALID_ARGUMENT, f"unknown field {field!r}", hint=f"use one of {', '.join(FIELDS)}")


def deform_scale(arrays: dict, diag: float, deformed) -> float:
    """``deformed``: True / "auto" (largest movement drawn as ~6 % of the part's size, never shrunk), or a number."""
    if deformed in (None, False, 0):
        return 0.0
    umax = float(np.linalg.norm(arrays["displacement"], axis=1).max())
    if deformed is True or deformed == "auto":
        return max(1.0, 0.06 * diag / umax) if umax > 0 else 1.0
    return float(deformed)


def scene_item(arrays: dict, report: dict, field: str, scale: float, name: str) -> tuple[SceneItem, dict]:
    """The analysed part as a coloured scene item, plus the legend description."""
    vals, title = field_values(arrays, field)
    V = arrays["vertices"] + scale * arrays["displacement"]
    tris, tface = arrays["tris"], arrays["tri_face"]
    if field == "safety":
        target = report["target"]
        colors = np.empty((len(vals), 3))
        colors[:] = SAFETY_BANDS[2][1]
        colors[vals < target] = SAFETY_BANDS[1][1]
        colors[vals < 1.0] = SAFETY_BANDS[0][1]
        legend = {"kind": "bands", "title": f"{title} (target {target:g})",
                  "bands": [(c, f"{lab.replace('target', f'{target:g}')}") for _, c, lab in SAFETY_BANDS],
                  "min": float(vals.min())}
    else:
        top = float(vals.max()) or 1.0
        colors = turbo(vals / top)
        legend = {"kind": "scale", "title": title, "max": top}
        if field == "stress":
            legend["mark"] = (report["material"]["yield_strength_MPa"], "strength")
        if field == "layers" and report["material"].get("layer_strength_MPa"):
            legend["mark"] = (report["material"]["layer_strength_MPa"], "layer strength")
    # split vertices per BRep face so shading stays crisp across edges
    keys = np.stack([tris.reshape(-1), np.repeat(tface, 3)], axis=1)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    verts = V[uniq[:, 0]]
    tri_new = inv.reshape(-1, 3)
    a, b, c = verts[tri_new[:, 0]], verts[tri_new[:, 1]], verts[tri_new[:, 2]]
    fn = np.cross(b - a, c - a)
    normals = np.zeros_like(verts)
    for k in range(3):
        np.add.at(normals, tri_new[:, k], fn)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-30)
    mesh = Mesh(verts, normals, tri_new.astype(np.int64), tface.astype(np.int64), _feature_edges(V, tris, tface), 0.0, 0.0)
    item = SceneItem(name, mesh, (0.7, 0.7, 0.7), (V.min(0), V.max(0)), vertex_colors=colors[uniq[:, 0]])
    return item, legend


def _feature_edges(V: np.ndarray, tris: np.ndarray, tface: np.ndarray) -> list[np.ndarray]:
    """Mesh edges where two BRep faces meet (the part's visible edges), as 2-point polylines."""
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    f = np.concatenate([tface, tface, tface])
    e = np.sort(e, axis=1)
    order = np.lexsort((f, e[:, 1], e[:, 0]))
    e, f = e[order], f[order]
    same = np.all(e[1:] == e[:-1], axis=1)
    border = np.nonzero(same & (f[1:] != f[:-1]))[0]
    return [V[e[i]] for i in border]


def overlay(arrays: dict, report: dict, legend: dict, scale: float, diag: float, field: str):
    """A render_one overlay callable drawing legend, hot spots, supports, loads and the original outline."""

    def draw(img, cam, framing):
        W, H = img.size
        d = ImageDraw.Draw(img)
        fs = max(11, int(H / 48))
        f = _font(fs)
        k = framing["_scale_px_per_mm"]
        cu, cv = framing["_cu"], framing["_cv"]
        zb, ss = framing["_zbuf"], framing["_ss"]

        def scr(p):
            p = np.asarray(p, dtype=float)
            return W / 2 + (float(p @ cam.right) - cu) * k, H / 2 - (float(p @ cam.up) - cv) * k

        def visible(p) -> bool:
            x, y = scr(p)
            ix, iy = int(x * ss), int(y * ss)
            if not (0 <= ix < zb.shape[1] and 0 <= iy < zb.shape[0]):
                return False
            win = zb[max(0, iy - 2 * ss):iy + 2 * ss + 1, max(0, ix - 2 * ss):ix + 2 * ss + 1]
            depth = float(np.asarray(p, dtype=float) @ -cam.eye)
            return not np.isfinite(win).any() or depth <= np.nanmin(np.where(np.isfinite(win), win, np.nan)) + 0.05 * diag

        if scale > 0:  # original shape: faint outline
            V0 = arrays["vertices"]
            for seg in _feature_edges(V0, arrays["tris"], arrays["tri_face"]):
                (x0, y0), (x1, y1) = scr(seg[0]), scr(seg[1])
                d.line((x0, y0, x1, y1), fill=(170, 170, 170), width=1)

        disp = arrays["displacement"] * scale

        def moved(p):
            p = np.asarray(p, dtype=float)
            if scale == 0:
                return p
            i = int(np.argmin(np.linalg.norm(arrays["vertices"] - p, axis=1)))
            return p + disp[i]

        L = 0.14 * diag
        for ld in report["loads"]:
            if "centroid" not in ld:
                continue
            c = moved(ld["centroid"])
            cx, cy = scr(c)
            if ld["type"] == "fixed":
                s = max(7, H / 70)
                for i in range(3):
                    ox = cx + (i - 1) * s * 1.1
                    d.polygon([(ox, cy), (ox - s / 2, cy + s), (ox + s / 2, cy + s)], outline=SUPPORT, width=2)
                d.line((cx - 2 * s, cy + s + 3, cx + 2 * s, cy + s + 3), fill=SUPPORT, width=2)
                lab = f"fixed {ld['faces']}"
                d.text((cx - d.textlength(lab, font=f) / 2, cy + s + 6), lab, fill=SUPPORT, font=f)
            elif ld["type"] in ("force", "bearing"):
                dv = np.asarray(ld["direction"], dtype=float)
                tx, ty = scr(c - dv * L)
                if math.hypot(tx - cx, ty - cy) < 6:  # pointing at the viewer: a target symbol
                    r = max(8, H / 60)
                    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=LOAD, width=2)
                    d.line((cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7), fill=LOAD, width=2)
                    d.line((cx - r * 0.7, cy + r * 0.7, cx + r * 0.7, cy - r * 0.7), fill=LOAD, width=2)
                else:
                    d.line((tx, ty, cx, cy), fill=LOAD, width=3)
                    _arrowhead(d, (tx, ty), (cx, cy), LOAD, max(9, H / 55))
                d.text((tx + 4, ty - fs - 2), f"{ld['type']} {ld['total_N']:g} N", fill=LOAD, font=f)
            elif ld["type"] == "torque":
                r = max(14, H / 30)
                pts = [(cx + r * math.cos(math.radians(t)), cy - r * math.sin(math.radians(t))) for t in range(30, 300, 12)]
                d.line(pts, fill=LOAD, width=2)
                _arrowhead(d, pts[-2], pts[-1], LOAD, r * 0.5)
                d.text((cx + r + 4, cy - r), f"torque {ld['total_Nm']:g} N*m", fill=LOAD, font=f)
            elif ld["type"] == "pressure":
                d.text((cx + 4, cy - fs - 2), f"pressure {ld.get('total_N', 0):g} N total", fill=LOAD, font=f)

        for h in report["hotspots"]:
            p = moved(h["at"])
            x, y = scr(p)
            vis = visible(p)
            r = max(9, H / 55)
            col = (20, 20, 20) if vis else (120, 120, 120)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255) if vis else None, outline=col, width=2)
            label = str(h["id"])
            tw = d.textlength(label, font=f)
            d.text((x - tw / 2, y - fs / 2 - 1), label, fill=col, font=f)
            if h["id"] == 1:
                txt = f"{h['von_mises_MPa']:.3g} MPa" + ("" if vis else " (behind)")
                d.text((x + r + 3, y - fs / 2), txt, fill=col, font=f)

        _legend(d, W, H, f, fs, legend, field, report)
        verdict = "OK" if report["ok"] else "BELOW TARGET"
        foot = (f"{verdict}: safety factor {report['safety_factor']:g} (target {report['target']:g}), "
                f"peak {report['max_von_mises_MPa']:.3g} MPa, moves up to {report['max_displacement_mm']:.3g} mm")
        if scale > 0:
            foot += f"  |  bend drawn x{scale:.3g}" + (" (true scale)" if abs(scale - 1) < 1e-9 else "")
        grav = [ld for ld in report["loads"] if ld["type"] == "gravity"]
        if grav:
            foot += f"  |  own weight {', '.join(str(g.get('total_N')) for g in grav)} N"
        y = 8 + 2 * (max(11, int(H / 45)) + 2) + 4  # below annotate()'s two title lines
        d.text((8, y), foot, fill=(150, 30, 30) if not report["ok"] else (30, 110, 50), font=f)
        return img

    return draw


def _legend(d, W, H, f, fs, legend: dict, field: str, report: dict) -> None:
    x1 = W - 16
    x0 = x1 - 18
    y0, y1 = int(H * 0.16), int(H * 0.70)
    title = legend["title"]
    tw = d.textlength(title, font=f)
    d.text((min(x1 - tw, W - tw - 6), y0 - 2.2 * fs), title, fill=(30, 30, 30), font=f)
    if legend["kind"] == "bands":
        n = len(legend["bands"])
        hgt = (y1 - y0) / n
        for i, (c, lab) in enumerate(reversed(legend["bands"])):
            ya = y0 + i * hgt
            d.rectangle((x0, ya, x1, ya + hgt - 3), fill=tuple(int(255 * v) for v in c), outline=(60, 60, 60))
            lw = d.textlength(lab, font=f)
            d.text((x0 - lw - 6, ya + hgt / 2 - fs / 2), lab, fill=(30, 30, 30), font=f)
        lab = f"lowest {legend['min']:.3g}"
        d.text((x1 - d.textlength(lab, font=f), y1 + 6), lab, fill=(30, 30, 30), font=f)
        return
    top = legend["max"]
    n = 64
    for i in range(n):
        c = turbo(np.array([1 - i / (n - 1)]))[0]
        ya = y0 + (y1 - y0) * i / n
        d.rectangle((x0, ya, x1, ya + (y1 - y0) / n + 1), fill=tuple(int(255 * v) for v in c))
    d.rectangle((x0, y0, x1, y1), outline=(60, 60, 60))
    for i in range(6):
        v = top * (1 - i / 5)
        y = y0 + (y1 - y0) * i / 5
        lab = f"{v:.3g}"
        d.line((x0 - 4, y, x0, y), fill=(60, 60, 60), width=1)
        d.text((x0 - d.textlength(lab, font=f) - 6, y - fs / 2), lab, fill=(30, 30, 30), font=f)
    mark = legend.get("mark")
    if mark:
        val, name = mark
        if val <= top:
            y = y1 - (y1 - y0) * val / top
            d.line((x0 - 10, y, x1 + 4, y), fill=(0, 0, 0), width=3)
            lab = f"{name} {val:g}"
            d.text((x0 - d.textlength(lab, font=f) - 12, y - fs - 2), lab, fill=(0, 0, 0), font=f)
        else:
            for i, lab in enumerate((f"{name} {val:g}", "(off the scale)")):
                d.text((x1 - d.textlength(lab, font=f), y0 - 2.2 * fs - (2 - i) * (fs + 3)), lab, fill=(30, 30, 30), font=f)
