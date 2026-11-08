"""Robot arm link on a servo horn, with stress studies for `cad fea`.

Demonstrates: Study load cases on named faces (the horn's screw holes held fixed, a
payload pushing down on the tip, a pushrod pulling sideways on the tip pin as a bearing
load), Parameters that `cad fea` traces hot spots back to, and `cad render --fea`.

    cad build && cad fea            # safety factor, peak stress, hot spots -> parameters
    cad render --fea payload --deformed
"""
from cad import Parameter, Part, Study

length = Parameter("arm.length", 90, min=50, max=150)
thick = Parameter("arm.thickness", 5.0, min=2, max=12)  # along the servo axis (Z)
width = Parameter("arm.width", 12.0, min=6, max=30)
root_r = Parameter("arm.root_fillet", 2.0, min=0.5, max=6)
payload = Parameter("payload_N", 8.0, unit="N", description="weight hanging at the tip")
pushrod = Parameter("pushrod_N", 30.0, unit="N", description="sideways pull of a linkage on the tip pin")

arm = Part("arm", material="PETG")
arm.cylinder(24, thick, name="hub")
arm.box(length, width, thick, at=(length / 2, 0, 0), align=("center", "center", "min"), name="beam")
arm.cylinder(width + 4, thick, at=(length, 0, 0), name="tip")
arm.fillet(arm.edges().concave(), root_r, name="root")
arm.hole(7, at=(0, 0), name="spline")  # clearance for the horn's hub
arm.bolt_circle(2.2, circle_diameter=16, count=4, start_angle=45, name="horn")  # M2 screws into the horn
arm.hole(4, at=(length, 0), name="pin")

lift = Study("payload", arm, target=2, description="arm horizontal, payload weight on the tip")
lift.fixed("horn.wall")  # the four screws hold the arm to the horn
# the arm's top is one merged face (hub, beam and tip are coplanar): load just the tip pad
lift.force("tip.top", payload, "-z", at=(length, 0, thick), radius=8)

side = Study("pushrod", arm, target=2, description="a linkage pulls the tip pin sideways")
side.fixed("horn.wall")
side.bearing("pin.wall", pushrod, "+y")
