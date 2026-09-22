"""The fault_device slice, re-exported so callers read `.bind`."""

from aroc.equipment.features.fault_device.command import FaultDevice
from aroc.equipment.features.fault_device.decider import decide
from aroc.equipment.features.fault_device.handler import Handler, bind
from aroc.equipment.features.fault_device.route import router

__all__ = ["FaultDevice", "Handler", "bind", "decide", "router"]
