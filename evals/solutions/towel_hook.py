from cad import Part, Path, Profile

p = Part("towel_hook", material="PETG")
p.box(40, 5, 60, at=(0, 0, -30), align=("center", "min", "min"), name="plate")
p.screw_hole("M4", at=[(0, 5, 20), (0, 5, -20)], kind="countersunk", direction="-y")   # from the plate front (Y = 5)
p.sweep(Profile.circle(8), Path.polyline([(0, 2, 0), (0, 45, 0), (0, 45, 30)], radius=12), name="rod")
