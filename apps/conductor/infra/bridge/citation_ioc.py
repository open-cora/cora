"""The two citation records, served where an acquisition server has none.

A conductor writes the keeper's execution and step ids into records beside
the acquisition server's own, so that whatever watches that server can say
which dispatched step a scan belonged to. At a station whose TomoScan
database carries those two records, that is the whole arrangement and this
process has no reason to exist. At one whose database does not, adding them
means restarting an IOC the beamline is using, and this serves them instead.

## Why a separate server is not a workaround

Channel Access resolves a name and not a server, so a record served from
here is the same record to every client that asks for it. A conductor
writing it, a reporter reading it and a detector's attributes file naming
it all behave exactly as they would against the station's own database.

What makes this temporary is the other direction. Once the two records are
added upstream, two servers answer one name, and that race is one this
deployment has already met: every reference at this beamline once drew a
duplicate-server warning and answered from a machine nobody meant to serve
it. So retiring this unit belongs in the same change that lands the records
in the station's database, not in a later tidy-up.

## What it deliberately does not do

It serves no other record of the acquisition server's and reads none. A
process mirroring part of that database would be a second answer to
questions the station already answers, and the first disagreement between
them would be invisible to both. Two records, written by one client and
read by another, is all of it.

The ids do not reach the data file from here. They would not reach it from
the station's database either: what puts a value in the file is the
detector's attributes XML together with the file plugin's layout, and those
name records explicitly and resolve them over Channel Access like any other
client. That work is the same whichever server answers.

## Why both records start empty

A record holds its last value, so a scan run with no citation after one
that had ids would read those ids back and claim to belong to a step it had
nothing to do with. A conductor clears both when it walks a procedure that
cites nothing, which closes that for the runs it drives. Nothing here is
restored from a settings file, so a restart closes it for the rest.
"""

from __future__ import annotations

import sys
from typing import Any, Final

from caproto import ChannelType
from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run

TEXT_LENGTH: Final = 256
"""The width TomoScan's own templates give a string record.

Matched rather than chosen. A uuid needs thirty six characters and any
smaller record would hold one, but a client reading this and a client
reading the station's copy should not be able to tell which they got.
"""


def _text() -> Any:
    """A character waveform, which is how TomoScan serves its strings."""
    return pvproperty(
        value="",
        dtype=ChannelType.CHAR,
        max_length=TEXT_LENGTH,
        string_encoding="utf-8",
    )


class CitationIOC(PVGroup):
    """The keeper's execution and step ids, carried on the control network."""

    KeeperExecutionId = _text()
    KeeperStepId = _text()


def main() -> None:
    """Serve the two records under a prefix the deployment names."""
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="",
        desc="The keeper citation records for one acquisition server.",
    )
    if not str(ioc_options.get("prefix", "")).strip():
        sys.exit(
            "a prefix is required, and it is the acquisition server's own, "
            "for example --prefix 19bm:TomoScan:"
        )
    run(CitationIOC(**ioc_options).pvdb, **run_options)


if __name__ == "__main__":
    main()
