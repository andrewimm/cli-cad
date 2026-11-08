from cad import Part

c = Part("coupler")
c.cylinder(25, 40)
c.hole(8, at=(0, 0, 0), depth=20, direction="+z")
c.hole(5, at=(0, 0, 40), depth=20, direction="-z")
c.hole(2.5, at=(12.5, 0, 10), depth=12.5, direction="-x")
c.hole(2.5, at=(12.5, 0, 30), depth=12.5, direction="-x")
c.chamfer(c.edges().circular(radius=12.5), 1)
