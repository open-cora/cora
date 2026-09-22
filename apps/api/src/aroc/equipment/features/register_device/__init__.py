"""The register_device slice, re-exported so callers read `.bind`."""

from aroc.equipment.features.register_device.command import RegisterDevice
from aroc.equipment.features.register_device.decider import decide
from aroc.equipment.features.register_device.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from aroc.equipment.features.register_device.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "RegisterDevice",
    "bind",
    "decide",
    "router",
]
