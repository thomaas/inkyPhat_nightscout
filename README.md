# inkyPhat_nightscout

A Python script that pulls glucose data from Dexcom (via [pydexcom](https://github.com/gagebenne/pydexcom)) and renders the latest reading plus a trend graph onto a Pimoroni [InkyPHAT](https://shop.pimoroni.com/products/inky-phat) mounted on a Raspberry Pi.

![InkyPhat generated graph](inkyPhatShown.png)
![InkyPhat mounted on a Raspberry Pi](inkyPhatShown2.jpeg)

## What you need

- A Raspberry Pi with a GPIO header (Zero W / Zero 2 W / 3 / 4 are all fine)
- A Pimoroni InkyPHAT (red, yellow, or black/white)
- A Dexcom Share account (username + password)
- Python 3.11 or newer

## Setup on the Raspberry Pi

1. **Enable SPI** so the Pi can talk to the InkyPHAT:

   ```bash
   sudo raspi-config nonint do_spi 0
   ```

2. **Install system packages** needed by Inky, Pillow, and numpy:

   ```bash
   sudo apt update
   sudo apt install -y git python3-venv python3-dev libopenjp2-7 libopenblas0
   ```

   `libopenblas0` is required by the numpy wheel — without it you'll see `ImportError: libopenblas.so.0: cannot open shared object file` when running the script.

3. **Clone the repo and create a virtualenv:**

   ```bash
   git clone https://github.com/thomaas/inkyPhat_nightscout.git
   cd inkyPhat_nightscout
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install inky
   ```

   `inky` is the Pimoroni driver for the e-paper display. It's intentionally not in `requirements.txt` so the project can also be developed on a Mac.

4. **Create your config:**

   ```bash
   cp config.py_example config.py
   ```

   Edit `config.py` and fill in:
   - `dexcom_username` / `dexcom_password` — your Dexcom Share login
   - `dexcom_region` — `"us"` for the US, `"ous"` for the rest of the world, `"jp"` for Japan
   - `inkyPhatColour` — `"red"`, `"yellow"`, or `"black"`, matching your InkyPHAT model

5. **Run it:**

   ```bash
   python main.py
   ```

   The InkyPHAT will refresh and show your latest reading.

## Refreshing automatically

To refresh every 5 minutes, add to `crontab -e` (adjust the path to your user's home directory):

```cron
*/5 * * * * /home/pi/inkyPhat_nightscout/.venv/bin/python /home/pi/inkyPhat_nightscout/main.py
```

Set `checkDataBeforeRefresh = True` in `config.py` to skip the (relatively slow) e-paper refresh when there's no new reading from Dexcom.

## Development on a Mac (or any non-Pi machine)

The script also runs without an InkyPHAT — the Inky import is detected as missing and the rendered image is saved as a PNG instead, which is useful for tweaking the layout.

```bash
git clone https://github.com/thomaas/inkyPhat_nightscout.git
cd inkyPhat_nightscout
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.py_example config.py
```

In `config.py`, set `saveLastImageShown = True` so the preview PNG (`inkyPhatLastShown.png`) is written, then:

```bash
python main.py
```

## Tests

```bash
pip install pytest
python -m pytest tests/
```

The tests in `tests/dexcomCalls_test.py` are integration tests that hit the live Dexcom API, so they require valid credentials in `config.py` to pass.
