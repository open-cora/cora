"""The get_device slice, re-exported so callers read `.bind`."""

from aroc.equipment.features.get_device.handler import Handler, bind
from aroc.equipment.features.get_device.query import GetDevice
from aroc.equipment.features.get_device.route import router

__all__ = ["GetDevice", "Handler", "bind", "router"]
