from cad import Part, Profile

box = Part("box")
box.extrude(Profile.rounded_rect(100, 70, 6), 40, name="body")
box.shell(2.5, open_faces=box.faces("body.top"))

lid = Part("lid")
lid.extrude(Profile.rounded_rect(100, 70, 6), 3, offset=40)
ow, oh = 100 - 5 - 0.5, 70 - 5 - 0.5
lip = Profile.rounded_rect(ow, oh, 3.25) - Profile.rounded_rect(ow - 4, oh - 4, 1.25)
lid.extrude(lip, -3, offset=40)
