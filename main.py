import dexcomCalls
import matplotLibActions
from inkyHelper import InkyDisplay
from config import show_pump_data, target_high, target_low


def _get_pump_data():
    if not show_pump_data:
        return None
    try:
        import tandemCalls
        return tandemCalls.get_pump_data()
    except Exception as exc:
        print(f"Tandem API not available: {exc}")
        return None


def main():
    glucose = dexcomCalls.getDataFromNightscout()
    pump_data = _get_pump_data()

    img = matplotLibActions.render(glucose, pump_data, target_low, target_high)

    InkyDisplay().show(img)


if __name__ == "__main__":
    main()
