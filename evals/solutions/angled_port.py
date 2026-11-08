import math
from cad import Part

m = Part("manifold")
m.box(40, 30, 25)
m.hole(6, at=(-10, 0), depth=15)
s, c = math.sin(math.radians(30)), math.cos(math.radians(30))
L = 15 / c                                   # from Z=10 up to the top face along the axis
top = (-10 + L * s, 0, 25)
m.hole(6, at=top, direction=(-s, 0, -c), depth=L)
m.hole(4.5, at=(15, 5), direction="+y")
m.assert_valid()
