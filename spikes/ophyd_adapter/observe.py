"""Build real ophyd devices against a soft IOC and record what they say.

The question this spike exists for is what an equipment model can honestly
hold. Three sub-questions, one scenario each, and a fourth scenario for
the thing the other three kept walking past.

  identity     does a device have a name that survives a restart
  fault        is a fault durable, or only visible to whoever was watching
  outage       what a client reports about a device it cannot reach
  boundary     where ophyd itself thinks one device stops

## What is real here and what is not

Real, imported from the installed package and not overridden: `Device`,
`Component`, `EpicsMotor`, `EpicsSignal`, `EpicsSignalRO`, and every
method called on them. `read`, `read_configuration`, `describe`,
`walk_signals`, `wait_for_connection`, `connected`, `alarm_severity` and
`alarm_status` are ophyd's own. The motor is caproto's own `motor` record
simulator, so `EpicsMotor` connects to a full motor record rather than to
a set of PVs chosen to please it.

Not real: the camera's records are hand-written rather than an
areaDetector database, and the temperature alarm is set by the IOC rather
than computed by a record from its HIHI and HHSV fields. Neither changes
what is measured, because what is measured is what a CLIENT can see of an
alarm, not how the record arrived at one.

Run it with:

    uv run --with caproto --with ophyd --with pyepics \\
        python spikes/ophyd_adapter/observe.py
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from pathlib import Path
from typing import Any

# Both halves of the port move, because the client searches on the same
# number the server listens on. See SERVER_PORT in ioc.py for why it is
# not the default.
os.environ.setdefault("EPICS_CA_ADDR_LIST", "127.0.0.1")
os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")
os.environ.setdefault("EPICS_CA_SERVER_PORT", "5074")
os.environ.setdefault("EPICS_CAS_SERVER_PORT", "5074")
# caproto otherwise announces itself to the broadcast address, which a
# laptop refuses, and the refusal prints a traceback per beacon that
# buries the output. Nothing measured here depends on beacons.
os.environ.setdefault("EPICS_CAS_BEACON_ADDR_LIST", "127.0.0.1")
os.environ.setdefault("EPICS_CAS_AUTO_BEACON_ADDR_LIST", "NO")

HERE = Path(__file__).parent
OUT = HERE / "observations.json"

SETTLE_SECONDS = 1.0
"""How long to let monitors deliver before reading what they saw."""

CONNECT_TIMEOUT = 20.0
"""Generous, because a motor record is twenty PVs and CI machines are slow."""


def station_class() -> Any:
    """The device tree a beamline's startup profile would build.

    Written the way those are written: a class per assembly, components
    naming PV suffixes, and `kind` deciding what counts as a reading and
    what counts as configuration. Nothing here is ophyd-unusual, which is
    the point.
    """
    from ophyd import Component, Device, EpicsMotor, EpicsSignal, EpicsSignalRO

    class Camera(Device):
        acquire = Component(EpicsSignal, "cam1:Acquire")
        state = Component(EpicsSignalRO, "cam1:DetectorState_RBV", string=True)
        temperature = Component(EpicsSignalRO, "cam1:Temperature_RBV")
        acquire_time = Component(EpicsSignal, "cam1:AcquireTime", kind="config")

    class Experiment(Device):
        """The user fields, declared as configuration the way a profile would."""

        user_name = Component(EpicsSignal, "UserName", string=True, kind="config")
        user_last_name = Component(EpicsSignal, "UserLastName", string=True, kind="config")
        user_badge = Component(EpicsSignal, "UserBadge", string=True, kind="config")
        user_email = Component(EpicsSignal, "UserEmail", string=True, kind="config")
        user_institution = Component(
            EpicsSignal, "UserInstitution", string=True, kind="config"
        )
        proposal_number = Component(EpicsSignal, "ProposalNumber", string=True, kind="config")
        esaf_number = Component(EpicsSignal, "ESAFNumber", string=True, kind="config")

    class Station(Device):
        sample_x = Component(EpicsMotor, "m1")
        camera = Component(Camera, "")
        experiment = Component(Experiment, "", kind="config")

    return Station


def identity(station: Any, prefix: str) -> dict[str, Any]:
    """What names this device has, and which of them the facility knows."""
    from ophyd import EpicsSignal

    # The same hardware, built by a second profile that chose other words.
    # Nothing rejects this, and nothing anywhere records that the two are
    # the same device.
    rival = station_class()(prefix, name="tomo")
    rival.wait_for_connection(timeout=CONNECT_TIMEOUT)

    desc = EpicsSignal(prefix + "m1.DESC", name="desc", string=True)
    desc.wait_for_connection(timeout=CONNECT_TIMEOUT)
    as_served = desc.get()
    desc.put("sample x translation", wait=True)
    time.sleep(SETTLE_SECONDS)
    after_operator = desc.get()

    return {
        "scenario": "identity",
        "asks": "does a device have a name that survives a restart",
        "ophyd_name": station.name,
        "ophyd_name_of_a_part": station.sample_x.user_readback.name,
        "dotted_name": station.sample_x.user_readback.dotted_name,
        "prefix": station.prefix,
        "pvname": station.sample_x.user_readback.pvname,
        "same_hardware_other_profile": {
            "ophyd_name": rival.name,
            "ophyd_name_of_a_part": rival.sample_x.user_readback.name,
            "pvname": rival.sample_x.user_readback.pvname,
            "connected": rival.connected,
        },
        "motor_desc_as_served": as_served,
        "motor_desc_after_an_operator_writes_it": after_operator,
        "desc_is_writable_by_any_client": True,
    }


def fault(station: Any, prefix: str) -> dict[str, Any]:
    """Whether a fault is readable after the fact, or only while it lasts."""
    from ophyd import EpicsSignal

    thermostat = EpicsSignal(prefix + "cam1:SetTemperature", name="thermostat")
    thermostat.wait_for_connection(timeout=CONNECT_TIMEOUT)
    temperature = station.camera.temperature

    def snapshot(label: str) -> dict[str, Any]:
        return {
            "when": label,
            "value": temperature.get(),
            "alarm_severity": temperature.alarm_severity,
            "alarm_status": str(temperature.alarm_status),
            "read": temperature.read(),
            "describe_keys": sorted(next(iter(temperature.describe().values())).keys()),
        }

    before = snapshot("before")
    thermostat.put(45.0, wait=True)
    time.sleep(SETTLE_SECONDS)
    during = snapshot("while the camera is too hot")
    thermostat.put(20.0, wait=True)
    time.sleep(SETTLE_SECONDS)
    after = snapshot("after it cools")

    reading_names = sorted(next(iter(during["read"].values())).keys())
    return {
        "scenario": "fault",
        "asks": "is a fault durable, or only visible to whoever was watching",
        "snapshots": [before, during, after],
        "fields_a_reading_carries": reading_names,
        "alarm_is_in_the_reading": any("alarm" in k or "sever" in k for k in reading_names),
        "alarm_is_in_describe": any(
            "alarm" in k or "sever" in k for k in during["describe_keys"]
        ),
    }


def probe(signal: Any) -> dict[str, Any]:
    """Read one signal in a fixed order, because the order changes the answer.

    `alarm_severity` is served from metadata ophyd caches, and a `get`
    refreshes that cache. So the severity read before a get and the one
    read after it can differ, and which an adapter sees depends on
    whether it happened to read the value first. Both are recorded rather
    than one being chosen.
    """
    before = signal.alarm_severity
    try:
        value: Any = signal.get(timeout=2)
    except Exception as error:  # noqa: BLE001 - recording it is the point
        value = f"raised {type(error).__name__}"
    try:
        timestamp = next(iter(signal.read().values()))["timestamp"]
    except Exception as error:  # noqa: BLE001
        timestamp = f"raised {type(error).__name__}"
    return {
        "connected": signal.connected,
        "severity_before_a_get": before,
        "get": value,
        "severity_after_a_get": signal.alarm_severity,
        "reading_timestamp": timestamp,
    }


def outage(station: Any, prefix: str, server: Any, serve: Any) -> dict[str, Any]:
    """What a client says about a device it can no longer reach.

    The camera is left in alarm on purpose. A client that keeps reporting
    the last thing it saw is wrong in one direction here, and wrong in
    the other if the device was healthy when the link dropped.
    """
    from ophyd import EpicsSignal

    thermostat = EpicsSignal(prefix + "cam1:SetTemperature", name="thermostat")
    thermostat.wait_for_connection(timeout=CONNECT_TIMEOUT)
    thermostat.put(45.0, wait=True)
    time.sleep(SETTLE_SECONDS)
    temperature = station.camera.temperature
    while_up = probe(temperature)

    server.terminate()
    server.join()
    time.sleep(5)
    while_down = probe(temperature)

    restarted = multiprocessing.Process(target=serve, daemon=True)
    restarted.start()
    time.sleep(8)
    after_restart = probe(temperature)

    return {
        "scenario": "outage",
        "asks": "what a client reports about a device it cannot reach",
        "while_up": while_up,
        "while_down": while_down,
        "after_restart": after_restart,
        "the_camera_was_in_alarm_when_the_link_dropped": True,
        "server": restarted,
    }


def boundary(station: Any) -> dict[str, Any]:
    """Where ophyd itself thinks one device stops."""
    signals = list(station.walk_signals())
    configuration = station.read_configuration()
    # Selected by which sub-device declared them, not by a word in the
    # key. A substring match on "user" is the obvious way to write this
    # and it is wrong: a motor record's user coordinate fields are not
    # about a person. What that match would have caught is recorded below
    # so whoever writes a redaction rule sees the trap before setting it.
    from_experiment = set(station.experiment.read_configuration())
    personal = [key for key in configuration if key in from_experiment]
    near_miss = [
        key for key in configuration if "user" in key and key not in from_experiment
    ]
    return {
        "scenario": "boundary",
        "asks": "where ophyd itself thinks one device stops",
        "top_level_components": list(station.component_names),
        "components_per_child": {
            name: list(getattr(station, name).component_names)
            for name in station.component_names
        },
        "signals_beneath_one_device": len(signals),
        "reading_keys": list(station.read()),
        "configuration_keys": list(configuration),
        "counts": {
            "signals": len(signals),
            "readings": len(station.read()),
            "configuration": len(configuration),
        },
        "personal_data_in_configuration": personal,
        "matches_user_but_is_not_a_person": near_miss,
    }


def main() -> None:
    from ioc import PREFIX, serve

    server = multiprocessing.Process(target=serve, daemon=True)
    server.start()
    time.sleep(4)

    station = station_class()(PREFIX, name="station")
    station.wait_for_connection(timeout=CONNECT_TIMEOUT)
    time.sleep(SETTLE_SECONDS)

    scenarios = [identity(station, PREFIX), fault(station, PREFIX), boundary(station)]
    # Last, because it takes the IOC down and brings it back.
    ending = outage(station, PREFIX, server, serve)
    still_running = ending.pop("server")
    scenarios.append(ending)

    OUT.write_text(json.dumps(scenarios, indent=2, default=str) + "\n", encoding="utf-8")
    still_running.terminate()
    report(scenarios)


def report(scenarios: list[dict[str, Any]]) -> None:
    by_name = {scenario["scenario"]: scenario for scenario in scenarios}

    one = by_name["identity"]
    print("\n=== identity: does a device have a name that survives a restart ===")
    print(f"   ophyd name          {one['ophyd_name_of_a_part']!r}")
    print(f"   same PV, 2nd profile{'':<1}{one['same_hardware_other_profile']['ophyd_name_of_a_part']!r}")
    print(f"   the PV              {one['pvname']!r}")
    print(f"   motor DESC served   {one['motor_desc_as_served']!r}")
    print(f"   after an operator   {one['motor_desc_after_an_operator_writes_it']!r}")

    two = by_name["fault"]
    print("\n=== fault: is it durable, or only visible while it lasts ===")
    print(f"   {'when':<28} {'value':<8} {'severity':<9} status")
    for snapshot in two["snapshots"]:
        print(
            f"   {snapshot['when']:<28} {snapshot['value']:<8} "
            f"{snapshot['alarm_severity']!s:<9} {snapshot['alarm_status']}"
        )
    print(f"   a reading carries: {two['fields_a_reading_carries']}")
    print(f"   alarm in the reading: {two['alarm_is_in_the_reading']}")

    four = by_name["outage"]
    print("\n=== outage: what a client says about a device it cannot reach ===")
    print(f"   {'':<14} {'connected':<10} {'sev before get':<15} {'sev after get':<14} get")
    for label in ("while_up", "while_down", "after_restart"):
        state = four[label]
        print(
            f"   {label:<14} {state['connected']!s:<10} "
            f"{state['severity_before_a_get']!s:<15} "
            f"{state['severity_after_a_get']!s:<14} {state['get']}"
        )

    three = by_name["boundary"]
    print("\n=== boundary: where ophyd thinks one device stops ===")
    print(f"   components         {three['top_level_components']}")
    print(f"   signals beneath    {three['counts']['signals']}")
    print(f"   readings           {three['counts']['readings']}")
    print(f"   configuration      {three['counts']['configuration']}")
    print(f"   of which personal  {len(three['personal_data_in_configuration'])}")
    for key in three["personal_data_in_configuration"]:
        print(f"      {key}")
    print(f"   says user, is not  {three['matches_user_but_is_not_a_person']}")

    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
