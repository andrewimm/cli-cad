"""Electronics enclosure: shelled box with a separate lid that has a locating lip.

Demonstrates: multiple parts returned as a dict, shell with open faces,
Profile-based extrusion, counterbored holes, interference checks.
"""
from cad import Parameter, Part, Profile

L = Parameter("length", 90, min=30, max=300)
W = Parameter("width", 60, min=30, max=300)
H = Parameter("height", 35, min=10, max=200)
wall = Parameter("wall", 2.0, min=1.0, max=6.0)
clearance = Parameter("lid_clearance", 0.3, min=0.0, max=1.0)


def build():
    box = Part("box")
    box.extrude(Profile.rounded_rect(L, W, 5), H, name="body")
    box.shell(wall, open_faces=box.faces("body.top"))
    # four screw bosses' holes in the floor (counterbored from below)
    box.hole_pattern(3.0, spacing=(L - 20, W - 20), count=(2, 2), direction="+z",
                     counterbore=(6.0, 1.5), name="floor_screws")
    box.assert_valid()

    lid = Part("lid", color="#e8a050")
    lid.extrude(Profile.rounded_rect(L, W, 5), wall, plane="XY", offset=H + 1.0, name="plate")
    lip_l, lip_w = L - 2 * wall - 2 * clearance, W - 2 * wall - 2 * clearance
    lip = Profile.rounded_rect(lip_l, lip_w, max(5 - wall, 0.5)) - Profile.rounded_rect(lip_l - 2 * wall, lip_w - 2 * wall, 1)
    lid.extrude(lip, -4, plane="XY", offset=H + 1.0, name="lip")
    lid.assert_valid()

    # lid sits 1 mm above the box rim in this exploded layout; the lip must not collide with the walls
    assert lid.interference(box) == 0
    return {"box": box, "lid": lid}
