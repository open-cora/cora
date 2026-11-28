#!/usr/bin/env bash
# Whether the keeper's API may come back with nobody deciding that it should.
#
#   nothing-is-queued.sh
#
# The guard after-boot.sh runs before it starts cora-keeper.service on its
# own, after a boot that came up without it. Read only, and it says what it
# found either way:
#
#   0  nothing is queued, so the API may start
#   1  something is, so the API waits for a person
#   2  the queue could not be read, so the API waits as well
#
# install.sh runs it too, once the API is up, and refuses on a 2: a guard
# that cannot read the queue holds the API after every reboot, which is
# the outage this was written to end, arriving by another road.
#
# ## The hazard
#
# A conductor keeps asking for work while the keeper is away, and takes
# what is dispatched to its beamline the moment an ask is answered. So the
# instant the API answers after a reboot, anything dispatched before the
# host went down and never taken up starts moving a station: a scan queued
# for a sample long since unloaded, in somebody else's beamtime, however
# many days after anyone asked for it.
#
# A walk that parked at work still running elsewhere is the same hazard a
# little later. It is taken back the moment that work is reported stopped,
# and its next step may be the one that moves the station.
#
# This holds that case and no other. When nothing is queued the API comes
# back exactly as the boot would have brought it. When something is, the
# API stays down and the journal says what is waiting and where, because
# whether that work should still run is a decision about a station, and the
# party able to make it is a person who can see the station.
#
# Waiting on a failed read is the same choice made for the same reason. A
# keeper held down is down where anybody looking at it can see; a station
# moved by stale work is reported by nothing.
#
# ## Why the log and not the summary
#
# The intake answers from the execution summary, which the API's own
# projection worker fills from the event log. A host that went down hard
# can leave the log a few events ahead of the summary, and the events in
# that gap are the newest: the ones dispatched just before it died. The
# summary would not show them, and the worker would project them a moment
# after the API started, straight into the intake. So the query reads the
# log the summary is rebuilt from.
#
# It reads as keeper_app over the container's local socket, the role that
# can read the log and cannot rewrite it. Nothing here needs more, and the
# owner's password is not read.
#
# ## Releasing a hold
#
# The deploy README's section on reboots has the procedure. In short: stop
# the conductor at each beamline named, start the API by hand, end what
# should not run, and start the conductors again. Starting the API while
# they are running hands them the queue at once.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERY="${SCRIPT_DIR}/queued-executions.sql"

PATH="${PATH}:/usr/local/bin:/usr/bin:/bin"

for _ in $(seq 1 60); do
  podman exec keeper-postgres pg_isready -U keeper -d keeper >/dev/null 2>&1 && break
  sleep 2
done

if ! queued="$(podman exec -i keeper-postgres \
    psql -X -q -t -A -F ' ' -v ON_ERROR_STOP=1 -U keeper_app -d keeper -f - \
    < "${QUERY}" 2>&1)"; then
  echo "the queue could not be read, so nothing can say the API is safe to bring back:"
  printf '%s\n' "${queued}" | sed 's/^/    /'
  exit 2
fi

if [ -z "${queued}" ]; then
  echo "nothing is dispatched or parked and waiting, so the API can come back as it was"
  exit 0
fi

count="$(printf '%s\n' "${queued}" | wc -l | tr -d ' ')"
echo "${count} execution(s) are dispatched and not yet taken up, or parked on work"
echo "that may stop at any moment, and a conductor takes each one the moment it can:"
echo "    beamline procedure dispatched-at execution waiting"
printf '%s\n' "${queued}" | sed 's/^/    /'
exit 1
