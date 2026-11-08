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
cad init my_part            # or: cad examples copy mounting_bracket my_part
cd my_part                  # edit model.py
cad build                   # runs model.py -> immutable revision (cached if nothing changed)
cad inspect                 # validity, bbox, volume, holes, features, warnings
cad render                  # PNGs in renders/r<N>/ (+ <name>_sheet.png with all views)
cad render --views az=200,el=25 --part lid   # look again from elsewhere (cheap: meshes are cached)
cad set width 80            # parameter override -> params.toml -> rebuild
cad export --format step,stl
```

Add `--json` to any command for a machine-readable envelope
`{"ok", "command", "result", "warnings", "error"}`. Exit codes: 0 ok,
1 internal, 2 usage / unknown parameter, 3 model error, 4 validation failed,
5 not found, 6 worker crashed, 7 timeout, 8 daemon unavailable.

One-shot, no project: `cad run model.py --render iso,front --export step --out out/`.

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

| call | notes / named faces |
|---|---|
| `box(width, depth, height, at=(0,0,0), align=("center","center","min"))` | `align` per axis says where `at` sits on the box: `"min"`, `"center"`, `"max"`. Default: centred in X/Y, bottom at `at.z`. Faces: `.top .bottom .front .back .left .right` |
| `cylinder(diameter, height, at=(0,0,0), axis="z", align="min")` | `align` along the axis. Faces: `.side .start .end` (+ `.top/.bottom`… when axis-aligned) |
| `sphere(diameter, at=(0,0,0))` | `.surface` |
| `extrude(profile, distance, plane="XY", offset=0, symmetric=False)` | Extrudes along the plane normal; negative distance goes the other way. Faces: `.start .end .side` (+ direction names) |
| `revolve(profile, angle=360, plane="XZ", axis="v")` | Revolves about the plane's v axis (for `XZ`: world Z). Draw the half-profile at u ≥ 0. |
| `union(other_part)`, `cut(other_part)`, `intersect(other_part)` | Boolean with another Part |

Planes: `"XY"` (u=+X, v=+Y, normal +Z), `"XZ"` (u=+X, v=+Z, **normal −Y**),
`"YZ"` (u=+Y, v=+Z, normal +X), or `Plane.make(origin, normal, u=None)`,
`Plane.named("XY", offset=5)`, `plane.offset(d)`.

## Profiles (2D, in plane coordinates u, v)

`Profile.rect(w, h, center=(0,0))`, `Profile.rect_corners(p1, p2)`,
`Profile.circle(diameter, center)`, `Profile.rounded_rect(w, h, radius, center)`,
`Profile.slot(length, width, center, angle)`, `Profile.polygon([(u,v), ...])`,
`Profile.regular_polygon(sides, diameter, center, angle)`.
Combine with `a + b` (union) and `a - b` (subtract); `p.translated((du, dv))`, `p.rotated(deg)`.

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

- `direction` is the drilling direction (default `"-z"`, i.e. drilled down from the top).
- `at` is either a **3D start point**, or a **2D point in the two axes perpendicular
  to the direction**: ±Z → (x, y); ±Y → (x, z); ±X → (y, z). With a 2D point the
  hole starts at the part's bounding-box face it enters.
- `depth=None` drills through everything; otherwise depth from the start point.
- `counterbore=(diameter, depth)`, `countersink=(diameter, angle=90)`.
- `hole_pattern` centres the grid: `spacing=(48, 28), count=(2, 2)` → holes at (±24, ±14).
- Faces: `<id>.wall` (all), `<id>.wall.<i>` (per hole), `.floor` (blind), `.counterbore`, `.countersink`.
- A hole that misses the part produces a `CUT_NO_EFFECT` / `HOLE_MISSED` warning.

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

`p.translate((dx, dy, dz))`, `p.rotate(angle, axis="z", center=(0,0,0))`,
`p.mirror("YZ", keep_original=True)` (mirror and fuse), `p.copy(name)`.

## Selecting faces and edges

```python
p.faces()                    # all faces          p.faces("base.top")  # a named reference
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
p.holes()          # [{diameter, axis, position, depth, names}] found in the actual geometry
p.is_valid()       # BRep validity
p.assert_valid(solids=1)          # raises VALIDATION_FAILED with problems listed
p.distance_to(other)              # min distance (0 if touching/overlapping)
p.interference(other)             # shared volume (0 = no collision)
p.warnings                        # non-fatal diagnostics from all features
p.feature_graph()                 # features, params, dependencies, references
p.references()                    # named references and their status
p.export("out/part.step")         # .step/.stp, .stl, .brep
from cad import approx; approx(a, b, tol=1e-6)
```

`hole["position"]` is the centre of the hole's end with the lowest coordinate along
its (positive) axis — for a vertical through hole in a plate on Z=0 that is (x, y, 0).

## CLI reference

| command | purpose |
|---|---|
| `cad init [dir] [--example NAME]` | new project (cad.toml, model.py, .gitignore); becomes the current project |
| `cad open <dir or file.py>` | make a project current (commands work from any directory afterwards) |
| `cad build [-p name=value] [--force]` | build → revision N (identical inputs reuse an existing revision) |
| `cad inspect [part] [--features] [--refs] [-r REV]` | summary, holes, features, warnings |
| `cad measure [part[.ref]] [--volume --area --bbox --com --holes] [--distance OTHER] [--density D]` | numbers, or the faces of a reference (e.g. `bracket.base.top`) |
| `cad query [part] "<expr>"` | evaluate a selection, e.g. `cad query "edges().vertical().convex()"` |
| `cad render [--views ...] [--part P] [--size WxH] [--style shaded_edges|shaded|lines] [-r REV]` | PNG + JSON metadata per view, plus a contact sheet |
| `cad export [--format step,stl,brep] [--part P] [--out DIR] [--tolerance 0.01]` | manufacturing files |
| `cad params` / `cad set NAME VALUE` / `cad unset NAME` | parameter overlay (params.toml) |
| `cad revisions` / `cad diff [A] [B]` / `cad checkout REV` / `cad restore REV --force` | history; checkout never edits sources, restore does |
| `cad status`, `cad daemon status|stop|restart` | session / daemon state |
| `cad capabilities`, `cad help CMD --json`, `cad schema [name]`, `cad examples list|show|copy`, `cad docs` | discovery |

Revision selectors: a number, `head`, or `-1` (previous), `-2`, …

Views: `iso front back left right top bottom iso_back iso_left iso_bottom all`,
`az=<deg>,el=<deg>` (azimuth from front toward right, elevation above horizon),
`dir=x,y,z[,up=x,y,z]` (direction from the model toward the camera).
Every PNG has a sidecar JSON with the camera vectors, `mm_per_pixel`, and the
model bbox; images are annotated with the view, screen axes, an axis triad and a scale bar.

## Errors

Errors carry `code`, `message`, `hint`, `feature` and `details` (with
`details.location` = script file/line for errors raised from your script). Common
codes: `INVALID_ARGUMENT`, `NO_BODY`, `EMPTY_SELECTION`, `AMBIGUOUS_SELECTION`,
`UNKNOWN_REFERENCE`, `REFERENCE_LOST`, `BOOLEAN_FAILED`, `FILLET_FAILED`,
`CHAMFER_FAILED`, `SHELL_FAILED`, `INVALID_SHAPE`, `VALIDATION_FAILED`,
`SCRIPT_ERROR`, `NO_MODEL`, `UNKNOWN_PARAMETER`, `PARAMETER_OUT_OF_RANGE`.
Warnings: `CUT_NO_EFFECT`, `ADD_NO_EFFECT`, `DISCONNECTED_BODIES`, `HOLE_MISSED`.
A failed build never replaces the last good revision.

## Recipes

```python
# plate with rounded corners and a chamfered top edge
p = Part("plate"); p.box(80, 50, 5, name="body")
p.fillet(p.edges().vertical(), 4)
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
