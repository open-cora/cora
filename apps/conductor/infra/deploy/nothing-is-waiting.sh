#!/usr/bin/env bash
# Whether a conductor may come back with nobody deciding that it should.
#
#   nothing-is-waiting.sh UNIT
#
# The guard after-boot.sh runs before it starts a conductor on its own,
# after a boot that came up without it. It is handed the unit's name, reads
# which configuration that unit runs with, and asks the keeper, as that
# conductor, what is dispatched to its beamline and not yet taken up, and
# what a walk there parked. Read only, and it says what it found either way:
#
#   0  nothing is waiting, so the conductor may start
#   1  something is, so the conductor waits for a person
#   2  the queue could not be read, so the conductor waits as well
#
# install.sh runs it too, once the conductor is up, and refuses on a 2: a
# guard that cannot read the queue holds the conductor after every boot
# the job acts on, which is a beamline nobody dispatches to, arriving by
# another road.
#
# ## The hazard
#
# A conductor asks for work the moment it starts and takes what is
# dispatched to its beamline the moment it is answered. So anything
# dispatched while it was away starts moving the station at once: a scan
# queued for a sample long since unloaded, in somebody else's beamtime.
#
# The job is what makes the time away open-ended. Without it, a conductor
# whose boot never read its unit stayed down until a person noticed, and
# that person was the decision. The job starts it on the first tick after
# the home is back, which is minutes after the boot when the mount was
# merely late, and as long as the outage when the home itself was gone.
# The work waiting by then is as old as that.
#
# The keeper's own guard does not reach this. It holds the keeper's API
# while anything is queued, which covers a keeper coming back to
# conductors that kept asking. A beamline host that reboots while the
# keeper stays up is the other order, and the conductor is the one coming
# back.
#
# A walk that parked is the same hazard. It stopped at a step whose work is
# still running elsewhere, and the conductor takes it back the moment that
# work is reported stopped, whether or not anyone still wants the step
# after it. So a parked execution holds the conductor as a dispatched one
# does, and so does a ready one, which is a parked one whose wait is over.
#
# This holds that case and no other. When nothing is waiting the conductor
# comes back exactly as the boot would have brought it. When something is,
# it stays down and the journal names what is waiting. The job asks again
# at every tick, so ending what should not run is enough to let it start.
#
# ## What it asks, and as whom
#
# The listings a conductor reads on its first asks, narrowed to its beamline
# and to work nothing has taken up or a walk there parked, one status at a
# time, with its own token, through its own configuration loader, under the
# interpreter and the certificate bundle its unit names. A guard that gets
# an answer is a conductor that could have asked.
#
# Narrowed by beamline and not by the routines the conductor runs. Work
# sent to this station that no conductor here can run is still work
# somebody sent to this station, and whether it should run is the same
# decision.
#
# The keeper's guard reads the event log because the API is down when it
# runs. This runs with the keeper up, so it reads what a conductor is
# answered from.

set -euo pipefail

UNIT="${1:-}"
UNIT_FILE="${HOME}/.config/systemd/user/${UNIT}"

PATH="${PATH}:/usr/local/bin:/usr/bin:/bin"

could_not() {
  echo "the queue could not be read, so nothing can say ${UNIT:-this conductor} is safe to bring back: $*"
  exit 2
}

[ -n "${UNIT}" ] || could_not "no unit was named"
[ -f "${UNIT_FILE}" ] || could_not "there is no unit file at ${UNIT_FILE}"

# Read from the unit rather than worked out, so the question goes out with
# what the service itself would send it with.
EXEC="$(sed -n 's/^ExecStart=//p' "${UNIT_FILE}" | head -n 1)"
PYTHON="${EXEC%% *}"
CONFIG="$(printf '%s\n' "${EXEC}" | sed -n 's/.* --config \([^ ]*\).*/\1/p')"
BUNDLE="$(sed -n 's/^Environment=SSL_CERT_FILE=//p' "${UNIT_FILE}" | head -n 1)"

[ -x "${PYTHON}" ] || could_not "${UNIT} starts ${PYTHON:-nothing}, which is not an executable"
[ -n "${CONFIG}" ] || could_not "${UNIT} names no configuration"
if [ -n "${BUNDLE}" ]; then
  export SSL_CERT_FILE="${BUNDLE}"
fi

# Work waiting comes back from Python as 3 and leaves here as 1, because 1
# is also what Python exits with when it raises. A crash read as work
# waiting would hold the conductor just the same, and would pass the
# installer, which refuses only on 2.
set +e
"${PYTHON}" -P - "${CONFIG}" <<'ASK'
import sys
from pathlib import Path

try:
    import httpx

    from conductor.adapters.http_tasking import DISPATCHED, PARKED, READY
    from conductor.config import load

    config = load(Path(sys.argv[1]))
    waiting = []
    more = False
    for status in (DISPATCHED, READY, PARKED):
        answered = httpx.get(
            f"{config.base_url}/executions",
            params={"beamline": config.beamline, "status": status},
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=15.0,
        )
        if answered.status_code != 200:
            raise RuntimeError(
                f"{config.base_url} answered {answered.status_code}: {answered.text[:200]}"
            )
        page = answered.json()
        more = more or bool(page.get("next_cursor"))
        waiting.extend(
            (str(row["created_at"]), str(row["procedure_name"]), str(row["execution_id"]), status)
            for row in page["items"]
        )
    waiting.sort()
except Exception as unread:
    print(
        "the queue could not be read, so nothing can say this conductor is safe "
        f"to bring back: {unread}"
    )
    sys.exit(2)

if not waiting:
    print(
        f"nothing is dispatched or parked at {config.beamline} and waiting, so the "
        "conductor can come back as it was"
    )
    sys.exit(0)

counted = f"{len(waiting)} or more" if more else str(len(waiting))
print(
    f"{counted} execution(s) at {config.beamline} are dispatched and not yet taken up, "
    "or parked on work that may stop at any moment, and this conductor takes each "
    "one the moment it can:"
)
print("    procedure dispatched-at execution status")
for dispatched_at, procedure, execution, status in waiting:
    print(f"    {procedure} {dispatched_at} {execution} {status}")
sys.exit(3)
ASK
asked=$?
set -e

case "${asked}" in
  0) exit 0 ;;
  3) exit 1 ;;
  2) exit 2 ;;
  *) could_not "the question itself failed, with exit ${asked}" ;;
esac
