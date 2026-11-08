from cad import Parameter, Part

W = Parameter("plate_width", 100)
H = Parameter("plate_height", 70)
D = Parameter("hole_diameter", 4.5)
SX = Parameter("hole_spacing_x", 35)
SY = Parameter("hole_spacing_y", 40)

p = Part("plate")
p.box(W, H, 6, align="min")
p.hole_pattern(D, spacing=(SX, SY), count=(3, 2), center=(W / 2, H / 2))
