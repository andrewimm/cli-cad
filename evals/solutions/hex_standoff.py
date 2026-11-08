from cad import Part, Profile

s = Part("standoff")
s.extrude(Profile.regular_polygon(6, 8 / 0.8660254037844386), 20)
s.hole(2.5, at=(0, 0))
s.chamfer(s.edges().perpendicular_to("z").linear(), 0.5)
