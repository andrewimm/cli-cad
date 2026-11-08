from cad import Assembly, Parameter, Part, Profile

Parameter("yaw", 0, min=-90, max=90, unit="deg")
Parameter("shoulder", 0, min=-45, max=45, unit="deg")
Parameter("elbow", 0, min=-60, max=60, unit="deg")
T, W = 5.0, 14.0


def link(name, a, b, y0):
    """A flat link (thickness T along Y, from y0) between pivots a and b given as (x, z)."""
    import math
    (ax, az), (bx, bz) = a, b
    L = math.dist(a, b)
    ang = math.degrees(math.atan2(bz - az, bx - ax))
    prof = (Profile.rect(L, W, center=(L / 2, 0)) + Profile.circle(W) + Profile.circle(W, center=(L, 0))).rotated(ang)
    p = Part(name)
    p.extrude(prof.translated((ax, az)), -T, plane="XZ", offset=-y0)
    p.hole(5.2, at=(ax, az), direction="+y", name="pivot_a")
    p.hole(5.2, at=(bx, bz), direction="+y", name="pivot_b")
    return p


def build():
    base = Part("base"); base.cylinder(80, 10)
    turret = Part("turret")
    turret.cylinder(50, 8, at=(0, 0, 10.5))
    turret.box(16, 5, 40, at=(0, -9, 18.5), align=("center", "min", "min"))       # upright, Y -9..-4
    turret.hole(5.2, at=(0, 40), direction="+y", name="shoulder")
    lower = link("lower_arm", (0, 40), (0, 160), -3.5)                              # Y -3.5..1.5
    upper = link("upper_arm", (0, 160), (100, 160), 2.0)                             # Y 2..7
    asm = Assembly("lamp")
    asm.add(base, turret, lower, upper)
    asm.revolute("yaw", base, turret, axis=((0, 0, 0), (0, 0, 1)), angle="yaw")
    asm.revolute("shoulder", turret, lower, axis=turret.faces("shoulder.wall"), angle="shoulder")
    asm.revolute("elbow", lower, upper, axis=lower.faces("pivot_b.wall"), angle="elbow", direction="-y")
    return asm
