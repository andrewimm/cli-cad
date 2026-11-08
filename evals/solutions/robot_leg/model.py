from cad import Parameter, Part, Profile

knee = Parameter("knee_angle", 0, min=0, max=90, unit="deg")
T = 5.0      # link thickness along Y
W = 16.0     # link width / pivot boss diameter


def link(name, length, y0):
    """A flat link in the XZ plane from (0, 0) down to (0, -length), thickness T at Y = y0..y0+T."""
    prof = Profile.rect(W, length, center=(0, -length / 2)) + Profile.circle(W) + Profile.circle(W, center=(0, -length))
    p = Part(name)
    p.extrude(prof, -T, plane="XZ", offset=-y0)       # XZ normal is -Y: distance -T extrudes toward +Y
    for z in (0, -length):
        p.hole(6.2, at=(0, z), direction="+y")
    return p


def build():
    base = Part("base_mount")
    base.box(30, 5, 40, at=(0, -0.5, -10), align=("center", "max", "min"))   # Y -5.5..-0.5, Z -10..30
    base.hole(6.2, at=(0, 0), direction="+y", name="hip")
    base.holes(3.4, [(-9, 22), (9, 22)], direction="+y", name="mount")

    upper = link("upper_link", 85, 0.0)                # Y 0..5
    lower = link("lower_link", 110, 5.5)               # Y 5.5..10.5, built hanging from the origin
    lower.translate((0, 0, -85))
    lower.rotate(-knee, axis="y", center=(0, 0, -85))  # +knee swings the foot toward +X
    return {"base_mount": base, "upper_link": upper, "lower_link": lower}
