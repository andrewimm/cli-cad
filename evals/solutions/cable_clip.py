from cad import Part, Profile

c = Part("clip")
c.box(36, 14, 3)
ring = Profile.circle(16, center=(0, 10)) - Profile.circle(10, center=(0, 10))
c.extrude(ring, 14, plane="XZ", symmetric=True)
c.box(7, 20, 10, at=(0, 0, 13), op="cut")
c.holes(4, [(-13, 0), (13, 0)], countersink=(8, 90))
c.assert_valid()
