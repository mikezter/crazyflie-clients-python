#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#     ||          ____  _ __
#  +------+      / __ )(_) /_______________ _____  ___
#  | 0xBC |     / __  / / __/ ___/ ___/ __ `/_  / / _ \
#  +------+    / /_/ / / /_/ /__/ /  / /_/ / / /_/  __/
#   ||  ||    /_____/_/\__/\___/_/   \__,_/ /___/\___/
#
#  Copyright (C) 2011-2013 Bitcraze AB
#
#  Crazyflie Nano Quadcopter Client
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
#  USA.
"""
Driver for reading data from the PySDL2 API. Maps to 360-like game controllers
using the SDL2 GameController APIs. Look at pysdl2.py for a more general
approach using SDL2 Joystick API.
Used from Inpyt.py for reading input data.
"""
import logging
import sys
import time
from threading import Thread

from queue import Queue

if sys.platform.startswith('linux'):
    raise Exception("No SDL2 support on Linux")

try:
    from sdl2 import *
    import sdl2.ext
    import sdl2.hints
except ImportError as e:
    raise Exception("sdl2 library probably not installed ({})".format(e))

__author__ = '@mikezter'
__all__ = ['SDL2GameController']

logger = logging.getLogger(__name__)

MODULE_MAIN = "SDL2GameController"
MODULE_NAME = "SDL2GameControllerAPI"

# TODO: should be a config value
DEADZONE = 2000


class _SDLEventDispatcher(Thread):
    """Wrapper to read all SDL2 events from the global queue and distribute
    them to the different devices"""

    def __init__(self, callback):
        Thread.__init__(self)
        self._callback = callback
        self.daemon = True
        # SDL2 will Seg Fault on Linux if you read events after you
        # have closed a device (and without opening a new one). Even if you
        # have two devices open, it will crash after one.
        self.enable = False

    def run(self):
        while True:
            if self.enable:
                for ev in sdl2.ext.get_events():
                    try:
                        if self._callback:
                            self._callback(ev.jdevice.which, ev)
                    except AttributeError:
                        pass
            time.sleep(0.01)


class _JS():
    """Wrapper for one input device

       Buttons:
        SDL_CONTROLLER_BUTTON_INVALID = -1
        SDL_CONTROLLER_BUTTON_A
        SDL_CONTROLLER_BUTTON_B
        SDL_CONTROLLER_BUTTON_X
        SDL_CONTROLLER_BUTTON_Y
        SDL_CONTROLLER_BUTTON_BACK
        SDL_CONTROLLER_BUTTON_GUIDE
        SDL_CONTROLLER_BUTTON_START
        SDL_CONTROLLER_BUTTON_LEFTSTICK
        SDL_CONTROLLER_BUTTON_RIGHTSTICK
        SDL_CONTROLLER_BUTTON_LEFTSHOULDER
        SDL_CONTROLLER_BUTTON_RIGHTSHOULDER
        SDL_CONTROLLER_BUTTON_DPAD_UP
        SDL_CONTROLLER_BUTTON_DPAD_DOWN
        SDL_CONTROLLER_BUTTON_DPAD_LEFT
        SDL_CONTROLLER_BUTTON_DPAD_RIGHT
        SDL_CONTROLLER_BUTTON_MAX

       Axis:
        SDL_CONTROLLER_AXIS_INVALID = -1
        SDL_CONTROLLER_AXIS_LEFTX
        SDL_CONTROLLER_AXIS_LEFTY
        SDL_CONTROLLER_AXIS_RIGHTX
        SDL_CONTROLLER_AXIS_RIGHTY
        SDL_CONTROLLER_AXIS_TRIGGERLEFT
        SDL_CONTROLLER_AXIS_TRIGGERRIGHT
        SDL_CONTROLLER_AXIS_MAX
    """

    def __init__(self, sdl_index, name):
        self.axes = []
        self.buttons = []
        self.name = MODULE_NAME
        self._j = None
        self._index = sdl_index
        self._name = name
        self._event_queue = Queue()

    def open(self):
        self._j = SDL_GameControllerOpen(self._index)

        self.axes = list(0 for i in range(SDL_CONTROLLER_AXIS_MAX))
        self.buttons = list(0 for i in range(SDL_CONTROLLER_BUTTON_MAX + 2))


    def close(self):
        if self._j:
            SDL_GameControllerClose(self._j)
        self._j = None

    def add_event(self, event):
        self._event_queue.put(event)

    def read(self):
        while not self._event_queue.empty():
            e = self._event_queue.get_nowait()
            if e.type == SDL_CONTROLLERAXISMOTION:
                v, a = e.caxis.value, e.caxis.axis
                if abs(v) < DEADZONE:
                    v = 0

                setting = v / 32767.0

                logger.debug("Read Axis [{}]: {}".format(a, v))
                self.axes[a] = setting

                if a == SDL_CONTROLLER_AXIS_TRIGGERLEFT:
                    self.buttons[-1] = 1 if v > 0 else 0

                if a == SDL_CONTROLLER_AXIS_TRIGGERRIGHT:
                    self.buttons[-2] = 1 if v > 0 else 0

            if e.type == SDL_CONTROLLERBUTTONDOWN:
                self.buttons[e.cbutton.button] = 1

            if e.type == SDL_CONTROLLERBUTTONUP:
                self.buttons[e.cbutton.button] = 0

        return [self.axes, self.buttons]


class SDL2GameController():
    """Used for reading data from input devices using the
       PySDL2 GameController API."""

    def __init__(self):
        SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER)
        SDL_SetHint(sdl2.hints.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS,
                    b"1")

        sdl2.ext.init()
        self._js = {}
        self.name = MODULE_NAME
        self._event_dispatcher = _SDLEventDispatcher(self._dispatch_events)
        self._event_dispatcher.start()
        self._devices = []

    def open(self, device_id):
        """Initialize the reading and open the device with deviceId and set
        the mapping for axis/buttons using the inputMap"""
        self._event_dispatcher.enable = True
        self._js[device_id].open()

    def close(self, device_id):
        """Close the device"""
        self._event_dispatcher.enable = False
        self._js[device_id].close()

    def read(self, device_id):
        """Read input from the selected device."""
        return self._js[device_id].read()

    def _dispatch_events(self, device_id, event):
        self._js[device_id].add_event(event)

    def devices(self):
        """List all the available devices."""
        logger.info("Looking for devices")
        names = []
        if len(self._devices) == 0:

            nbrOfInputs = SDL_NumJoysticks()
            logger.info("Found {} devices".format(nbrOfInputs))

            for sdl_index in range(0, nbrOfInputs):
                if not SDL_IsGameController:
                    continue

                name = \
                    SDL_GameControllerNameForIndex(sdl_index).decode("UTF-8")
                if names.count(name) > 0:
                    name = "{0} #{1}".format(name, names.count(name) + 1)
                names.append(name)

                self._devices.append({"id": sdl_index, "name": name})

                self._js[sdl_index] = _JS(sdl_index, name)

        return self._devices
