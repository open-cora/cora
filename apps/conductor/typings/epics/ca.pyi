"""The one Channel Access call this project makes below the `PV` layer.

Clearing a channel is not reachable through `PV`. `PV.disconnect` keeps
the library's entry for the name, so a channel built for that name
afterwards is handed the unresolved one back, along with the retry
interval that widened while its server was away. This is the call that
drops the entry, and `TomoscanEngine._discard` is its only caller.
"""

from ctypes import c_long

def clear_channel(chid: c_long, /) -> int: ...
