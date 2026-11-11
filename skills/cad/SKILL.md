---
name: cad
description: Design 3D-printable and machined parts with the `cad` CLI (agent-first parametric CAD on Open CASCADE). Use when asked to model a part, bracket, enclosure, mount, assembly or multi-material print, check dimensions/clearances/wall thickness, render views, or export STEP/STL/3MF. Python scripts in, exact solids, renders and manufacturing files out.
---

# cad — parametric CAD for agents

`cad` turns a Python script into exact solid geometry (BRep), checks it, renders PNG views
and exports STEP, STL or 3MF. Everything is a CLI command with `--json` output.

## 1. Make sure it is installed

```bash
cad --version            # prints "cad X.Y.Z"; if "command not found", install it (below)
```

If it is missing, install it (macOS or Linux; installs `uv` if needed, no compiler required):

```bash
curl -LsSf https://github.com/andrewimm/cli-cad/releases/latest/download/install.sh | sh   # add: -s -- --fea for stress analysis
```

On Linux it may ask for a few system libraries (`sudo apt-get install -y libgl1 libegl1 libfontconfig1`).
Building from source and troubleshooting: the [README's Install section](https://github.com/andrewimm/cli-cad#install).

In a sandbox that forbids Unix sockets (e.g. Codex) the background daemon cannot run; `cad` then
runs each command standalone automatically (same results, a note on stderr, ~0.6 s per command).
Set `CAD_NO_DAEMON=1` to skip the daemon attempt.

## 2. Workflow

```bash
cad init                          # this directory becomes a project (cad.toml + model.py; keeps an existing model.py)
# write model.py (section 3)
cad build                         # -> immutable revision; errors name your script line and give a hint
cad inspect                       # validity, bbox, volume, holes, materials, warnings
cad render --views iso,top        # PNGs in renders/r<N>/ — open them and look
cad export --format stl           # out/r<N>/<part>.stl, with a watertightness check
```

Learn the rest on demand: `cad docs <words>` prints one section (`cad docs holes`,
`cad docs fillet`, `cad docs materials`, `cad docs assemblies`); `cad docs --list`;
`cad examples list` / `cad examples show <name>`; `cad help <command>`.
Add `--json` to any command; exit codes: 0 ok, 2 usage, 3 model error, 4 check failed, 5 not found.

## 3. Writing model.py

```python
from cad import Part, Parameter

w = Parameter("width", 70)                        # declared parameters: change with `cad set width 80`

def build():                                      # return a Part, a list of Parts, or {name: Part}
    p = Part("cover", material="PETG")            # one Part = one solid body
    p.box(w, 45, 3, name="body")                  # width X, depth Y, height Z; centred on X/Y, bottom on Z = 0
    p.hole_pattern(3.4, spacing=(w - 12, 33), count=(2, 2))   # centre-to-centre spacing, grid centred on (0, 0)
    p.hole(10, at=(0, 0))                         # drilled down (-z) from where it enters material
    p.fillet(p.edges().vertical(), 4)             # select edges/faces with predicates, never indices
    p.assert_valid()
    return p
```

Bodies (each takes `op="add" | "cut" | "intersect"`, `name=`, returns a feature):
`box(w, d, h, at=, align=)`, `cylinder(dia, h, at=, axis="z")`, `sphere(dia, at=)`,
`extrude(profile, distance, plane="XY", offset=0, symmetric=False, through=False)`, `revolve(profile, plane="XZ")`.
`box`/`cylinder` accept a list of points for `at` (many bosses/ribs in one fast feature).
Profiles: `Profile.rect/rounded_rect/circle/slot/polygon/regular_polygon(across_flats=)`, combine with `+` / `-`, `.offset(d)`.
Holes: `hole`, `holes(d, positions)`, `hole_pattern`, `bolt_circle`; `depth=None` is through;
`counterbore=(d, depth)`, `countersink=(d, 90)`; `direction=` may be any vector.
Shapes: `loft([(Profile.rect(40, 20), 0), (Profile.circle(15), 30)])`, `sweep(profile, Path.polyline(pts, radius=10))`
(also `Path.spline/arc/helix`), `draft(2)` (`cad docs loft`).
Dress-up: `fillet(edges, r)`, `chamfer(edges, d)`, `shell(t, open_faces=...)`. Transforms: `translate`, `rotate`, `mirror`.
Printing: `screw_hole("M3", at=, kind="clearance|counterbore|countersunk|tap|insert|nut")` (`cad fasteners`),
`bottom_chamfer(0.5)`, `snap_hook(on=, length=, thickness=, width=, catch=)` (checks strain), `thread("M8", length=)`,
`threaded_hole("M8", at=)`. `cad docs printing` for details.
Text: `engrave("SN 01", on=p.faces("body.top"), size=6, depth=0.6)` / `emboss(..., height=0.5)` on any flat
face (`size` = capital height mm; `at=(u, v)` from the face centre; `font=`, `bold=True`; `cad fonts`).

Selections chain: `p.faces().facing("+z").max("z")`, `p.edges().vertical().convex()`, `.concave()`,
`.circular(radius=)`, `.nearest((x, y, z))`, `.one()` (fails instead of guessing). Named references survive
later features: `p.faces("body.top")`, `p.faces("hole1.wall")`, a bare feature id (`p.faces("hole1")`),
or your own `p.tag("mount", p.faces().facing("-z"))`.

## 4. Conventions that trip agents up

- Units mm and degrees; right-handed, **Z up**. `front` view looks from −Y, `top` from +Z.
- `box` is centred in X/Y with its bottom at `at.z` unless you pass `align=("min", "center", "max")` per axis.
- Sketch planes: `XY` (normal +Z), `YZ` (u=Y, v=Z, normal +X), **`XZ` (u=X, v=Z, normal −Y)**:
  a slab from Y = y0 to y0 + t is `extrude(profile, -t, plane="XZ", offset=-y0)`.
- 2D hole positions are in the two axes perpendicular to the direction (±z → (x, y); ±y → (x, z); ±x → (y, z))
  and start where the drill line first enters material. Pass a 3D point to start exactly somewhere.
- `rotate(angle, axis="y")` turns +Z toward +X (right-hand rule); use a negative angle for the other way.
- Fillet failures say which edges fail and why; fillet fewer edges per call or reduce the radius.
- Warnings matter: `CUT_NO_EFFECT` (missed the part), `DISCONNECTED_BODIES`, `BODY_SPLIT`, `HOLE_MISSED`.
- `find_holes()` measures holes in the actual geometry; `part.find_holes()` ≠ `part.holes(...)` (which drills).

## 5. Verify before you finish

| requirement | check |
|---|---|
| sizes, positions | `cad inspect`, `cad measure --bbox` |
| holes | `cad measure --holes` |
| wall thickness | `cad measure <part> --thickness` (holes near edges leave thin ligaments) |
| clearance to other parts | `cad clearance --min 0.5` (every pair: clear / touching / overlap) |
| a component you design around | `Part("servo", reference=True)` (rendered, never exported) + `cad clearance` |
| moving parts | model in place, `Assembly` + `asm.revolute("knee", upper, lower, axis=upper.faces("knee.wall"), angle="knee_angle")`, return the assembly; `cad joints`, `cad sweep knee 0:90:15 --min 0.5 --render front` (`cad docs joints`) |
| hidden internals | `cad render --views front --section y=0` |
| a vendor part (STEP/STL) | `cad info vendor/x.step`, then `Part.from_file("vendor/x.step", reference=True)`; keep it where the file puts it; outline at a height: `cad measure x --section z=-5` |
| will it print, how long, how many grams | `cad slice` (Bambu Studio; `NEEDS_SUPPORT` = `part.print_on(face)` to lay it on another face, or `--supports auto`) |
| strong / stiff enough under load | `Study` in the script + `cad fea` (safety factor, hot spots -> the feature and parameter to change), `cad render --fea NAME` (`cad docs stress`) |

Renders show shape; numbers prove it. Do not report success until the checks pass.

## 6. 3D printing and materials

```python
from cad import Part, Material

case = Part("case", material="PETG")              # built-ins: PLA PETG ABS ASA TPU PA12 PC Resin Aluminium Steel Brass
seal = Part("seal", material="TPU")
badge = Part("badge", material=Material("PLA", color="#e8a050"))   # custom colour (or density=)
case.box(40, 30, 10)
case.mass()                                       # grams from the material density
```

- One material per part; a multi-material print is several parts touching in place (not overlapping).
- `cad export --format 3mf --3mf-mode multimaterial`: one piece printed with several filaments
  (Bambu Studio, OrcaSlicer and Cura load it as one object, part k on filament k; for PrusaSlicer add
  `--3mf-for prusa`). `cad export --format 3mf`: separate pieces (every slicer).
  Set the default in cad.toml: `[export]` `threemf_mode = "multimaterial"`. `cad materials` lists the library.
- `cad slice [--printer "P1S"] [--process "0.16mm Optimal"] [--supports auto]`: print time, grams per filament
  and a ready-to-print `.gcode.3mf` via Bambu Studio (if installed). `cad docs slicing` for options.

## 7. Strength: stress analysis

```python
from cad import Part, Study

arm = Part("arm", material="PETG")
arm.box(80, 12, 5, name="beam")
arm.hole(4, at=(-34, 0), name="pivot")
s = Study("lift", arm, target=2)             # target safety factor
s.fixed("pivot.wall")                        # where it is held
s.force("beam.right", 10, "-z")              # N; also bearing() for pins in holes, torque(), pressure(), gravity()
```

- `cad fea` (exit 4 below target); fix hotspot 1 (its `parameters` / `suggestions` name what to change), rebuild,
  re-run. Iterate with `-q draft` (~2 s), confirm with the default `normal`.
- The verdict is judged away from fixed faces (ideal clamps inflate stress there). A hot spot on a sharp inside
  edge keeps it failing until you fillet that edge (`STRESS_SINGULARITY` gives the exact call; `cad inspect` lists
  sharp inside edges). For links with round ends use `Profile.tapered_slot`: no inside corners to fillet.
- Coplanar faces merge when bodies join: load part of a merged face with `at=(x, y, z), radius=r`.
- Optional install; if `cad fea` says `FEA_UNAVAILABLE`, run the command in its hint (or tell the user).
