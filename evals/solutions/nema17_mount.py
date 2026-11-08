from cad import Part, Profile

m = Part("mount")
m.box(60, 60, 5)
m.hole(22.5, at=(0, 0))
m.hole_pattern(3.4, spacing=(31, 31), direction="+z", counterbore=(6.5, 3))
for x in (-24, 24):
    m.extrude(Profile.slot(14, 5.5, center=(x, 0), angle=90), 1, op="cut", through=True)
