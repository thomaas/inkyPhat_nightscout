import dexcomCalls
import matplotLibActions

from PIL import ImageDraw

from inkyHelper import InkyDisplay
from config import matplotImagePath


def main():
    sgvs, dates, delta = dexcomCalls.getDataFromNightscout()
    matplotLibActions.createSGVPlot(sgvs, dates)

    display = InkyDisplay()
    img = display.prepareImage(matplotImagePath)
    draw = ImageDraw.Draw(img)

    deltaStr = f"+{delta}" if delta > 0 else str(delta)

    _, hDelta = display.drawText(draw, deltaStr, 20, 0, 0)
    wMg, hMg = display.drawText(draw, "mg/dl", 10, 0, hDelta)
    display.drawText(draw, str(sgvs[-1]), 32, wMg + 2, 0)
    display.drawText(draw, dates[-1], 12, 0, hDelta + hMg)

    display.show(img)


if __name__ == "__main__":
    main()
