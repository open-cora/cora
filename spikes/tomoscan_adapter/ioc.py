"""A soft IOC carrying the PVs TomoScan's lifecycle reads and writes.

No hardware and no EPICS installation: caproto serves Channel Access from
Python, and pyEpics connects to it the same way it connects to a real IOC.
What runs against this is the real TomoScan code, unmodified, so the
transitions observed are the ones its own lines produce.

The record types come from `tomoScanApp/Db/tomoScan.template` in the
TomoScan repository, which is where a beamline's PVs are declared. Enum
choices matter and are copied exactly: TomoScan reads several of these
with `get(as_string=True)` and compares the result to a literal, so a
wrong choice list changes the path taken rather than just the label.

Only the PVs the lifecycle touches are here. The full database is about
four times this, almost all of it detector and motor configuration that
nothing in the lifecycle reads.
"""

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty, run

PREFIX = "2bmb:TomoScan:"
"""Stands in for a beamline's `$(P)$(R)`. Any prefix would do."""


def enum(*choices: str) -> dict[str, object]:
    """A record TomoScan reads back as one of a fixed set of words."""
    return {"dtype": ChannelType.ENUM, "enum_strings": choices}


def text(value: str = "") -> dict[str, object]:
    """A record TomoScan reads back as a string."""
    return {"value": value, "string_encoding": "utf-8", "report_as_string": True}


class TomoScanPVs(PVGroup):
    """The lifecycle's own PVs, and the detector PVs it writes through."""

    # The three that say what is happening. Everything in FINDINGS turns on
    # how little these carry.
    ScanStatus = pvproperty(**text("Idle"))
    StartScan = pvproperty(value=0)
    AbortScan = pvproperty(value=0)

    # Scan configuration, read into instance variables by begin_scan.
    ExposureTime = pvproperty(value=0.1)
    RotationStart = pvproperty(value=0.0)
    RotationStep = pvproperty(value=0.25)
    RotationStop = pvproperty(value=180.0)
    RotationResolution = pvproperty(value=0.0001)
    RotationMaxSpeed = pvproperty(value=30.0)
    Rotation = pvproperty(value=0.0)
    RotationHomF = pvproperty(value=0)
    NumAngles = pvproperty(value=720)
    ReturnRotation = pvproperty(**enum("No", "Yes", "Home"))
    NumDarkFields = pvproperty(value=20)
    DarkFieldMode = pvproperty(**enum("Start", "End", "Both", "None"))
    NumFlatFields = pvproperty(value=20)
    FlatFieldMode = pvproperty(**enum("Start", "End", "Both", "None"))
    FrameType = pvproperty(**enum("DarkField", "FlatField", "Projection"))

    # Where the data goes. Until ScanUUID this was the closest thing a run
    # had to a name, and it is still the only one written at the end.
    FilePath = pvproperty(**text("/local/data/"))
    FileName = pvproperty(**text("sample"))
    FullFileName = pvproperty(**text(""))
    HDF5Location = pvproperty(**text("/exchange/data"))
    HDF5ProjectionLocation = pvproperty(**text("/exchange/data"))
    OverwriteWarning = pvproperty(**enum("No", "Yes"))

    # Declared by `tomoScan_2BM.template` and `tomoScan_19BM.template`, not
    # by the base one. A station's answer to run identity rather than the
    # engine's, which is why FINDINGS treats it as 2-BM's and not TomoScan's.
    ScanUUID = pvproperty(**text("Unknown"))

    # The areaDetector file plugin, which TomoScan drives rather than reads.
    FPFilePath = pvproperty(**text("/local/data/"))
    FPFilePathRBV = pvproperty(**text("/local/data/"))
    FPFileName = pvproperty(**text("sample"))
    FPFileNameRBV = pvproperty(**text("sample"))
    FPFileNumber = pvproperty(value=1)
    FPFileTemplate = pvproperty(**text("%s%s_%3.3d.h5"))
    FPFullFileName = pvproperty(**text("/local/data/sample_001.h5"))
    FPCapture = pvproperty(value=0)

    # The camera, and the shutter the beamline closes afterwards.
    CamAcquire = pvproperty(value=0)
    CamAcquireTime = pvproperty(value=0.1)
    AutoCloseShutter = pvproperty(value=1)
    CloseShutter = pvproperty(value=0)
    OpenShutter = pvproperty(value=0)

    # Progress, which a beamline updates as frames arrive.
    ImagesCollected = pvproperty(**text("0"))
    ImagesSaved = pvproperty(**text("0"))


WATCHED = (
    "ScanStatus",
    "StartScan",
    "AbortScan",
    "ScanUUID",
    "FrameType",
    "FullFileName",
    "ImagesCollected",
    "ImagesSaved",
    "CamAcquire",
    "FPCapture",
    "Rotation",
)
"""What a monitoring client subscribes to.

Chosen as everything a reporter could plausibly learn a run's life from.
That it is a guess is itself the point: nothing here declares which PVs
carry the lifecycle, so a client picks a set and hopes.
"""


def serve() -> None:
    run(TomoScanPVs(prefix=PREFIX).pvdb, log_pv_names=False)


if __name__ == "__main__":
    serve()
