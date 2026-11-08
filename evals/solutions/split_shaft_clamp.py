from cad import Part, Profile


def half(name, z0):
    h = Part(name)
    h.box(16, 30, 12, at=(0, 0, z0), align=("center", "center", "min"))
    h.cylinder(8.2, 20, at=(-10, 0, 0), axis="x", op="cut", name="bore")
    h.holes(3.4, [(0, -10), (0, 10)], name="screws")
    return h


top = half("clamp_top", 0)
bottom = half("clamp_bottom", -12)
for y in (-10, 10):
    nut = Profile.regular_polygon(6, across_flats=5.7, center=(0, y))   # corner on +X -> flats parallel to X
    bottom.extrude(nut, 2.6, offset=-12, op="cut")
