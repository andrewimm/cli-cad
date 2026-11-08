from cad import Part

p = Part("plate")
p.box(80, 50, 5, name="body")
p.hole_pattern(4.5, spacing=(68, 38), count=(2, 2))
p.fillet(p.edges().vertical().convex(), 5)
