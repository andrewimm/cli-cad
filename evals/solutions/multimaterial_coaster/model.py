from cad import Part


def build():
    c = Part("coaster", material="PLA")
    c.cylinder(90, 5)
    c.cylinder(80, 2, at=(0, 0, 3), op="cut")
    i = Part("insert", material="TPU")
    i.cylinder(80, 2, at=(0, 0, 3))
    return {"coaster": c, "insert": i}
