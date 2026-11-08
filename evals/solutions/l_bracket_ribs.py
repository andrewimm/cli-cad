from cad import Part, Profile

p = Part("bracket")
p.box(50, 40, 5, name="base")
p.box(50, 5, 35, at=(0, 20, 5), align=("center", "max", "min"), name="wall")
# rib triangle in the YZ plane (u = Y, v = Z): corner at (15, 5), legs 25 along -Y and +Z
rib = Profile.polygon([(15, 5), (-10, 5), (15, 30)])
for x in (-15, 15):
    p.extrude(rib, 4, plane="YZ", offset=x, symmetric=True)
p.hole(5.5, at=(-8, -12))
p.hole(5.5, at=(8, -12))
p.assert_valid()
