from PIL import Image, ImageFont
from font_intuitive import Intuitive

from config import inkyPhatColour, inkyPhatLastImageShown, saveLastImageShown


class InkyDisplay:
    INKY_PHAT_WIDTH = 212
    INKY_PHAT_HEIGHT = 104
    FALLBACK_BLACK = 0

    def __init__(self):
        try:
            from inky import InkyPHAT
            self._display = InkyPHAT(inkyPhatColour)
            self.width = self._display.WIDTH
            self.height = self._display.HEIGHT
            self.black = self._display.BLACK
            self.hasHardware = True
        except (ImportError, RuntimeError):
            self._display = None
            self.width = self.INKY_PHAT_WIDTH
            self.height = self.INKY_PHAT_HEIGHT
            self.black = self.FALLBACK_BLACK
            self.hasHardware = False

    def prepareImage(self, source):
        img = Image.open(source).convert('L')
        img = img.point(lambda x: 255 if x < 240 else 0, '1')
        return img.resize((self.width, self.height))

    def drawText(self, draw, text, size, offsetX, offsetY, align="right"):
        font = ImageFont.truetype(Intuitive, size)
        left, top, right, bottom = font.getbbox(text)
        w, h = right - left, bottom - top
        if align == "centered":
            x = (self.width / 2) - (w / 2)
        elif align == "right":
            x = self.width - w - offsetX
        else:
            x = offsetX
        draw.text((x, offsetY), text, self.black, font)
        return w, h

    def show(self, img):
        if saveLastImageShown:
            img.save(inkyPhatLastImageShown, "PNG")
        if self.hasHardware:
            # Inky's set_image quantizes via palette and refuses mode '1' images.
            if img.mode == "1":
                img = img.convert("RGB")
            self._display.set_image(img)
            self._display.show()
        elif saveLastImageShown:
            print(f"No Inky hardware detected — preview saved to {inkyPhatLastImageShown}")
        else:
            print("No Inky hardware detected and saveLastImageShown is off — nothing to show.")
