"""Printed enclosure: snap-fit lid, heat-set insert bosses for a PCB, countersunk mounting holes.

Demonstrates: screw_hole(kind="insert" / "countersunk"), snap_hook with its strain check and
catch position, matching windows cut from the hook's metrics, bottom_chamfer against
elephant's foot, and parts placed as assembled (the lid closed on the base) with
print_on() giving the lid's print orientation for `cad slice` / STL / 3MF.
"""
from cad import Parameter, Part

W, D, H, wall = 60, 40, 25, 2.0
hook_len = Parameter("hook_length", 11.0, min=5, max=15)


def build():
    base = Part("base", material="PETG")
    base.box(W, D, H, name="body")
    base.shell(wall, open_faces=base.faces("body.top"))
    base.fillet(base.edges().vertical().convex(), 3)
    base.box(W - 2 * wall, D - 2 * wall, 1.5, at=(0, 0, wall), name="floor_pad")   # 3.5 mm floor for countersinks
    floor = wall + 1.5
    # two bosses with M3 heat-set inserts for a PCB
    base.cylinder(7.5, 6, at=[(-18, 0, floor), (18, 0, floor)], name="boss")
    base.screw_hole("M3", at=[(-18, 0), (18, 0)], kind="insert")
    # countersunk holes to screw the box to a wall, heads flush with the floor inside
    base.screw_hole("M3", at=[(0, 12, floor), (0, -12, floor)], kind="countersunk")
    base.bottom_chamfer(0.4)

    lid = Part("lid", material="PETG")
    lid.box(W, D, 2, at=(0, 0, H), name="plate")
    lid.fillet(lid.edges().vertical(), 3)
    hooks = []
    for side in (+1, -1):
        y = side * (D / 2 - wall - 0.2)          # beam outer face 0.2 mm inside the wall
        h = lid.snap_hook(on=lid.faces("plate.bottom"), at=(0, y, H), hook=(0, side, 0),
                          length=hook_len, thickness=1.4, width=8, catch=0.8)
        hooks.append(h.feature.metrics["snap"])
    # windows in the side walls for the catches: top edge 0.2 mm above each catch face
    for m in hooks:
        cx, cy, cz = m["catch_face_at"]
        side = 1 if cy > 0 else -1
        base.box(9, wall + 2, 3.2, at=(cx, side * (D / 2 - wall / 2), cz + 0.2), align=("center", "center", "max"), op="cut")
    lid.print_on(lid.faces("plate.top"))     # modelled closed; printed upside down, hooks pointing up
    base.assert_valid()
    lid.assert_valid()
    return {"base": base, "lid": lid}
