"""Robot arm link: screwed to a servo horn at the hub, a linkage pin at the tip."""
from cad import Parameter, Part, Study

length = Parameter("arm.length", 90)
thick = Parameter("arm.thickness", 4.0)
width = Parameter("arm.width", 10.0)

arm = Part("arm", material="PETG")
arm.cylinder(24, thick, name="hub")
arm.box(length, width, thick, at=(length / 2, 0, 0), align=("center", "center", "min"), name="beam")
arm.cylinder(14, thick, at=(length, 0, 0), name="tip")
arm.hole(7, at=(0, 0), name="spline")                                          # clearance for the horn's hub
arm.bolt_circle(2.2, circle_diameter=16, count=4, start_angle=45, name="horn")  # M2 screws into the servo horn
arm.hole(4, at=(length, 0), name="pin")                                         # linkage pin

# load cases (do not change them): the servo holds the arm by its four horn screws
side = Study("pushrod", arm, target=2, description="the linkage pulls the tip pin sideways")
side.fixed("horn.wall")
side.bearing("pin.wall", 30, "+y")

lift = Study("payload", arm, target=2, description="arm horizontal, a 12 N load pressing down around the tip pin")
lift.fixed("horn.wall")
lift.force("tip.top", 12, "-z", at=(length, 0, thick), radius=7)
