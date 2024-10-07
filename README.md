# yabd
Yet another brightness daemon

This is a simple (~300 lines of python) daemon that sets the brightness of the screen depending on ambient brightness.
It was developed for my [framework](https://frame.work/) laptop on wayland / sway, but it should work with any system that 
1. uses systemd/dbus (with `systemd-logind`)
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

You will first need `python-sdbus-git` from the AUR (installable with your favourite AUR manager). 

```console
$ pikaur -S --asdeps python-sdbus-git # or your favourite AUR manager
$ cd etc
$ makepkg -si
```


### With Pip

First install `python3.10` or newer and `iio-sensor-proxy` through your package manager. 

Then use pip to install `yabd` and its python dependencies:

```console
$ pip install yabd
```

it will get installed in `$site-packages/yabd.py`

Optionally also install the systemd service file from this repo:

```console
$ cp etc/yabd-installed-with-pip.service  ~/.config/systemd/user/yabd.service
```

## Usage

### systemd

The easiest way to use this is to use the provided systemd service file. To start the service once

```console
$ systemctl --user start yabd
```

To start the service on login

```console
$ systemctl --user enable yabd
```

To modify the options, edit the service file using 

```console
$ systemctl --user edit yabd
```

and modify the command line options in the `[Service]` section. The command line options are described below.

### Command line

#### Running the daemon

To run the daemon manually, use the `yabd run` command:

```console
$ yabd run --help
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

#### Changing the brightness


##### By changing the brightness directly

If another program changes the brightness (for example `brightnessctl`), the daemon will temporarily stop controlling the brightness. 

If the ambient light changes more than a threshold (default 100 lumen), the daemon will take back control of the brightness.

This behaviour is configurable and can be disabled (see `--change-to-get-control-back` and `--no-yield-control`) although 

- If yielding control it is disabled, changes to the brightness may be immediately rolled back by the daemon.
- If yielding control is enabled and the threshold is disabled, the daemon will stop doing anything if the brightness is changed by another program.
  
Thus for user control of the brightness, it is recommended to use the **brightness multiplier** instead (see below), or to keep the threshold to a reasonable value.

##### By changing the brightness multiplier

Otherwise, the user can change the brightness multiplier. This is a value that is originally equal to `100%`, and that is multiplied to every brightness value that is set by the daemon.

Hence, when the user adds `10%` to the brightness multiplier, the brightness will be `10%` higher than what the daemon would have otherwise set it to.

This can be done with the following commands:

```console
$ yabd change_multiplier -h
usage: yabd change_multiplier [-h] change

positional arguments:
  change      change the brightness multiplier by this amount (in percent)

options:
  -h, --help  show this help message and exit
$ yabd set_multiplier -h
usage: yabd set_multiplier [-h] new_multiplier

positional arguments:
  new_multiplier  set the brightness multiplier to this value (in percent)

options:
  -h, --help      show this help message and exit
```

for example
```console
$ yabd change_multiplier +10 # increase the brightness by 10%. prints the new multiplier
110.0 
$ yabd set_multiplier 100 # set the multiplier back to 100%. prints the new multiplier
100.0 
```

##### Example sway config

```swayconfig
bindsym XF86MonBrightnessUp exec "yabd change_multiplier +10"
bindsym XF86MonBrightnessDown exec "yabd change_multiplier -10"
```

#### Dimming the screen

This daemon allows the user to dim the screen via a remote command (via dbus). This is useful to dim the screen when the computer is idle.

Dimming / undimming the screen can be done with the following commands

```console
$ yabd dim
$ yabd undim
```
it could also be done by calling directly the `re.bruge.yabd` dbus interface (if you want to do it programmatically)

```console
$ gdbus call --session -d re.bruge.yabd -o /re/bruge/yabd -m re.bruge.yabd.dim
$ gdbus call --session -d re.bruge.yabd -o /re/bruge/yabd -m re.bruge.yabd.undim
```

For example, here is a sample `swayidle` config:

```console
timeout 200 'yabd dim' resume 'yabd undim'
timeout 300 'swaymsg "output * dpms off"' resume 'swaymsg "output * dpms on"'
```
