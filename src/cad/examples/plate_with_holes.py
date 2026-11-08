"""Rectangular plate with four corner mounting holes and rounded corners.

The smallest useful example: box, hole_pattern, fillet of vertical edges.
"""
from cad import Parameter, Part

w = Parameter("width", 70, min=20, max=300)
d = Parameter("depth", 45, min=20, max=300)
t = Parameter("thickness", 4, min=1, max=30)

plate = Part("plate")
plate.box(w, d, t, name="body")                       # centred on origin, z from 0 to t
plate.hole_pattern(3.4, spacing=(w - 14, d - 14), count=(2, 2), name="mount")
plate.fillet(plate.edges().vertical().convex(), radius=3)
plate.chamfer(plate.edges("body.top").convex().exclude(plate.edges().circular()), 0.5)
plate.assert_valid()
