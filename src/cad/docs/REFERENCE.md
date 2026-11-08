# cad — API & CLI reference

Agent-first parametric CAD on Open CASCADE. Write a Python script, build it,
check numbers, look at renders, revise, export.

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
| `cad export [--format step,stl,brep] [--part P] [--out DIR] [--tolerance 0.01]` | manufacturing files |
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

## Assemblies, motion and designing around components

A script may return several parts (`return {"base": base, "arm": arm}`); each is a separate
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
cad clearance --min 0.5                 # every pair: clear / touching / overlap, closest points;
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
