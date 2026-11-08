from cad import Parameter, Part, Profile

fold = Parameter("fold_angle", 0, min=0, max=120, unit="deg")
W, T = 12.0, 4.0


def link(name, length, z0):
    prof = Profile.rect(length, W, center=(length / 2, 0)) + Profile.circle(W) + Profile.circle(W, center=(length, 0))
    p = Part(name)
    p.extrude(prof, T, offset=z0)
    for x in (0, length):
        p.hole(4.2, at=(x, 0))
    return p


def build():
    base = Part("base_block")
    base.box(30, 30, 10, at=(-10, 0, 0), align=("center", "center", "min"))      # Z 0..10
    base.hole(4.2, at=(0, 0))
    base.holes(3.4, [(-20, -9), (-20, 9)])
    arm = link("arm", 60, 10.5)                       # Z 10.5..14.5
    fore = link("forearm", 50, 15.0)                  # Z 15..19, starts at the origin
    fore.rotate(fold, axis="z")                       # +fold swings the tip toward +Y
    fore.translate((60, 0, 0))
    return {"base_block": base, "arm": arm, "forearm": fore}
