from cad import Part

c = Part("cradle")
c.box(50, 70, 5, name="flange")                                          # Z 0..5, wide in Y for the screws
c.box(50, 40, 22, name="block")                                          # Z 0..22, below the sensor mid-plane (25)
c.cylinder(30, 80, at=(-40, 0, 25), axis="x", op="cut", name="seat")     # sensor seat, touches the body
c.holes(4.4, [(0, -28), (0, 28)], name="mount")                          # on the flange, clear of block and sensor
