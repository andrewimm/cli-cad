"""A printable bottle and its screw cap.

Demonstrates: loft (rounded-rectangle base blending into a round neck), shell with an
open neck, an external printed thread on the neck with a bore through it, and a cap with
the matching internal thread (threaded_hole), modelled beside the bottle.
"""
from cad import Parameter, Part, Profile

H = Parameter("height", 90.0, min=50, max=150)
WALL = 1.6
NECK = "M28x3"          # coarse printable thread


def build():
    top = H - 8                                                     # where the shoulder ends and the neck starts
    bottle = Part("bottle", material="PETG")
    # one two-section loft: a flask from a rounded rectangle to the round neck.  (A smooth loft through 3+
    # sections can bulge past them, and a loft fused onto an extrusion often will not shell.)
    bottle.loft([(Profile.rounded_rect(60, 40, 12), 0), (Profile.circle(30), top)], name="body")
    bottle.shell(WALL, open_faces=bottle.faces("body.end"))
    bottle.cylinder(30, 2, at=(0, 0, top - 1))                      # collar fusing the rim to the neck
    bottle.thread(NECK, length=14, at=(0, 0, top))
    bottle.hole(21, at=(0, 0, top + 14), depth=16)                  # bore: 1.6 mm wall inside the thread root
    bottle.bottom_chamfer(0.4)

    cap = Part("cap", material="PLA")
    cap.cylinder(36, 16, at=(60, 0, 0), name="shell")
    cap.threaded_hole(NECK, at=(60, 0, 0), direction="+z", depth=13)  # from the open bottom face
    return {"bottle": bottle, "cap": cap}
