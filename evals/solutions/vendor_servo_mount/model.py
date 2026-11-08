from cad import Part


def build():
    servo = Part.from_file("vendor/micro_servo.step", "servo", reference=True)
    mount = Part("mount", material="PETG")
    # ears: x -22 .. 10.2, y -6.1 .. 6.1, underside z = -2.5; plate 6 mm wider on every side
    mount.box(32.2 + 12, 12.2 + 12, 4, at=(-5.9, 0, -6.5))
    mount.box(22.8 + 1, 12.2 + 1, 4, at=(-5.9, 0, -6.5), op="cut")
    mount.holes(2.2, [(-19.8, 0), (8.0, 0)])
    return [mount, servo]
