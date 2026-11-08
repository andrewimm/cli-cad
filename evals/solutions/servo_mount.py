from cad import Part

p = Part("servo_mount")
p.box(50, 30, 3)
p.box(23.4, 12.8, 3, op="cut")
p.holes(2.0, [(-13.9, 0), (13.9, 0)])
p.hole_pattern(3.2, spacing=(40, 20))
