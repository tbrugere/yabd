# yabd
Yet another brightness daemon

This is a simple (~200 lines of python) daemon that sets the brightness of the screen depending on ambient brightness.
It was developed for my [framework](https://frame.work/) laptop on wayland / sway, but it should work with any system that 
1. uses systemd/dbus (with systemd-logind)
2. has an ambient light sensor compatible with `iio-sensor-proxy`

Features:

- Set brightness depending on ambient brightness sensor
- dim screen with a dbus command (for use with `swayidle` or similar)
- optionally ramps brightness up and down smoothly 
- Uses dbus interfaces `systemd-logind (8)` (to set brightness) and [iio-sensor-proxy](https://gitlab.freedesktop.org/hadess/iio-sensor-proxy/). This means it should be compatible with any window system / wayland / tty (though I have only tested it on `sway`).

## Installation

This needs `python3.10` or newer. It also needs `iio-sensor-proxy` to be installed, as well as `pygobject` and `dbus-python`

### Arch linux

There is a PKGBUILD in the `etc` folder. You can install it with `makepkg -si`.

```console
$cd etc
$makepkg -si
```


### With Pip

First install `python3.10` or newer and `iio-sensor-proxy` through your package manager. 

Then use pip to install `yabd` and its python dependencies:

```console
pip install git+https://github.com/tbrugere/yabd.git
```

it will get installed in `$site-packages/yabd.py`

Optionally also install the systemd service file:

```console
cp etc/yabd-installed-with-pip.service  ~/.config/systemd/user/yabd.service
```

## Usage

### systemd

The easiest way to use this is to use the provided systemd service file. To start the service once

```console
systemctl --user start yabd
```

To start the service on login

```console
systemctl --user enable yabd
```

To modify the options, edit the service file using 

```console
systemctl --user edit yabd
```

and modify the command line options in the `[Service]` section. The command line options are described below.

### Command line

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
