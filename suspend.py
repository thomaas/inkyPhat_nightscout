import dexcomCalls
import matplotLibActions
from inkyHelper import InkyDisplay
from config import target_high, target_low


def main():
    history = dexcomCalls.getTodayData()
    stats = dexcomCalls.timeInRangeStats(history, target_low, target_high)
    img = matplotLibActions.render_suspend(history, stats, target_low, target_high)
    InkyDisplay().show(img)


if __name__ == "__main__":
    main()
