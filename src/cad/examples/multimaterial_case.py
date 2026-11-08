"""Multi-material print: PETG case, TPU feet and an orange PLA inlay, exported as 3MF.

Demonstrates: Part(material=...), custom Material colours, touching (not overlapping)
parts in their assembled positions, mass from density, and
`cad export --format 3mf [--3mf-mode multimaterial]`.
"""
from cad import Material, Parameter, Part, Profile

L = Parameter("length", 80, min=40, max=200)
W = Parameter("width", 50, min=30, max=200)
H = Parameter("height", 25, min=10, max=100)


def build():
    case = Part("case", material="PETG")
    case.extrude(Profile.rounded_rect(L, W, 6), H, name="body")
    case.shell(2, open_faces=case.faces("body.top"))
    # shallow recess in the front wall for the inlay
    case.box(30, 0.6, 8, at=(0, -W / 2, H / 2), align=("center", "min", "center"), op="cut", name="recess")

    feet = Part("feet", material="TPU")
    corners = [(sx * (L / 2 - 8), sy * (W / 2 - 8), -1.5) for sx in (-1, 1) for sy in (-1, 1)]
    feet.cylinder(8, 1.5, at=corners)                      # four feet in one feature, touching the floor

    inlay = Part("inlay", material=Material("PLA", color="#e8a050"))
    inlay.box(30, 0.6, 8, at=(0, -W / 2, H / 2), align=("center", "min", "center"))  # fills the recess exactly

    for p in (case, feet, inlay):
        p.assert_valid(solids=None if p is feet else 1)
    assert case.interference(inlay) < 1e-6 and case.interference(feet) < 1e-6
    return {"case": case, "feet": feet, "inlay": inlay}
