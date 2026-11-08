from cad import Part

p = Part("plate")
p.box(80, 36, 5, name="body")
p.fillet(p.edges().vertical(), 4)
p.holes(4.2, [(-34, -12), (34, -12), (-34, 12), (34, 12)])
p.engrave("SN 0042", on=p.faces("body.top"), size=7, depth=0.8, at=(0, 4))
p.emboss("MADE WITH CAD", on=p.faces("body.top"), size=3.2, height=0.5, at=(0, -8), bold=True)
