from config import inkyPhatColour, inkyPhatLastImageShown, saveLastImageShown


class InkyDisplay:
    def __init__(self):
        try:
            from inky import InkyPHAT
            self._display = InkyPHAT(inkyPhatColour)
            self.hasHardware = True
        except (ImportError, RuntimeError):
            self._display = None
            self.hasHardware = False

    def show(self, img):
        if saveLastImageShown:
            img.save(inkyPhatLastImageShown, "PNG")
        if self.hasHardware:
            self._display.set_image(img)
            self._display.show()
        elif saveLastImageShown:
            print(f"No Inky hardware detected — preview saved to {inkyPhatLastImageShown}")
        else:
            print("No Inky hardware detected and saveLastImageShown is off — nothing to show.")
