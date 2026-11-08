"""Regenerate the import fixtures: `python tests/fixtures/make_fixtures.py`.

servo_inch.step  a two-body named, coloured assembly written in INCH units
                 (housing: 10 mm cube; shaft: 5 x 20 mm cylinder at x = 30 mm)
bracket.stl      an L-bracket as a binary STL (mm)
evals/setups/vendor_servo_mount/vendor/micro_servo.step   the servo for the servo_mount eval task
"""
from pathlib import Path

import re

from OCP.Interface import Interface_Static
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool

from cad import Part

HERE = Path(__file__).parent


def servo_step(path: Path) -> None:
    housing = Part("housing"); housing.box(10, 10, 10)
    shaft = Part("shaft"); shaft.cylinder(5, 20, at=(30, 0, 0))
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)

    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    asm = st.NewShape()
    TDataStd_Name.Set_s(asm, TCollection_ExtendedString("servo"))
    for name, part, rgb in (("housing", housing, (0.1, 0.1, 0.1)), ("shaft", shaft, (0.9, 0.9, 0.9))):
        lab = st.AddShape(part.shape, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(name))
        ct.SetColor(lab, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)
        st.AddComponent(asm, lab, TopLoc_Location())
    st.UpdateAssemblies()
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    w.SetColorMode(True)
    w.Transfer(doc)
    w.Write(str(path))
    # OCCT always writes millimetres: rewrite as an inch file (lengths / 25.4, inch unit)
    text = path.read_text()

    def scale(m):
        return m.group(1) + ",".join(f"{float(v) / 25.4:.10g}" for v in m.group(2).split(",")) + m.group(3)

    text = re.sub(r"(CARTESIAN_POINT\('[^']*',\()([^)]*)(\))", scale, text)
    text = re.sub(r"((?:CIRCLE|CYLINDRICAL_SURFACE)\('[^']*',#\d+,)([-\d.E+]+)(\))", scale, text)
    text = re.sub(r"(VECTOR\('[^']*',#\d+,)([-\d.E+]+)(\))", scale, text)
    text = re.sub(r"\( LENGTH_UNIT\(\) NAMED_UNIT\(\*\) SI_UNIT\(\.MILLI\.,\.METRE\.\) \)",
                  "( CONVERSION_BASED_UNIT('INCH',#99001) LENGTH_UNIT() NAMED_UNIT(#99002) )", text)
    text = text.replace("ENDSEC;\nEND-ISO", "#99001 = LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#99003);\n"
                        "#99002 = DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.);\n"
                        "#99003 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );\nENDSEC;\nEND-ISO", 1)
    path.write_text(text)


def micro_servo_step(path: Path) -> None:
    """A generic micro servo, vendor style: origin on the output shaft axis at the top of the
    mounting ears (Z up), body hanging below.  Ear holes 2.2 mm at x = -19.85 / +7.95."""
    case = Part("case")
    case.box(22.8, 12.2, 22.7, at=(-5.9, 0, -15.9))                 # body: z -15.9 .. 6.8, centred 5.9 mm behind the shaft
    case.box(32.2, 12.2, 2.5, at=(-5.9, 0, -2.5))                   # mounting ears: top at z = 0
    case.holes(2.2, [(-5.9 - 13.9, 0), (-5.9 + 13.9, 0)])           # ear holes 27.8 mm apart
    case.cylinder(11.8, 4.0, at=(0, 0, 6.8))                         # gear-train boss on top
    shaft = Part("output_shaft")
    shaft.cylinder(4.8, 3.2, at=(0, 0, 10.8))
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    XCAFApp_Application.GetApplication_s().InitDocument(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    asm = st.NewShape()
    TDataStd_Name.Set_s(asm, TCollection_ExtendedString("micro_servo"))
    for name, part, rgb in (("case", case, (0.15, 0.3, 0.75)), ("output_shaft", shaft, (0.95, 0.95, 0.95))):
        lab = st.AddShape(part.shape, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(name))
        ct.SetColor(lab, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)
        st.AddComponent(asm, lab, TopLoc_Location())
    st.UpdateAssemblies()
    w = STEPCAFControl_Writer()
    w.SetNameMode(True)
    w.SetColorMode(True)
    w.Transfer(doc)
    w.Write(str(path))


def bracket_stl(path: Path) -> None:
    p = Part("bracket"); p.box(30, 20, 3); p.box(30, 3, 20, at=(0, -8.5, 0))
    p.export(str(path))


if __name__ == "__main__":
    servo_step(HERE / "servo_inch.step")
    bracket_stl(HERE / "bracket.stl")
    micro_servo_step(HERE.parents[1] / "evals" / "setups" / "vendor_servo_mount" / "vendor" / "micro_servo.step")
