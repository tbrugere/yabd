#!/bin/env python

from typing import Never

import asyncio
import argparse
import functools as ft
from logging import info
import logging

import sdbus
from sdbus import DbusInterfaceCommonAsync, dbus_method_async, dbus_property_async

class SensorProxy(DbusInterfaceCommonAsync, interface_name="net.hadess.SensorProxy"):
    def __init__(self, bus: sdbus.SdBus|None=None):
        super().__init__()
        self._proxify("net.hadess.SensorProxy", "/net/hadess/SensorProxy", bus=bus)

    @dbus_method_async("", "")
    async def claim_light(self) -> None:
        raise NotImplementedError

    @dbus_property_async("d")
    def light_level(self) -> float:
        raise NotImplementedError

class Login1(DbusInterfaceCommonAsync, interface_name="org.freedesktop.login1.Session"):
    def __init__(self, bus: sdbus.SdBus|None=None):
        super().__init__()
        self._proxify("org.freedesktop.login1", "/org/freedesktop/login1/session/auto", bus=bus)

    @dbus_method_async("ssu", "")
    async def set_brightness(self, backlight: str, device: str, brightness: int) -> None:
        raise NotImplementedError


class Yabd(DbusInterfaceCommonAsync, interface_name="re.bruge.yabd"):

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
    ramp_step = 0.2 # in percent, how much to change brightness per 10ms when ramping. Too high a value might cause flicker

    gamma= 2. # for power scaling

    yield_control_on_brightness_change = False #whether to yield control when the brightness is changed by another application

    ##################### INTERFACES
    login1: Login1
    sensor_proxy: SensorProxy

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
    start_ramp_signal: asyncio.Event
    target_brightness: int | None = None

    def __init__(self, read_args=True, args=None):
        if read_args:
            self.read_args(args)
        super().__init__()
        # get buses
        bus = sdbus.sd_bus_open_system()
        self.login1 = Login1(bus=bus)
        self.sensor_proxy = SensorProxy(bus=bus)

        self.ramp_step_units = int(self.ramp_step * self.max_brightness / 100)
        self.start_ramp_signal = asyncio.Event()

    async def loop(self):
        info("starting up")
        session_bus = sdbus.sd_bus_open_user()
        await self.sensor_proxy.claim_light()
        async def brightness_changed_loop() -> Never:
            async for _, properties, __ in self.sensor_proxy.properties_changed:
                if "LightLevel" in properties:
                    light_level_type, light_level = properties["LightLevel"]
                    assert light_level_type == "d"
                    await self.brightness_changed_handler(light_level)
                else :
                    info(f"got PropertiesChanged signal, but without LightLevel")

        # register our dbus service
        sdbus.set_default_bus(session_bus)
        await sdbus.request_default_bus_name_async("re.bruge.yabd")
        self.export_to_dbus("/re/bruge/yabd", bus=session_bus)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(brightness_changed_loop())
            tg.create_task(self.ramp_routine())

    async def set_brightness_percent(self, brightness_percent, ramp=False):
        info(f"setting brightness to {brightness_percent}%")
        brightness = int(self.max_brightness * brightness_percent / 100)
        await self.set_brightness(brightness, ramp=ramp)

    async def set_brightness(self, brightness, ramp=False):
        if ramp: 
            self.target_brightness = brightness
            self.start_ramp_signal.set()
            return
        self.has_control = True
        self.known_brightness = brightness
        await self.login1.set_brightness(self.subsystem, self.device, brightness)

    async def brightness_changed_handler(self, light_level):
        """Dbus signal handler for brightness changes"""
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
            await self.set_brightness_depending_on_ambient_light(light_level)

    async def set_brightness_depending_on_ambient_light(self, light_level=None):
        info(f"got {light_level=}")
        # find light level
        if light_level is None: #might happen if we call this function directly
            light_level = float(await self.sensor_proxy.light_level)
        light_level = min(light_level, self.max_ambient_brightness) # clip light_level to the max
        brightness_range_size = self.max_selectable_brightness - self.min_selectable_brightness
        light_level_percent = light_level / self.max_ambient_brightness

        # scale brightness depending on ambient light with a power law
        brightness_percent = self.min_selectable_brightness + \
                    brightness_range_size * light_level_percent ** self.gamma
        info(f"brightness_percent = {self.min_selectable_brightness} + {brightness_range_size} * {light_level_percent}^{self.gamma} = {brightness_percent}")

        # apply user multiplier
        brightness_percent = self.multiplier * brightness_percent

        # clip brightness to the min and max
        brightness_percent = max(self.min_selectable_brightness, brightness_percent)
        brightness_percent = min(self.max_selectable_brightness, brightness_percent)

        if self.is_dim:
            brightness_percent= self.dimmed_brightness
        await self.set_brightness_percent(brightness_percent, ramp=self.ramp)

    async def ramp_routine(self):
        while True:
            await self.start_ramp_signal.wait()
            info("starting ramp")
            while True:
                if self.target_brightness is None: break
                current_brightness = self.query_brightness()
                if abs(current_brightness - self.target_brightness) < self.ramp_step_units:
                    break
                delta = self.ramp_step_units if current_brightness < self.target_brightness else -self.ramp_step_units

                await self.set_brightness(current_brightness + delta)
                await asyncio.sleep(10e-3) # 10 ms
            info("stopping ramp")
            self.start_ramp_signal.clear()
            await self.set_brightness(self.target_brightness)
            target_brightness = None


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

    async def set_multiplier_(self, multiplier, in_percent=False, relative=False):
        if in_percent: multiplier = multiplier / 100
        if relative:
            multiplier = self.multiplier + multiplier
        multiplier = max(0, multiplier)
        multiplier = min(5., multiplier) #max multiplier is 500%
        self.multiplier = multiplier
        await self.set_brightness_depending_on_ambient_light()
        if in_percent: return multiplier * 100
        return multiplier

    ##################################### DBUS METHODS. 
    # They all return False if the daemon is not controllable.

    @dbus_method_async("", "b")
    async def dim(self) -> bool:
        if not self.controllable: return False
        info("dimming")
        self.is_dim = True
        await self.set_brightness_depending_on_ambient_light()
        return True

    @dbus_method_async("", "b")
    async def undim(self) -> bool:
        if not self.controllable: return False
        info("undimming")
        self.is_dim = False
        await self.set_brightness_depending_on_ambient_light()
        return True

    @dbus_method_async("d", "v")
    async def change_multiplier(self, change: float) -> tuple[str, float|bool]:
        if not self.controllable: return ("b", False)
        info(f"changing multiplier by {change}")
        new_multiplier = await self.set_multiplier_(change, in_percent=True, relative=True)
        return ("d", new_multiplier)

    @dbus_method_async("d", "v")
    async def set_multiplier(self, new_multiplier: float) -> tuple[str, float|bool]:
        if not self.controllable: return ("b", False)
        info(f"setting multiplier to {new_multiplier}")
        new_multiplier = await self.set_multiplier_(new_multiplier, in_percent=True)
        return ("d", new_multiplier)


    @classmethod
    def argument_parser(cls, parser=None):
        if parser is None:
            parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument("--max-brightness", type=float, help=f"max selectable brightness in percent", default=cls.max_selectable_brightness)
        parser.add_argument("--min-brightness", type=float, help=f"min selectable brightness in percent", default=cls.min_selectable_brightness)
        parser.add_argument("--dimmed-brightness", type=float, help=f"brightness when the screen is dimmed through command", default=cls.dimmed_brightness)
        parser.add_argument("--max-ambient-brightness", type=float, 
                            help=f"ambient brightness (in lumen) corresponding to the max", default=cls.max_ambient_brightness)
        parser.add_argument("--device", type=str, help=f"device to control", default=cls.device)
        parser.add_argument("--subsystem", type=str, help=f"subsystem to control", default=cls.subsystem)
        parser.add_argument("--yield-control", action=argparse.BooleanOptionalAction, help=f"If this option is activated and the screen brightness is changed by another application, this daemon stops controlling it temporarily.", default=cls.controllable)
        parser.add_argument("--change-to-get-control-back", type=float, help=f"""how much the ambient brightness has to change to get control back (default {cls.ambient_brightness_change_to_get_control_back} lumen). 
    If `--yield-control` is activated and another program changes the screen brightness, the daemon stops controlling the screen brightness. 
    But if the ambient brightness changes more than this amount, it takes control back. set to 0 to disable this behaviour""", 
                            default=cls.ambient_brightness_change_to_get_control_back)
        parser.add_argument("--controllable", action=argparse.BooleanOptionalAction, help=f"whether to respond to dbus commands (dim, undim, change_multiplier, set_multiplier)", default=cls.controllable)
        parser.add_argument("--ramp", action=argparse.BooleanOptionalAction, help=f"ramp brightness changes", default=cls.ramp)
        parser.add_argument("--ramp-step", type=float, help=f"how much to change the brightness every 10 ms when ramping (in percent)", default=cls.ramp_step)
        parser.add_argument("--gamma", type=float, help=f"gamma for power scaling. 1 means proportional. Lower values mean that as the room gets brighter, the screen gets brighter faster. Raise if the backlight is too bright in the dark.", default=cls.gamma)
        return parser

    def read_args(self, args=None):
        if args is None:
            parser = self.argument_parser()
            args = parser.parse_args()
        self.max_selectable_brightness = args.max_brightness
        self.min_selectable_brightness = args.min_brightness
        self.dimmed_brightness = args.dimmed_brightness
        self.max_ambient_brightness = args.max_ambient_brightness
        self.ambient_brightness_change_to_get_control_back = args.change_to_get_control_back
        self.device = args.device
        self.controllable = args.controllable
        self.subsystem = args.subsystem
        self.yield_control_on_brightness_change = args.yield_control
        self.ramp = args.ramp
        self.ramp_step = args.ramp_step
        self.gamma = args.gamma

def argument_parser():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    subparsers = parser.add_subparsers(dest="command")
    parser.add_argument("-v", "--verbose", 
                        action="store_const", 
                        dest="loglevel", 
                        const=logging.INFO,  
                        default=logging.WARNING,
                        help="enable logging")
    daemon_parser = subparsers.add_parser("run", help="run the daemon", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    Yabd.argument_parser(daemon_parser)
    subparsers.add_parser("dim", help="dim the screen")
    subparsers.add_parser("undim", help="undim the screen")
    change_multiplier_parser = subparsers.add_parser("change_multiplier", help="change the brightness multiplier by a relative amount")
    change_multiplier_parser.add_argument("change", type=float, help="change the brightness multiplier by this amount (in percent)")
    set_multiplier_parser = subparsers.add_parser("set_multiplier", help="set the brightness multiplier to a specific value")
    set_multiplier_parser.add_argument("new_multiplier", type=float, help="set the brightness multiplier to this value (in percent)")
    return parser

def run_command(command, args, *,  signature=""):
    bus = sdbus.sd_bus_open_user()
    daemon_proxy = Yabd.new_proxy("re.bruge.yabd", "/re/bruge/yabd", bus=bus)
    if command == "dim":
        result = asyncio.run(daemon_proxy.dim())
    elif command == "undim":
        result = asyncio.run(daemon_proxy.undim())
    elif command == "change_multiplier":
        _, result = asyncio.run(daemon_proxy.change_multiplier(args.change))
    elif command == "set_multiplier":
        _, result = asyncio.run(daemon_proxy.set_multiplier(args.new_multiplier))
    else:
        raise ValueError(f"unknown command {command}")

    if isinstance(result, bool):
        if result: info("success")
        else: logging.error("failed: daemon is not controllable")
    else: print(result)

def main():
    parser = argument_parser()
    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)
    if args.command == "run":
        daemon = Yabd(read_args=True, args=args)
        asyncio.run(daemon.loop())
    else:
        run_command(args.command, args)
    
if __name__ == "__main__":
    main()
