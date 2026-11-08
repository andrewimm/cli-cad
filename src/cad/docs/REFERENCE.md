# cad — API & CLI reference

Agent-first parametric CAD on Open CASCADE. Write a Python script, build it,
check numbers, look at renders, revise, export. Print one section with
`cad docs <words>` (e.g. `cad docs holes`); list them with `cad docs --list`.

## Quick start

```python
# model.py  (create the project with `cad init`, then `cad build`)
from cad import Part

def build():
    p = Part("cover")                                   # one part = one printable solid
    p.box(70, 45, 3, name="body")                       # 70 (X) x 45 (Y) x 3 (Z) mm, centred on X/Y, bottom on Z = 0
    p.hole_pattern(3.4, spacing=(58, 33), count=(2, 2)) # 2 x 2 holes, centre-to-centre spacing, grid centred on (0, 0)
    p.hole(10, at=(0, 0))                               # one more hole at (x, y), drilled down through the part
    p.fillet(p.edges().vertical(), 4)                   # round the four vertical corners
    p.assert_valid()
    return p
```

```bash
cad build && cad measure --holes        # check sizes and hole positions
cad render --views iso,top              # look at renders/r1/*.png
cad export --format stl                 # printable file: out/r1/cover.stl (mm)
```

## Conventions

- Units: **millimetres** and **degrees**. Right-handed, **Z up**.
- `width` = X, `depth` = Y, `height` = Z.
- Views: `front` looks from −Y (you see the XZ plane, +X right), `right` from +X,
  `top` from +Z (+X right, +Y up), `iso` from (+1, −1, +1).
- Feature ids default to `<type><n>` (`box1`, `hole2`, …); pass `name=` to choose your own (no dots).
- Faces created by a feature get **named references** `"<feature>.<role>"`
  (e.g. `base.top`, `hole1.wall`). They follow the geometry through later
  features. If a later feature destroys a face, using its name raises `REFERENCE_LOST`.

## Workflow

```bash
cad init                    # make the CURRENT directory a project (safe with existing files; keeps model.py if present)
                            # or: cad init my_part   /   cad examples copy mounting_bracket my_part
cad build                   # runs the entry script -> immutable revision (cached if nothing changed)
cad inspect                 # validity, bbox, volume, holes, features, warnings
cad render                  # PNGs in renders/r<N>/ (+ *_sheet.png with all views in one image)
cad render --views az=200,el=25 --part lid      # look again from elsewhere (cheap: meshes are cached)
cad render --views front,iso --section y=0      # cut-away: see cavities, bores, wall thickness (cut faces red)
cad set width 80            # parameter override -> params.toml -> rebuild
cad export --format step,stl
```

Add `--json` to any command for a machine-readable envelope
`{"ok", "command", "result", "warnings", "error"}`. Exit codes: 0 ok,
1 internal, 2 usage / unknown parameter, 3 model error, 4 validation failed,
5 not found, 6 worker crashed, 7 timeout, 8 daemon unavailable.

One-shot, no project: `cad run model.py --render iso,front --export step --out out/`.

### Verify before you finish

Renders show shape; numbers prove it. Match each kind of requirement to a check:

| requirement | check |
|---|---|
| sizes, positions | `cad inspect`, `cad measure --bbox` (no part name: every part), `cad query "faces().facing('+z')"` |
| holes (diameter, position, depth) | `cad measure --holes` |
| minimum wall thickness | `cad measure <part> --thickness` (holes near edges leave thin ligaments) |
| clearance to other parts / a component envelope | model the component as `Part(..., reference=True)`, then `cad clearance --min D` |
| moving parts | a motion `Parameter`, then `cad sweep PARAM START:STOP:STEP --min D --render front` |
| hidden internals (cavities, pockets, bores) | `cad render --views front,iso_bottom --section y=0` |

`cad build` in a directory with `model.py` but no `cad.toml` creates the project file for you.

### Project files

A project is a directory with `cad.toml` (what `cad init` writes):

```toml
[project]
name = "bracket"          # label for renders/exports (part names come from Part("..."))
entry = "model.py"        # the model script

[render]                  # optional defaults for `cad render`
views = ["iso", "front", "right", "top"]
size = [1024, 768]

[export]                  # optional defaults for `cad export`
formats = ["step", "stl"]
threemf_mode = "objects"  # or "multimaterial" (see Materials and 3D printing)
```

`params.toml` holds parameter overrides written by `cad set` (commit it with the
script). `.cad/` (revisions, caches) and `renders/`, `out/` are generated.
`cad open model.py` turns a lone script's directory into a project.

## Script contract

```python
from cad import Part, Profile, Plane, Parameter

width = Parameter("width", 60, min=20, max=200)   # returns a plain number

def build():                     # return a Part, a list of Parts or {name: Part}
    p = Part("bracket")
    p.box(width, 40, 4, name="base")
    p.assert_valid()
    return p
```

Without `build()`, every module-level `Part` with geometry is collected.
`print()` output is captured and shown by `cad build`. Plain `python model.py`
also works (parameters take their defaults).

## Part — creating bodies

Every body operation takes `op="add" | "cut" | "intersect"` (default `"add"`)
and `name=`. The first body must use `"add"`. All return a `FeatureRef`.
`box` and `cylinder` accept a **list of points** for `at` to place many identical
instances in one feature and one Boolean — use it for repeated bosses, pins and ribs
(1000 bosses: ~1 s, versus minutes one call at a time).

| call | notes / named faces |
|---|---|
| `box(width, depth, height, at=(0,0,0), align=("center","center","min"))` | `align` per axis says where `at` sits on the box: `"min"`, `"center"`, `"max"`. Default: centred in X/Y, bottom at `at.z`. Faces: `.top .bottom .front .back .left .right` |
| `cylinder(diameter, height, at=(0,0,0), axis="z", align="min")` | `align` along the axis. Faces: `.side .start .end` (+ `.top/.bottom`… when axis-aligned) |
| `sphere(diameter, at=(0,0,0))` | `.surface` |
| `extrude(profile, distance, plane="XY", offset=0, symmetric=False, through=False)` | See *Sketch planes and extrusion* below. Faces: `.start .end .side` (+ direction names) |
| `revolve(profile, angle=360, plane="XZ", axis="v")` | Revolves about the plane's v axis (for `XZ`: world Z). Draw the half-profile at u ≥ 0. |
| `union(other_part)`, `cut(other_part)`, `intersect(other_part)` | Boolean with another Part |

### Sketch planes and extrusion

| plane | profile u → | profile v → | normal (extrude direction) | `offset=d` puts the sketch at |
|---|---|---|---|---|
| `"XY"` | +X | +Y | +Z | Z = d |
| `"XZ"` | +X | +Z | **−Y** | Y = −d |
| `"YZ"` | +Y | +Z | +X | X = d |

- The profile is drawn in (u, v) on the plane, then swept `distance` along the normal.
  Negative `distance` sweeps the other way (`"XZ"` with `-5` goes toward +Y).
- `symmetric=True` centres the extrusion on the sketch plane (`distance/2` each side).
- `through=True` (with `op="cut"`) makes the cut go through the whole part in both directions; `distance` is ignored.
- Arbitrary planes: `Plane.make(origin, normal, u=None)`, `Plane.named("XY", offset=5)`, `plane.offset(d)`.

```python
# a ramp: side profile drawn in the YZ plane (u = Y, v = Z), extruded 20 mm along X, centred on X = 0
p.extrude(Profile.polygon([(0, 0), (30, 0), (30, 12)]), 20, plane="YZ", symmetric=True)
# a 3 mm thick triangular web whose mid-plane is X = -8
p.extrude(Profile.polygon([(0, 3), (-18, 3), (0, 21)]), 3, plane="YZ", offset=-8, symmetric=True)
# a skirt hanging 2 mm down from a plate whose underside is at Z = 25
cap.extrude(skirt, -2, plane="XY", offset=25)
# slot-shaped through cut-out
p.extrude(Profile.slot(30, 8), 1, op="cut", through=True)
```

## Profiles (2D, in plane coordinates u, v)

`Profile.rect(w, h, center=(0,0))`, `Profile.rect_corners(p1, p2)`,
`Profile.circle(diameter, center)`, `Profile.rounded_rect(w, h, radius, center)`,
`Profile.slot(length, width, center, angle)`, `Profile.polygon([(u,v), ...])`,
`Profile.regular_polygon(sides, diameter=None, center, angle, across_flats=None)` — size by
`diameter` (corner to corner) **or** `across_flats` (wrench size); `angle=0` puts a corner on +u, so a
hexagon's flats are at v = ±across_flats/2.
Combine with `a + b` (union) and `a - b` (subtract); `p.translated((du, dv))`, `p.rotated(deg)`,
`p.offset(d)` (grow by d mm, negative shrinks; holes shrink/grow accordingly), `p.area`.

```python
frame = Profile.rect(50, 35) - Profile.rect(47, 32)              # 1.5 mm perimeter frame
pocket = Profile.rounded_rect(60, 40, 4)
skirt = pocket.offset(-0.3) - pocket.offset(-1.8)                 # 0.3 mm clearance, 1.5 mm thick
```

```python
# L-shaped rib in the XZ plane, 3 mm thick, centred on Y=0
rib = Profile.polygon([(0, 0), (20, 0), (0, 20)])
p.extrude(rib, 3, plane="XZ", symmetric=True)
```

## Holes

```python
p.hole(diameter, at, depth=None, direction="-z", counterbore=None, countersink=None)
p.holes(diameter, positions=[...], ...)                          # same rules, many positions
p.hole_pattern(diameter, spacing=(sx, sy), count=(nx, ny), center=(0, 0), ...)
p.bolt_circle(diameter, circle_diameter=40, count=6, center=(0, 0), start_angle=0, ...)
```

- `direction` is the drilling direction: `"-z"` (default, drilled down from the top),
  `"+x"`, … **or any vector** such as `(-0.5, 0, -0.866)` for angled holes.
- `at` is either a **3D start point** (the hole starts exactly there — use it for angled holes or to
  start inside/above the part), or a **2D point** in the two axes perpendicular to an axis-aligned
  direction; the hole then starts where the drilling line **first enters the material** (e.g. the
  plate top, not a taller boss elsewhere):

  | direction | 2D `at` means | drilled from |
  |---|---|---|
  | `-z` / `+z` | (x, y) | above, downward / below, upward |
  | `-y` / `+y` | (x, z) | the back (+Y side) / the front (−Y side) |
  | `-x` / `+x` | (y, z) | the right (+X side) / the left (−X side) |

- `depth` is measured from the start point along the direction; `None` drills through everything
  ahead of the start point. Drilling away from the part raises `HOLE_MISSED` naming the direction to use.
- `counterbore=(diameter, depth)`, `countersink=(diameter, angle=90)` are added at the start.
- `hole_pattern` centres the grid on `center` (absolute coordinates in the plane perpendicular to
  the direction): `spacing=(48, 28), count=(2, 2)` → holes at (±24, ±14); `count=(nx, ny)` is
  (columns along the first axis, rows along the second).
- Faces: `<id>.wall` (all), `<id>.wall.<i>` (per hole), `.floor` (blind), `.counterbore`, `.countersink`.
- A hole that misses the part produces a `CUT_NO_EFFECT` / `HOLE_MISSED` warning.

```python
r.hole(6, at=(0, 0, 0), depth=12, direction="+z")              # bore up from the bottom face of a round bar
r.hole(3, at=(0, -9, 6), depth=9, direction="+y")              # radial: from the -Y surface (Ø18 bar) to the axis
t.holes(2, [(18, 0, 5), (-18, 0, 5)], depth=3)                 # blind holes from boss tops at Z = 5
import math                                                    # angled: axis through (0,5,4), 20° from vertical,
a = math.radians(20)                                           # leaning toward -Y as it rises; top face at Z = 18
L = (18 - 4) / math.cos(a)
k.hole(5, at=(0, 5 - L * math.sin(a), 18), direction=(0, math.sin(a), -math.cos(a)), depth=L)
```

## Dress-up

```python
p.fillet(edges, radius)            # edges: an EdgeSelection
p.chamfer(edges, distance)
p.shell(thickness, open_faces=p.faces("body.top"))   # hollow inward, leave faces open
```

Fillet failures raise `FILLET_FAILED` with the failing edges and a hint (radius too
large, or edges that interfere; fillet them in separate calls). Do **shell before
small fillets**. Fillet faces are named `<id>.faces`.

## Transforms

`p.translate((dx, dy, dz))`, `p.rotate(angle, axis="z", center=(0,0,0))` (right-hand rule:
positive angles turn counter-clockwise when looking from +axis toward the origin; `rotate(30, axis="y")`
tilts +Z toward +X, `rotate(90, axis="z")` turns +X into +Y),
`p.mirror("YZ", keep_original=True)` (mirror and fuse), `p.copy(name)`.

## Selecting faces and edges

```python
p.faces()                    # all faces          p.faces("base.top")  # a named reference
p.faces("hole1")             # a feature id selects every face that feature created
p.edges()                    # all edges          p.edges("base.top")  # edges of named faces
```

Filters (chainable; each returns a new selection):

| faces | edges | both |
|---|---|---|
| `.planar()` `.cylindrical()` `.of_type("cone")` | `.linear()` `.circular(radius=None)` | `.max("z")` `.min("x")` — extreme centroid along an axis |
| `.facing("+z")` — planar, outward normal along a direction | `.vertical()` (∥Z) `.horizontal()` (in planes ⟂Z) | `.at("z", 4)` `.between("x", -5, 5)` |
| `.holes(diameter=None)` — hole walls (concave, ≥180°) | `.parallel_to("x")` `.perpendicular_to("z")` | `.nearest((x, y, z), count=1)` |
| `.larger_than(a)` `.smaller_than(a)` `.largest()` | `.convex()` outside corners, `.concave()` inside corners | `.named(name)` `.created_by("hole1")` |
| `.edges()` — edges bounding these faces | `.of(face_selection)` `.longer_than(l)` `.shorter_than(l)` | `.exclude(sel)`, `a | b`, `a - b`, `.where(lambda info: ...)` |

Checks: `.one()` (exactly one, else `AMBIGUOUS_SELECTION`/`EMPTY_SELECTION` listing
candidates), `.expect(n)`, `len(sel)`, `.info()` (list of dicts: type, area/length,
centroid/midpoint, normal, radius, names…).

Name things you will need later: `p.tag("mounting_surface", p.faces().facing("-z"))`
then `p.faces("mounting_surface")`. A `FeatureRef` gives `ref.faces()`, `ref.faces("wall")`,
`ref.edges()`, `ref.refs`, `ref.warnings`.

Selections capture the geometry at the moment they are made: re-select after
modifying the part (stale selections raise an error).

## Queries and validation

```python
p.bbox             # BBox: .min .max .size .width .depth .height .center
p.volume           # mm³            p.area  # mm²
p.center_of_mass   # (x, y, z)      p.solid_count
p.mass(1.24)       # grams for density g/cm³ (PLA 1.24, PETG 1.27, ABS 1.04, Al 2.70)
p.find_holes()     # [{diameter, axis, position, depth, names}] found in the actual geometry
p.is_valid()       # BRep validity
p.assert_valid(solids=1)          # raises VALIDATION_FAILED with problems listed
p.wall_thickness()                # {"min", "p2", "thinnest": [{thickness, at, measured_along, faces}]}
p.assert_min_thickness(3)         # raises VALIDATION_FAILED with the thinnest locations
p.distance_to(other)              # min distance (0 if touching/overlapping)
p.interference(other)             # shared volume (0 = no collision)
p.faces("lip").distance_to(box.faces("shell1.inner"))   # gap between selections (or a Part)
p.warnings                        # non-fatal diagnostics from all features
p.feature_graph()                 # features, params, dependencies, references
p.references()                    # named references and their status
p.export("out/part.step")         # .step/.stp, .stl, .brep
from cad import approx; approx(a, b, tol=1e-6)
```

`depth` in `find_holes()` is the axial extent of the hole wall, so a hole entering a slanted
surface reports its longest side. `find_holes()[i]["position"]` is the centre of the hole's end with the lowest coordinate along
its (positive) axis — for a vertical through hole in a plate on Z=0 that is (x, y, 0).

## CLI reference

| command | purpose |
|---|---|
| `cad init [dir] [--example NAME]` | new project (cad.toml, model.py, .gitignore); becomes the current project |
| `cad open <dir or file.py>` | make a project current (commands work from any directory afterwards) |
| `cad build [-p name=value] [--force]` | build → revision N (identical inputs reuse an existing revision) |
| `cad inspect [part] [--features] [--refs] [-r REV]` | summary, holes, features, warnings |
| `cad measure [part[.ref]] [--volume --area --bbox --com --holes --thickness] [--distance OTHER] [--density D]` | numbers, or the faces of a reference (e.g. `bracket.base.top`); `--distance` accepts parts or references on both sides, e.g. `cad measure lid.lip --distance box.shell1.inner` |
| `cad query [part] "<expr>"` | evaluate a selection, e.g. `cad query "edges().vertical().convex()"` |
| `cad render [--views ...] [--section y=0] [--part P] [--size WxH] [--style shaded_edges|shaded|lines] [-r REV]` | PNG + JSON metadata per view, plus a contact sheet; `--section` cuts away the half facing the camera (`x=5:+` keeps the +X side) |
| `cad export [--format step,stl,3mf,brep] [--3mf-mode objects|multimaterial] [--part P] [--out DIR] [--tolerance 0.01]` | manufacturing files; 3MF carries materials; STL reports watertightness |
| `cad materials` | built-in materials (density, colour) |
| `cad fonts [filter]` | installed fonts for text |
| `cad measure <part> --section z=V` | cross-section outline at a plane (regions, rectangles, circles, holes) |
| `cad fasteners` | M2-M8 screw, nut and heat-set insert dimensions (screw_hole table) |
| `cad joints` | an Assembly's joints: world axes, values, limits, what positive motion does |
| `cad info <file>` | bodies, names, sizes, units in a STEP / IGES / STL / BREP file |
| `cad slice` | Bambu Studio slice: print time, grams per filament, supports, warnings, .gcode.3mf |
| `cad params` / `cad set NAME VALUE` / `cad unset NAME` | parameter overlay (params.toml) |
| `cad clearance [--min D] [--part P]` | gaps / contact / overlap for every pair of parts; per-face gaps for reference envelopes; exit 4 below `--min` |
| `cad sweep PARAM START:STOP:STEP [--min D] [--render VIEWS]` | rebuild across a parameter range, check clearances and optionally render each value |
| `cad revisions` / `cad diff [A] [B]` / `cad checkout REV` / `cad restore REV --force` | history; checkout never edits sources, restore does |
| `cad status`, `cad daemon status|stop|restart` | session / daemon state |
| `cad capabilities`, `cad help CMD --json`, `cad schema [name]`, `cad examples list|show|copy`, `cad docs` | discovery |

Revision selectors: a number, `head`, or `-1` (previous), `-2`, …

Views: `iso front back left right top bottom iso_back iso_left iso_bottom all`,
`az=<deg>,el=<deg>` (azimuth from front toward right, elevation above horizon),
`dir=x,y,z[,up=x,y,z]` (direction from the model toward the camera).
Every PNG has a sidecar JSON with the camera vectors, `mm_per_pixel`, and the
model bbox; images are annotated with the view, screen axes, an axis triad and a scale bar.

## Text: engrave and emboss

```python
p = Part("plate"); p.box(80, 36, 5, name="body")
p.engrave("SN 0042", on=p.faces("body.top"), size=7, depth=0.8, at=(0, 4), bold=True)   # cut in
p.emboss("MADE WITH CAD", on=p.faces("body.top"), size=3.2, height=0.5, at=(0, -8))    # raised
p.engrave("FRONT", on=p.faces("body.front"), size=2.6, depth=0.4)                      # any flat face
```

- `size` = height of capital letters in mm; `depth` / `height` = how deep / how proud.
- `on` = one flat face (a face split by earlier text is fine: coplanar faces are treated as one) or a `Plane`.
  Text reads normally when you look at that face from outside, upright on vertical faces
  (`up=(x, y, z)` changes "up"); `at=(u, v)` moves it from the face centre (u = reading direction), or
  pass a 3D point; `angle=` rotates it. By default the text's bounding box is **centred on `at`**;
  `align=("left"|"center"|"right", "baseline"|"bottom"|"center"|"top")` anchors it differently.
- Check where text landed: `cad measure plate.engrave1.floor --bbox` (engraved letter bottoms) or
  `plate.emboss1.end` (raised letter tops); `cad inspect --features` shows each text feature's width,
  height, font and estimated stroke width.
- `font=` an installed font name (`cad fonts`, `cad fonts helv`) or a .ttf/.otf path; default Helvetica,
  else Arial / DejaVu Sans; `bold=True`, `italic=True`. Unknown fonts are an error (never substituted).
- Warnings: `TEXT_OFF_FACE` (text runs past the face edge), `TEXT_STROKES_THIN` (strokes under ~0.4 mm:
  too fine for FDM; increase size or use bold). Named faces: `<id>.end` (raised tops), `<id>.floor` (engraved bottoms).
- As a 2D profile: `Profile.text("A1", 8)` for `extrude(..., op="cut")`, or a separate part in another
  material for a two-colour print: `label.extrude(Profile.text("PLA", 8), 0.6, plane=Plane.from_face(base.faces("body.top")))`.
- Flat faces only: text does not wrap around curved surfaces.

## Materials and 3D printing (3MF)

```python
from cad import Part, Material

housing = Part("housing", material="PETG")          # built-in: PLA PETG ABS ASA TPU PA12 PC Resin Aluminium Steel Brass
gasket  = Part("gasket",  material="TPU")
badge   = Part("badge",   material=Material("PLA", color="#e8a050"))     # built-in density, own colour
insert  = Part("insert",  material=Material("CF-PA", density=1.15, color="#333333"))  # custom
housing.mass()                                      # grams, from the material density
```

- One material per part. A multi-material print is several parts in their assembled positions
  (a TPU seal sitting in a PETG groove, a coloured inlay in a recess); make them touch, not overlap.
- Renders use the material colour unless the part sets `color=`. `cad inspect` shows material and mass.
- `cad materials` lists the library (density, colour, notes).

```bash
cad export --format 3mf --3mf-mode multimaterial # ONE print, several filaments: parts touching in place (inlay, seal, two-tone)
cad export --format 3mf                          # separate prints: every part its own object (box + lid, spare parts)
cad export --format stl                          # one STL per part, with a watertightness check
```

Which mode: parts that are printed together as one piece in different materials → `multimaterial`
(the slicer gets one object whose parts are on filaments 1, 2, …). Parts printed as separate
pieces → `objects`. Set a default in cad.toml: `[export]` `threemf_mode = "multimaterial"`. Check that
parts touch without overlapping with `cad clearance` (every pair: clear / touching / overlap).

The 3MF file holds all parts (reference parts excluded): mesh units mm, closed oriented meshes, each
part's colour in a 3MF colour group (how Bambu Studio picks filaments) and its material name as
`cad:material` metadata. Material slot k is filament k+1, in first-use order. `multimaterial` mode
writes one assembly object plus Bambu Studio's per-part settings (name + filament). Verified with
Bambu Studio 2.07: objects mode loads as separate objects on filaments 1..n; multimaterial mode as one
object with one part per material. Set the matching filament types/colours in the slicer.
Overlapping parts are reported (`MATERIAL_OVERLAP`) because two materials would claim the same volume.
In Python: `part.export("x.3mf")`, or `from cad.threemf import export_3mf; export_3mf({"a": a, "b": b}, "x.3mf", mode="multimaterial")`.

## Designing for 3D printing: screws, inserts, nuts, snap fits, threads

```python
p.screw_hole("M3", at=(20, 10), kind="counterbore")            # socket head sits below the surface
p.screw_hole("M3", at=[(-20, 10), (20, 10)], kind="insert")    # heat-set insert pockets (4.0 x 6.2 mm, lead-in)
p.screw_hole("M4", at=(0, 0), kind="nut")                      # clearance hole + hex nut pocket at the far side
p.bottom_chamfer(0.5)                                          # against elephant's foot (outline + holes on the bed)
lid.snap_hook(on=lid.faces("plate.front"), length=8, thickness=1.4, width=6, catch=0.8, hook="+z")
bolt.thread("M8", length=16, at=(0, 0, 6))                     # external thread, axis along +Z
nut.threaded_hole("M8", at=(0, 0))                             # internal thread, 0.3 mm radial clearance
```

- `screw_hole(size, at, kind=)`: sizes M2-M8 from the built-in table (`cad fasteners`); kinds `clearance`
  (ISO 273 medium), `counterbore`, `countersunk` (90 degrees, flush), `tap` (pilot hole a screw cuts its thread
  into), `insert` (heat-set insert pocket: blind, insert length + 0.5 mm), `nut` (hex pocket where the hole
  leaves the material). Metrics (`cad inspect --features`) give every dimension used, the material thickness
  and, for nuts, a standard screw length that fits. `INSERT_TOO_DEEP` when the material is too thin.
- Where things go: a 2D `at` starts at the first material along the drill direction (default -Z, from above),
  wherever the part sits, so `at=(18, 0)` on a part spanning Z 15..30 starts at Z = 30. Recesses (counterbore,
  countersink, insert lead-in) are at that entry; the `nut` pocket is at the far end, where the hole leaves the
  material (drill down from the top -> pocket in the underside). `cad inspect` lists the round holes; check
  pockets with `cad measure <part> --section z=<height>` (hex shows as a 6-edge hole loop) or `inspect --features`.
- Inserts need >= 1.5 mm of wall around the pocket (check with `cad measure <part> --thickness`); bosses
  for M3 inserts are typically 7-8 mm in diameter.
- `bottom_chamfer(size=0.5, holes=True)`: chamfers the edges of the bed face: the lowest flat face, or the face
  given to `print_on()` if you called it first (a lid printed upside down gets its top chamfered).
- `snap_hook(on=, length=, thickness=, width=, catch=, hook=, at=)`: a cantilever growing out of a flat face
  along its normal, hook pointing `hook` (a direction in the face). Metrics: peak strain (1.5 t y / L^2) against
  the material's allowable strain (PLA 2 %, PETG 3.5 %, ABS 2.5 %, PC 4 %, PA12 6 %), deflection force, and
  `catch_face_at` (where the mating ledge must be). `SNAP_STRAIN_HIGH` gives the minimum length that works;
  `SNAP_LAYER_ORIENTATION` warns when the beam stands upright (printed that way it snaps along its layers).
  Named faces: `<id>.catch` (the holding face), `<id>.lead_in`, `<id>.beam`. Make the mating window/ledge yourself
  at the catch position, `catch` mm deep, a little wider than the hook.
- `thread(size, length=, at=, direction=)` / `threaded_hole(size, at, depth=, clearance=0.3)`: helical ISO
  metric threads ("M8", "M8x1", "M40x3"). Print with the axis vertical (`THREAD_ORIENTATION` otherwise); below
  M6 printed threads are weak (`THREAD_TOO_FINE`): use `screw_hole(kind="insert")` or `kind="tap"`. Each thread
  takes a few seconds to build. A modelled bolt and nut only mesh at the right rotation, so `cad clearance`
  between them may report contact: that is expected.

## Importing STEP / STL files (vendor parts)

```bash
cad info vendor/servo.step     # bodies, assembly paths, sizes, positions, units -- before writing code
```

```python
servo = Part.from_file("vendor/servo.step", "servo", reference=True)       # design around it, never exported
case = Part.from_file("vendor/servo.step", solid="case", align=("center", "center", "min"))
p.import_file("vendor/pcb.step", op="cut", at=(0, 0, 2))                    # use a file as a cutter
b = Part.from_file("old_bracket.stl"); b.hole(5, at=(0, 2))                 # an STL becomes an editable solid
```

- Formats: STEP (.step/.stp) and IGES with body names and colours; BREP; STL (sewn into a solid, coplanar
  triangles merged; up to 100k triangles, `max_triangles=` to raise it).
- Units: STEP/IGES are converted to mm from the file's units (`cad info` shows them); STL/BREP have no units
  and are read as mm: `scale=25.4` for an inch STL.
- Placement: the file's coordinates are kept unless you pass `align=` (per axis "min" | "center" | "max",
  bounding box onto the origin) and/or `at=` (an offset). To design around a component keep it where it is
  and measure it: `cad info`, `cad measure servo --bbox --holes`, `part.find_holes()`, and its outline at a
  height with `cad measure servo --section z=-8` (each region's extents, rectangle / circle outlines, holes).
- `solid=` picks bodies by name (exact, else substring), index, or a list. Several bodies in one part stay
  separate solids. Named faces: `import1.top` / `.bottom` / `.front` ... and `import1.<body name>`.
- Paths are relative to the project directory; imported files count as sources, so editing one triggers a
  rebuild, and revisions keep a copy (stored once however many revisions use it).

## Slicing: print time and filament (Bambu Studio)

```bash
cad slice                                    # A1, 0.4 mm nozzle, the printer's standard process, textured PEI plate
cad slice --printer "P1S" --process "0.16mm Optimal" --supports auto
cad slice --filament PLA="Bambu PLA Matte" --set sparse_infill_density=25% --set wall_loops=3
cad slice --list printers | processes | filaments
```

- One combined estimate for everything sliced together (all parts on one plate); for per-part numbers slice
  them one at a time: `cad slice clamp_top`.
- Reports print time, grams and metres per filament (one per material; multi-material via `--3mf-mode
  multimaterial`), layers, whether supports were used, time by feature, and writes `out/r<N>/<name>.gcode.3mf`
  (open it in Bambu Studio or send it to the printer). Results are cached per revision and settings.
- Materials map to Bambu filament presets (PLA -> Bambu PLA Basic, PETG -> Bambu PETG Basic, TPU -> Bambu TPU 95A,
  ABS, ASA, PC, PA12 -> Generic PA); others slice as PLA with a `FILAMENT_ASSUMED` warning. Metals and resin are refused.
- Warnings: `NEEDS_SUPPORT` (overhangs would print in mid-air: re-orient, or `--supports auto`), `OFF_PLATE`,
  `SLICER_WARNING`. A model too big for the printer fails before slicing with its size and the plate's.
- `--plate textured | cool | engineering | high-temp`; Bambu refuses filaments a plate is not rated for (PETG on cool).
- The part is printed as modelled (Z up, lowest face on the bed) unless you say otherwise:
  `lid.print_on(lid.faces("plate.top"))` (or `print_on("+z")`) keeps the assembled model but turns the part so
  that face is on the bed for `cad slice` and STL / 3MF export (STEP keeps the design pose). Multi-material
  parts print as one object and turn together. `NEEDS_SUPPORT` on a part modelled in assembly pose usually
  means it needs `print_on`.
- Defaults in cad.toml: `[print]` `printer = "A1 mini"`, `process`, `supports`, `plate`, `slicer = "/path/to/BambuStudio"`;
  `[print.filaments]` `PLA = "Bambu PLA Matte"`; `[print.settings]` `wall_loops = 3`.
- Bambu Studio is found via cad.toml `slicer`, `$CAD_BAMBU_STUDIO`, `bambu-studio` on PATH, then the usual
  install locations.

## Assemblies, motion and designing around components

### Joints (moving parts)

Model every part in place, in its rest pose. Then connect parts with joints; a joint's value turns or moves
the child, and everything hanging below it, away from that rest pose (value 0 = as modelled).

```python
from cad import Assembly, Parameter, Part

Parameter("hip_angle", 0, min=-30, max=60, unit="deg")     # declare, then refer to it by name
Parameter("knee_angle", 0, min=0, max=90, unit="deg")

def build():
    base, upper, lower = make_base(), make_upper(), make_lower()   # modelled in place (rest pose)
    asm = Assembly("leg")
    asm.add(base, upper, lower)                            # the first part added is fixed to the world
    asm.revolute("hip", base, upper, axis=base.faces("hip.wall"), angle="hip_angle")
    asm.revolute("knee", upper, lower, axis=upper.faces("knee.wall"), angle="knee_angle")
    return asm                                             # instead of a dict of parts
```

- `revolute(name, parent, child, axis=, angle=)` (degrees), `slider(..., axis=, distance=)` (mm),
  `cylindrical(..., angle=, distance=)` (a pin that turns and slides), `fixed(name, parent, child)` (follows its parent).
- `axis=`: a hole or boss wall (`part.faces("hinge.wall")` for a `hole(..., name="hinge")`; a hole cut with
  `cylinder(..., op="cut", name="hinge")` is `part.faces("hinge.side")`), a circular or straight edge, a flat face
  (its normal, for sliders), or `((x, y, z), (dx, dy, dz))`. Give it in the parent's rest pose: the knee axis is
  where the knee hole is when everything is at 0; moving the hip carries it along.
- Direction: from geometry the axis points along the positive world axis it is closest to (+X, +Y or +Z);
  `direction="-y"` reverses it. Positive angles turn right-handed about the axis direction. `cad joints`
  prints, for each joint, the world axis and in words what a positive value does ("its far end moves -X"):
  read it after the first build and add `direction=` to any joint that moves the wrong way.
  `cad render --views front --joints` draws the axes with their positive sense.
- Values: a number, or the name of a declared Parameter (the joint takes its limits). Then
  `cad set knee 45` (joint name or parameter name) poses it and `cad sweep knee 0:90:15 --min 0.5` checks
  clearances through the motion (negative ranges work: `cad sweep shoulder -45:45:15`). `cad set` saves the pose
  in params.toml; `cad unset --all` returns every joint to the rest pose (sweeps restore it themselves). `limits=(lo, hi)` for numbers; out-of-range values fail with `JOINT_LIMIT`.
- Each part has one parent joint (a tree from the fixed part); closed loops such as four-bar linkages are not
  supported: drive one link and check the closing joint with `cad clearance`. `JOINT_AXIS_OFF_GEOMETRY` warns
  when a revolute axis does not pass through a hole or boss of both parts.
- Layer moving parts along the joint axis with a gap (links at different Y), as for any parts that slide past each other.

### Parts without joints

A script may also return several parts (`return {"base": base, "arm": arm}`); each is a separate
printable body, positioned in one shared assembly frame. Common patterns:

```python
from cad import Parameter, Part

angle = Parameter("hinge_angle", 0, min=0, max=135, unit="deg")

def build():
    # a component you design around: rendered and measured, never exported
    motor = Part("motor", reference=True)
    motor.cylinder(28, 40, at=(0, 0, 6))

    frame = Part("frame")
    frame.box(50, 50, 6)
    frame.hole(9, at=(0, 0))                       # shaft clearance

    flap = Part("flap")
    flap.box(40, 4, 30, at=(0, 30, 6), align=("center", "min", "min"))
    flap.rotate(angle, axis="x", center=(0, 30, 6))  # a motion parameter drives the pose
    return {"motor": motor, "frame": frame, "flap": flap}
```

- **Rotation sense** (right-hand rule, positive = counter-clockwise looking from +axis toward the
  origin): about `y`, +Z turns toward +X; about `z`, +X turns toward +Y; about `x`, +Y turns toward +Z.
  To swing something toward the opposite side, use a negative angle.
- **Layering along an axis:** keep moving parts in separate slabs (e.g. links at different Y or Z)
  with the required gap between slabs. On the `"XZ"` plane (u = X, v = Z) `offset=d` places the sketch at
  Y = −d and positive distances extrude toward −Y, so a slab from Y = y0 to Y = y0 + t is
  `extrude(profile, -t, plane="XZ", offset=-y0)`.
- **Check it:**

```bash
cad clearance --min 0.5                 # every pair of parts: clear / touching / overlap, closest points;
                                        # for reference parts, the gap in front of each of its faces
cad clearance --min 0.5 --allow-contact # touching is fine (a part resting on its support), overlap is not
cad sweep hinge_angle 0:135:15 --min 0.5 --render front    # rebuild at each value, report collisions,
                                        # render each pose; the active revision is restored afterwards
cad measure frame --thickness           # thinnest walls with locations (holes near edges, thin floors)
```

In Python: `part.wall_thickness()`, `part.assert_min_thickness(3)`, `part.distance_to(other)`,
`part.interference(other)`. `cad export` skips reference parts.

## Errors

Errors carry `code`, `message`, `hint`, `feature` and `details` (with
`details.location` = script file/line for errors raised from your script). Common
codes: `INVALID_ARGUMENT`, `NO_BODY`, `EMPTY_SELECTION`, `AMBIGUOUS_SELECTION`,
`UNKNOWN_REFERENCE`, `REFERENCE_LOST`, `BOOLEAN_FAILED`, `FILLET_FAILED`,
`CHAMFER_FAILED`, `SHELL_FAILED`, `INVALID_SHAPE`, `VALIDATION_FAILED`,
`SCRIPT_ERROR`, `NO_MODEL`, `UNKNOWN_PARAMETER`, `PARAMETER_OUT_OF_RANGE`.
Warnings: `CUT_NO_EFFECT`, `ADD_NO_EFFECT`, `DISCONNECTED_BODIES`, `BODY_SPLIT` (a cut severed the part), `HOLE_MISSED`, `RECESS_NO_EFFECT` (counterbore/countersink cut nothing).
A failed build never replaces the last good revision.

## Recipes

```python
# plate with rounded corners and a chamfered top edge
p = Part("plate"); p.box(70, 45, 4, name="body")
p.fillet(p.edges().vertical(), 3)
p.chamfer(p.edges("body.top").exclude(p.edges().circular()), 0.5)

# wall on the back edge of a base, inside corner filleted
p.box(60, 40, 4, name="base")
p.box(60, 4, 30, at=(0, 20, 4), align=("center", "max", "min"), name="wall")
p.fillet(p.edges().concave(), 3)

# hole through the wall (drilled toward +Y), 20 mm above the floor
p.hole(5, at=(0, 20), direction="+y")

# open-top box
b = Part("box"); b.extrude(Profile.rounded_rect(90, 60, 5), 35, name="body")
b.shell(2, open_faces=b.faces("body.top"))

# two parts that must not collide
assert lid.interference(box) == 0 and lid.distance_to(box) >= 0.2
```
