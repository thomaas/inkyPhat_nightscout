import nightscoutCalls
import matplotLibActions

from PIL import Image, ImageFont, ImageDraw

from font_intuitive import Intuitive

from inky import InkyPHAT, InkyWHAT
from config import matplotImagePath, inkyPhatColour, inkyPhatLastImageShown, saveLastImageShown

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


sgvs, dates, delta = nightscoutCalls.getDataFromNightscout()

matplotLibActions.createSGVPlot(sgvs, dates)

# Setup objects
inky_display = InkyPHAT(inkyPhatColour)
img = Image.open(matplotImagePath)
img = img.convert('L')
img = img.point(lambda x: 255 if x < 240 else 0, '1')
img = img.resize((inky_display.WIDTH, inky_display.HEIGHT))

if delta > 0:
    deltaStr = "+%d" % delta
else:
    deltaStr = "%d" % delta

w, hdelta = displayText(deltaStr, "right", 20, 0, 0)
wmg, hmgdl = displayText("mg/dl", "right", 10, 0, hdelta)
wsgv, h = displayText(str(sgvs[-1]), "right", 32, wmg + 2, 0)
displayText(dates[-1], "right", 12, 0, hdelta + hmgdl)

if saveLastImageShown:
    img.save(inkyPhatLastImageShown, "PNG")
inky_display.set_image(img)
inky_display.show()
