"""Nameplate with engraved and embossed text, plus a two-material label.

Demonstrates: Part.engrave / Part.emboss on top and side faces (text reads normally
from outside each face), size = capital letter height in mm, at= to position text,
TEXT_* warnings, and text as its own part in a second material for 3MF printing.
"""
from cad import Material, Parameter, Part, Plane, Profile

label_text = Parameter("label", "SN 0042", unit=None)


def build():
    plate = Part("plate", material="PETG")
    plate.box(80, 36, 5, name="body")
    plate.fillet(plate.edges().vertical(), 4)
    plate.hole_pattern(4.2, spacing=(68, 24), count=(2, 2))
    plate.engrave(label_text, on=plate.faces("body.top"), size=7, depth=0.8, at=(0, 4), bold=True)
    plate.emboss("MADE WITH CAD", on=plate.faces("body.top"), size=3.2, height=0.5, at=(0, -8), bold=True)
    plate.engrave("FRONT", on=plate.faces("body.front"), size=2.6, depth=0.4, bold=True)
    plate.assert_valid()

    # a separate badge in orange PLA sitting on the plate, for a two-colour print
    badge = Part("badge", material=Material("PLA", color="#e8a050"))
    badge.extrude(Profile.text("v1", 5, bold=True), 0.6, plane=Plane.from_face(plate.faces("body.top"), at=(24, -8)))
    badge.assert_valid(solids=None)
    return {"plate": plate, "badge": badge}
