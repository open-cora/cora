"""The list_devices slice, re-exported so callers read `.bind`."""

from aroc.equipment.features.list_devices.handler import Handler, bind
from aroc.equipment.features.list_devices.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListDevices,
)
from aroc.equipment.features.list_devices.route import router

__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "Handler", "ListDevices", "bind", "router"]
