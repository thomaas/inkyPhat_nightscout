from PIL import Image, ImageFont, ImageDraw
from inky import InkyPHAT
from font_intuitive import Intuitive
from config import matplotImagePath

img, inky_display = None, None
def initialize():
    inky_display = InkyPHAT("red")
    img = Image.open(matplotImagePath).convert('L')
    img.point(lambda x: 255 if x < 240 else 0, '1')
    img = img.resize((inky_display.WIDTH, inky_display.HEIGHT))

def displayText(text, position, size, offsetx, offsety):
    # Put title text on Pi
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(Intuitive, size)
    w, h = font.getsize(text)
    x = 0
    y = offsety
    if position == "centered":
        x = (inky_display.WIDTH / 2) - (w / 2)

    if position == "right":
        x = inky_display.WIDTH - w - offsetx

    draw.text((x, y), text, inky_display.BLACK, font)
    return w, h

def display():
    img.save("/home/shares/test/images/shown_graph.png", "PNG")
    inky_display.set_image(img)
    inky_display.show()
