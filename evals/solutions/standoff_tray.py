from cad import Part, Profile

t = Part("tray")
t.box(76, 56, 12, name="shell")
t.box(72, 52, 11, at=(0, 0, 2), op="cut")
for x in (-26, 26):
    for y in (-16, 16):
        t.cylinder(6, 5, at=(x, y, 2))
t.holes(2.5, [(x, y, 7) for x in (-26, 26) for y in (-16, 16)], depth=4)
t.holes(3.2, [(0, -24), (0, 24)])
t.assert_valid()
