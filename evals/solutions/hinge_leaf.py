from cad import Part

h = Part("leaf")
h.box(40, 30, 2)
h.cylinder(6, 40, at=(-20, 15, 3), axis="x")
h.hole(2.2, at=(-20, 15, 3), direction="+x")
h.holes(3.5, [(-12, -3, 2), (0, -3, 2), (12, -3, 2)], countersink=(7, 90))
