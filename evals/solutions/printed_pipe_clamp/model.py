from cad import Part

SCREWS = [(-18, 0), (18, 0)]


def half(name, z0):
    p = Part(name, material="PETG")
    p.box(50, 20, 15, at=(0, 0, z0), name="block")
    p.cylinder(20.4, 30, at=(0, -15, 15), axis="y", op="cut")
    return p


def build():
    bot = half("clamp_bottom", 0)
    bot.screw_hole("M4", at=[(x, y, 15) for x, y in SCREWS], kind="nut")     # drilled down: nut pocket at Z = 0
    bot.bottom_chamfer(0.5)
    top = half("clamp_top", 15)
    top.screw_hole("M4", at=SCREWS, kind="counterbore")
    top.bottom_chamfer(0.5)          # the split face is already this half's lowest face, i.e. its bed face
    return [bot, top]
