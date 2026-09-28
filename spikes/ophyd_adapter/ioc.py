"""A soft IOC carrying the PVs a beamline station publishes.

No hardware and no EPICS installation: caproto serves Channel Access from
Python, and pyEpics connects to it the same way it connects to a real IOC.
What runs against this is real ophyd, unmodified, so the device tree
observed is the one ophyd's own classes build.

Three groups of records, chosen for the three questions in FINDINGS:

  a motor      caproto's own motor record simulator, which is a full
               `motor` record and so carries DESC, MSTA and the limit
               switches an `EpicsMotor` expects
  a camera     the handful of records a detector publishes that a client
               would watch, plus a thermostat to drive one into alarm
  a proposal   the user fields `tomoScan_2BM.template` declares, copied
               because section 8 of the TomoScan findings is about them

The camera group is hand-written rather than an areaDetector database.
That is a difference in breadth and not in kind: every record here is
served by the same caproto machinery as the motor, and nothing measured
turns on how many of a real detector's several hundred records exist.
"""

from caproto import AlarmSeverity, AlarmStatus
from caproto.ioc_examples.fake_motor_record import FakeMotor
from caproto.server import PVGroup, SubGroup, pvproperty, run

PREFIX = "2bmb:"
"""Stands in for a beamline's `$(P)`. Any prefix would do."""

SERVER_PORT = 5074
"""Not the Channel Access default of 5064, and deliberately.

A sibling spike serves its own IOC on the default port, and two caproto
servers cannot both bind it: whichever starts second fails, and its
client then searches and times out. Moving this one leaves both runnable
at once. `observe.py` sets the matching client variable.
"""

FAULT_ABOVE = 30.0
"""Degrees above which the thermostat puts the camera into a MAJOR alarm.

A real `ai` record computes this from its own HIHI and HHSV fields. This
one is told, which changes who decided and not what a client can see.
"""


def text(value: str = "") -> dict[str, object]:
    """A record a client reads back as a string."""
    return {"value": value, "string_encoding": "utf-8", "report_as_string": True}


class Camera(PVGroup):
    """What a detector publishes, and a thermostat to make it unhappy."""

    Acquire = pvproperty(value=0)
    AcquireTime = pvproperty(value=0.1)
    DetectorState_RBV = pvproperty(**text("Idle"))
    Temperature_RBV = pvproperty(value=20.0, alarm_group="camera_temperature")
    """The record a scenario drives into alarm.

    `alarm_group` is not decoration. Every `pvproperty` in a caproto
    PVGroup shares one `ChannelAlarm` unless told otherwise, and a value
    write clears it, so the client's put to `SetTemperature` below would
    clear the severity this group had just set on the readback. A real
    IOC has one alarm per record. This restores that, and without it the
    fault scenario measures the rig rather than EPICS.
    """

    SetTemperature = pvproperty(value=20.0)
    """Where a scenario writes to drive the camera into and out of alarm.

    Separate from the readback because the two are separate on a real
    detector, and because caproto clears a channel's alarm on a value
    write, so the severity has to be set after the value rather than with
    it.
    """

    @SetTemperature.putter
    async def SetTemperature(self, instance, value: float) -> float:
        hot = value > FAULT_ABOVE
        await self.Temperature_RBV.write(value)
        await self.Temperature_RBV.alarm.write(
            status=AlarmStatus.HIHI if hot else AlarmStatus.NO_ALARM,
            severity=AlarmSeverity.MAJOR_ALARM if hot else AlarmSeverity.NO_ALARM,
        )
        return value


class Station(PVGroup):
    """One motor, one camera, and the people whose beamtime it is."""

    sample_x = SubGroup(FakeMotor, velocity=20.0, prefix="m1")
    cam = SubGroup(Camera, prefix="cam1:")

    # Copied from tomoScan_2BM.template. Present because a spike about
    # what an adapter sweeps up should sweep up what a beamline actually
    # publishes.
    UserName = pvproperty(**text("Ada"))
    UserLastName = pvproperty(**text("Lovelace"))
    UserBadge = pvproperty(**text("88213"))
    UserEmail = pvproperty(**text("ada@example.org"))
    UserInstitution = pvproperty(**text("Analytical Engine Co"))
    ProposalNumber = pvproperty(**text("GUP-77104"))
    ESAFNumber = pvproperty(**text("ESAF-220417"))


def serve() -> None:
    run(Station(prefix=PREFIX).pvdb, log_pv_names=False)


if __name__ == "__main__":
    serve()
