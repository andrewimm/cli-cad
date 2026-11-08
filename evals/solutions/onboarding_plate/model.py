from cad import Part

plate = Part("plate")
plate.box(60, 40, 4)
plate.hole_pattern(4.5, spacing=(48, 28))
