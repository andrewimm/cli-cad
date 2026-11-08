import math
from cad import Part, Profile

a = math.radians(65)
d = (math.cos(a), math.sin(a))          # slope direction in (Y, Z)
n = (math.sin(a), -math.cos(a))         # toward the back face
p0 = (-10.0, 6.0)
p1 = (p0[0] + 100 * d[0], p0[1] + 100 * d[1])
rest = [p0, p1, (p1[0] + 6 * n[0], p1[1] + 6 * n[1]), (p0[0] + 6 * n[0], p0[1] + 6 * n[1])]
s = Part("stand")
s.box(70, 90, 6, name="base")
s.extrude(Profile.polygon(rest), 70, plane="YZ", symmetric=True, name="rest")
s.box(70, 5, 18, at=(0, -45, 0), align=("center", "min", "min"), name="lip")
s.box(14, 20, 40, at=(0, -45, -1), align=("center", "min", "min"), op="cut", name="slot")
s.assert_valid()
