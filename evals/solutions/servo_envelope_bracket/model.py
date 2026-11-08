from cad import Part


def build():
    b = Part("bracket")
    b.box(76, 40, 10, name="base")                                   # Z 0..10: the servo stands on Z = 10
    for sx in (-1, 1):                                               # 9 mm end walls, 0.5 mm from the servo's X faces
        b.box(9, 20, 40, at=(sx * 25.0, 0, 10), align=("center", "center", "min"), name=f"wall{'n' if sx < 0 else 'p'}")
    b.holes(3.4, [(x, y) for x in (-33, 33) for y in (-14, 14)], name="mount")
    b.holes(2.5, [(-25, 0, 50), (25, 0, 50)], depth=10, name="clamp_pilots")
    b.assert_valid()

    c = Part("clamp")                                                # rests on the servo top and the wall tops
    c.box(62, 20, 3, at=(0, 0, 50))
    c.hole(9, at=(10, 0), name="shaft_clearance")
    c.holes(2.9, [(-25, 0), (25, 0)], name="screws")
    c.assert_valid()
    return {"bracket": b, "clamp": c}
