"""L-shaped mounting bracket with a base hole pattern, a wall hole and fillets.

Demonstrates: Parameter, box with align, hole_pattern, hole in a side wall,
concave/convex edge selection, named references and assertions.
"""
from cad import Parameter, Part

width = Parameter("width", 60, min=20, max=200, description="bracket length along X")
base_depth = Parameter("base_depth", 40, min=15, max=150)
wall_height = Parameter("wall_height", 30, min=10, max=150)
thickness = Parameter("thickness", 4, min=2, max=20)
hole_d = Parameter("hole_diameter", 3.2, min=1, max=12)


def build():
    part = Part("bracket")
    # base plate: centred in X/Y, bottom on Z=0
    part.box(width, base_depth, thickness, name="base")
    # upright wall flush with the back edge (+Y), sitting on top of the base
    part.box(width, thickness, wall_height, at=(0, base_depth / 2, thickness), align=("center", "max", "min"), name="wall")
    # inside corner fillet between base and wall
    part.fillet(part.edges().concave(), radius=thickness * 0.75, name="root_fillet")
    # mounting holes in the base, kept clear of the wall
    usable = base_depth - thickness
    part.hole_pattern(hole_d, spacing=(width - 12, usable - 12), count=(2, 2),
                      center=(0, -base_depth / 2 + usable / 2), name="base_holes")
    # one hole through the wall, drilled along +Y from the front face of the wall
    part.hole(hole_d * 1.5, at=(0, thickness + wall_height * 0.6), direction="+y", name="wall_hole")
    # round the outside vertical corners at the front of the base
    part.fillet(part.edges().vertical().convex().min("y"), radius=3, name="corner_fillets")
    part.tag("mounting_surface", part.faces().facing("-z"))

    part.assert_valid()
    assert abs(part.bbox.width - width) < 1e-6
    assert abs(part.bbox.height - (thickness + wall_height)) < 1e-6
    assert len(part.find_holes()) == 5
    return part
