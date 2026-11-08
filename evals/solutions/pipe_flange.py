from cad import Part

f = Part("flange")
f.cylinder(100, 12)
f.cylinder(50, 18, at=(0, 0, 12))
f.hole(30, at=(0, 0))
f.bolt_circle(11, circle_diameter=75, count=6)
