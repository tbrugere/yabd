# yabd
Yet another brightness daemon

This is a simple daemon that sets the brightness of the screen depending on ambient brightness.
It was developed for my [framework](https://frame.work/) laptop on wayland / sway, but it should work with any system that 
1. uses systemd/dbus (with systemd-logind)
2. 

Features:

- Set brightness depending on ambient brightness sensor
- dim screen with a dbus command (for use with `swayidle` or similar)
- optionally ramps brightness up and down smoothly 
- Uses dbus interfaces `systemd-logind (8)` (to set brightness) and [iio-sensor-proxy](https://gitlab.freedesktop.org/hadess/iio-sensor-proxy/). This means it should be compatible with any window system / wayland / tty (though I have only tested it on `sway`).

## Installation

## Interface

```console
usage: yabd [-h] [--max-brightness MAX_BRIGHTNESS] [--min-brightness MIN_BRIGHTNESS]
            [--max-ambient-brightness MAX_AMBIENT_BRIGHTNESS] [--device DEVICE]
            [--subsystem SUBSYSTEM]
            [--change-to-get-control-back CHANGE_TO_GET_CONTROL_BACK]
            [--ramp | --no-ramp] [-v]

options:
  -h, --help            show this help message and exit
  --max-brightness MAX_BRIGHTNESS
                        max selectable brightness in percent (default: 100.0)
  --min-brightness MIN_BRIGHTNESS
                        min selectable brightness in percent (default: 5.0)
  --max-ambient-brightness MAX_AMBIENT_BRIGHTNESS
                        ambient brightness (in lumen) corresponding to the max
                        (default: 500.0)
  --device DEVICE       device to control (default intel_backlight)
  --subsystem SUBSYSTEM
                        subsystem to control (default backlight)
  --change-to-get-control-back CHANGE_TO_GET_CONTROL_BACK
                        how much the ambient brightness has to change to get control
                        back (default 100.0 lumen). If the screen brightness is changed
                        by another application, this daemon stops controlling it
                        temporarily. but if the ambient brightness changes more than
                        this amount, it takes control back. set to 0 to disable this
                        behaviour
  --ramp, --no-ramp     ramp brightness changes (default True) (default: True)
  -v, --verbose         enable logging
```
