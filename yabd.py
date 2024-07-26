#!/bin/env python

from typing import Literal

import argparse
import functools as ft
from logging import info
import logging
import os

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

dbus_loop = DBusGMainLoop(set_as_default=True)

class Daemon(dbus.service.Object):

    #################### OPTIONS (can be changed through command line)
    controllable = True #whether to respond to dbus calls
    device = "intel_backlight"
    subsystem = "backlight"

    min_selectable_brightness = 1. # do not set the brightness lower than that (in percent)
    max_selectable_brightness = 100. # do not set the brightness higher than that (same)
    dimmed_brightness = .7 # brightness when dimmed
    max_ambient_brightness = 500.

    ambient_brightness_change_to_get_control_back = 100. # in lumen
    ramp = True #whether to ramp the brightness up and down
     #vs just setting it (disabling this makes the screen look flickery)
    ramp_step = 0.5 # in percent, how much to change brightness per 10ms when ramping. Too high a value might cause flicker

    gamma= 2. # for power scaling

    yield_control_on_brightness_change = False #whether to yield control when the brightness is changed by another application

    ##################### STATE
    multiplier= 1. # changes when user change brightness control. 

    known_brightness = None
    is_dim = False
    has_control = True #whether we should be controlling the brightness
    #if the brightness changes for any other reason than our daemon, 
    # we stop controlling it, and record the ambient light
    # if the ambient light has changed too much compared to when we lost control
    # we take it back 
    #ambient brightness when we lost control of it
    ambient_brightness_when_lost_control:  float | None = None
    ramp_step_units: int # in absolute units
    target_brightness: int | None = None
    ramp_timeout_id: int | None = None

    main_loop: GLib.MainLoop
    
    def __init__(self, main_loop: GLib.MainLoop, read_args=True):
        if read_args:
            self.read_args()
        self.main_loop = main_loop
        # get buses
        bus = dbus.SystemBus()
        session_bus = dbus.SessionBus()
        # register our dbus service
        our_bus_name = dbus.service.BusName("re.bruge.yabd", bus=session_bus)
        dbus.service.Object.__init__(self, session_bus, "/re/bruge/yabd", our_bus_name)

        # subscribe to sensor
        sensor_proxy = bus.get_object('net.hadess.SensorProxy', '/net/hadess/SensorProxy')
        sensor_interface = dbus.Interface(sensor_proxy, dbus_interface='net.hadess.SensorProxy')
        sensor_interface.ClaimLight()
        sensor_proxy.connect_to_signal("PropertiesChanged", dbus_interface="org.freedesktop.DBus.Properties", handler_function=self.brightness_changed_handler)

        self.bus = bus
        self.sensor_interface = sensor_interface
        self.sensor_proxy = sensor_proxy
        self.ramp_step_units = int(self.ramp_step * self.max_brightness / 100)

    def set_brightness_percent(self, brightness_percent, ramp=False):
        info(f"setting brightness to {brightness_percent}%")
        brightness = int(self.max_brightness * brightness_percent / 100)
        self.set_brightness(brightness, ramp=ramp)

    def set_brightness(self, brightness, ramp=False):
        if ramp: 
            self.target_brightness = brightness
            self.start_ramp()
            return
        self.has_control = True
        self.known_brightness = brightness
        self.bus.call_blocking("org.freedesktop.login1", 
                        '/org/freedesktop/login1/session/auto', 
                        'org.freedesktop.login1.Session', 
                        "SetBrightness", "ssu", 
                        ( "backlight", "intel_backlight", brightness))

    def brightness_changed_handler(self, _, args, __):
        """Dbus signal handler for brightness changes"""
        light_level = float(args["LightLevel"])
        screen_brightness = self.query_brightness()
        if not self.has_control and self.should_take_control_back(light_level):
            self.has_control = True
            self.ambient_brightness_when_lost_control= None
            self.known_brightness = None
        elif self.known_brightness is None:
            self.known_brightness = screen_brightness
        elif screen_brightness != self.known_brightness and self.yield_control_on_brightness_change:
            info(f"current brightness is {screen_brightness}. Last know brightness is {self.known_brightness}. surrendering control.")
            self.has_control = False
            self.ambient_brightness_when_lost_control = light_level
        self.known_brightness = screen_brightness

        if self.has_control:
            self.set_brightness_depending_on_ambient_light()

    def set_brightness_depending_on_ambient_light(self, light_level=None):
        info(f"got {light_level=}")
        # find light level
        if light_level is None: #might happen if we call this function directly
            light_level = float(self.sensor_proxy.Get("net.hadess.SensorProxy", 
                                                      "LightLevel",
                    dbus_interface="org.freedesktop.DBus.Properties"))
        light_level = min(light_level, self.max_ambient_brightness) # clip light_level to the max
        brightness_range_size = self.max_selectable_brightness - self.min_selectable_brightness
        light_level_percent = light_level / self.max_ambient_brightness

        # scale brightness depending on ambient light with a power law
        brightness_percent = self.min_selectable_brightness + \
                    brightness_range_size * light_level_percent ** self.gamma

        # apply user multiplier
        brightness_percent = multiplier * brightness_percent

        # clip brightness to the min and max
        brightness_percent = max(self.min_selectable_brightness, brightness_percent)
        brightness_percent = min(self.max_selectable_brightness, brightness_percent)

        if self.is_dim:
            brightness_percent= self.dimmed_brightness
        self.set_brightness_percent(brightness_percent, ramp=self.ramp)

    def handle_ramptimeout(self):
        """callback for ramping brightness"""
        current_brightness = self.query_brightness()

        if self.target_brightness is None:
            return self.stop_ramp()
        if abs(current_brightness - self.target_brightness) < self.ramp_step_units:
            self.set_brightness(self.target_brightness)
            return self.stop_ramp()
        if current_brightness < self.target_brightness:
            self.set_brightness(current_brightness + self.ramp_step_units)
        else:
            self.set_brightness(current_brightness - self.ramp_step_units)
        return True

    def start_ramp(self):
        info("starting ramp")
        if self.ramp_timeout_id is not None: return
        self.ramp_timeout_id = GLib.timeout_add(10, self.handle_ramptimeout)

    def stop_ramp(self):
        """`return self.stop_ramp()` in the timeout handler stops the ramp.
        This function by itself doesnt actually stop the ramp 
        but handles setting variables when stopping the ramp and returns False.
        what stops the ramp is returning false from the timeout handler.
        thus `return self.stop_ramp()` in the timeout handler stops the ramp
        """
        info("stopping ramp")
        self.ramp_timeout_id = None
        self.target_brightness = None
        return False

    def should_take_control_back(self, brightness_level):
        assert self.ambient_brightness_when_lost_control is not None
        if self.ambient_brightness_change_to_get_control_back == 0:
            return False
        return abs(brightness_level - self.ambient_brightness_when_lost_control) > self.ambient_brightness_change_to_get_control_back

    def query_brightness(self):
        with open(f"/sys/class/{self.subsystem}/{self.device}/brightness" 
                  ,"r") as f:
            return int(f.read())

    @ft.cached_property
    def max_brightness(self):
        with open(f"/sys/class/{self.subsystem}/{self.device}/max_brightness" 
                  ,"r") as f:
            return int(f.read())

    def set_multiplier(self, multiplier, in_percent=False):
        if in_percent: multiplier = multiplier / 100
        multiplier = max(0, multiplier)
        multiplier = min(2., multiplier) #max multiplier is 2.
        self.multiplier = multiplier
        self.set_brightness_depending_on_ambient_light()
        if in_percent: return multiplier * 100
        return multiplier

    ##################################### DBUS METHODS. 
    # They all return False if the daemon is not controllable.
    @dbus.service.method("re.bruge.yabd", in_signature="", out_signature="b")
    def dim(self):
        if not self.controllable: return False
        self.is_dim = True
        self.set_brightness_depending_on_ambient_light()
        return True

    @dbus.service.method("re.bruge.yabd", in_signature="", out_signature="b")
    def undim(self):
        if not self.controllable: return False
        self.is_dim = False
        self.set_brightness_depending_on_ambient_light(self.known_brightness)
        return True

    @dbus.service.method("re.bruge.yabd", in_signature="d", out_signature="v")
    def change_multiplier(self, change: float):
        """Returns the new multiplier value. Input is in percent."""
        if not self.controllable: return False
        return self.set_multiplier(self.multiplier + change, in_percent=True)

    @dbus.service.method("re.bruge.yabd", in_signature="d", out_signature="v")
    def set_multiplier(self, new_multiplier: float):
        """Returns the new multiplier value. Input is in percent."""
        if not self.controllable: return False
        return self.set_multiplier(new_multiplier, in_percent=True)

    @classmethod
    def argument_parser(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument("--max-brightness", type=float, help=f"max selectable brightness in percent (default: {cls.max_selectable_brightness})", default=cls.max_selectable_brightness)
        parser.add_argument("--min-brightness", type=float, help=f"min selectable brightness in percent (default: {cls.min_selectable_brightness})", default=cls.min_selectable_brightness)
        parser.add_argument("--max-ambient-brightness", type=float, 
                            help=f"ambient brightness (in lumen) corresponding to the max (default: {cls.max_ambient_brightness})", default=cls.max_ambient_brightness)
        parser.add_argument("--device", type=str, help=f"device to control (default {cls.device})", default=cls.device)
        parser.add_argument("--subsystem", type=str, help=f"subsystem to control (default {cls.subsystem})", default=cls.subsystem)
        parser.add_argument("--yield-control", action=argparse.BooleanOptionalAction, help=f"If this option is activated and the screen brightness is changed by another application, this daemon stops controlling it temporarily. (default {cls.controllable})", default=cls.controllable)
        parser.add_argument("""--change-to-get-control-back", type=float, help=f"how much the ambient brightness has to change to get control back (default {cls.ambient_brightness_change_to_get_control_back} lumen). 
    If `--yield-control` is activated and another program changes the screen brightness, the daemon stops controlling the screen brightness. 
    But if the ambient brightness changes more than this amount, it takes control back. set to 0 to disable this behaviour""", 
                            default=cls.ambient_brightness_change_to_get_control_back)
        parser.add_argument("--controllable", action=argparse.BooleanOptionalAction, help=f"whether to respond to dbus commands (dim, undim, change_multiplier, set_multiplier) (default {cls.controllable})", default=cls.controllable)
        parser.add_argument("--ramp", action=argparse.BooleanOptionalAction, help=f"ramp brightness changes (default {cls.ramp})", default=cls.ramp)
        parser.add_argument("--ramp-step", type=float, help=f"how much to change the brightness every 10 ms when ramping (in percent, default {cls.ramp_step})", default=cls.ramp_step)
        parser.add_argument("--gamma", type=float, help=f"gamma for power scaling (default {cls.gamma}). 1 means proportional. Lower values mean that as the room gets brighter, the screen gets brighter faster. ", default=cls.gamma)
        parser.add_argument("-v", "--verbose", 
                            action="store_const", 
                            dest="loglevel", 
                            const=logging.INFO,  
                            default=logging.WARNING,
                            help="enable logging")
        return parser

    def read_args(self, args=None):
        if args is None:
            parser = self.argument_parser()
            args = parser.parse_args()
        self.max_selectable_brightness = args.max_brightness
        self.min_selectable_brightness = args.min_brightness
        self.max_ambient_brightness = args.max_ambient_brightness
        self.ambient_brightness_change_to_get_control_back = args.change_to_get_control_back
        self.device = args.device
        self.controllable = args.controllable
        self.subsystem = args.subsystem
        logging.basicConfig(level=args.loglevel)

# def run_command(command, args, *,  signature=""):
#     # get bus
#     session_bus = dbus.SessionBus()
#     daemon = bus.get_object('re.bruge.yabd', '/re/bruge/yabd')
#     sensor_interface = dbus.Interface(sensor_proxy, dbus_interface='net.hadess.SensorProxy')
#
#     result = session_bus.call_blocking("re.bruge.yabd", 
#             '/re/bruge/yabd', 
#             're.bruge.yabd', 
#             command, 
#             signature, 
#             args)
#     if isinstance(result, dbus.Boolean) and not result:
#         logging.err("Daemon is not controllable, command failed")
#         os.exit(1)
#         
    

loop = GLib.MainLoop()
daemon = Daemon(read_args=True, main_loop=loop)
loop.run()
