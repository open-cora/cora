#!/usr/bin/env bash
# Whether the turner may come back with nobody deciding that it should.
#
#   no-pursuit-is-running.sh UNIT
#
# The guard after-boot.sh runs before it starts the turner on its own,
# after a boot that came up without it. It is handed the unit's name, reads
# which configuration that unit runs with, and asks the keeper, as the
# turner, which pursuits are running. Read only, and it says what it found
# either way:
#
#   0  no pursuit is running, so the turner may start
#   1  some are, so the turner waits for a person
#   2  the pursuits could not be read, so the turner waits as well
#
# install-turner.sh runs it too, once the turner is up, and refuses on a 2:
# a guard that cannot read the pursuits holds the turner after every boot
# the job acts on.
#
# ## The hazard
#
# A turner moves every running pursuit on by a step, and closing a round
# on an advancing answer dispatches the next execution, which a conductor
# takes the moment it asks. A pursuit's budget counts rounds, not time. So
# a turner that comes back after an outage continues every pursuit as late
# as the outage was long: the next scan of a sample that was on the station
# when the pursuit began, dispatched days afterwards into a conductor that
# is up and waiting.
#
# The job is what makes that late return happen with nobody deciding: it
# starts the turner on the first tick after the home is back, however long
# that took. Whether a pursuit should still go on after that is a decision
# about its goal and its station, and a person makes it, by withdrawing
# what should stop and starting the turner by hand. The job asks again at
# every tick, so withdrawing every running pursuit is also enough.
#
# Neither the keeper's guard nor a conductor's sees this. Both hold work
# already dispatched, and this is the work that would be dispatched next.
#
# ## What it asks, and as whom
#
# The listing a turner reads at the start of every pass, narrowed to the
# running pursuits, with the turner's own token, through its own
# configuration loader, under the interpreter and the certificate bundle
# its unit names. A guard that gets an answer is a turner that could have
# asked.

set -euo pipefail

UNIT="${1:-}"
UNIT_FILE="${HOME}/.config/systemd/user/${UNIT}"

PATH="${PATH}:/usr/local/bin:/usr/bin:/bin"

could_not() {
  echo "the pursuits could not be read, so nothing can say ${UNIT:-the turner} is safe to bring back: $*"
  exit 2
}

[ -n "${UNIT}" ] || could_not "no unit was named"
[ -f "${UNIT_FILE}" ] || could_not "there is no unit file at ${UNIT_FILE}"

EXEC="$(sed -n 's/^ExecStart=//p' "${UNIT_FILE}" | head -n 1)"
PYTHON="${EXEC%% *}"
CONFIG="$(printf '%s\n' "${EXEC}" | sed -n 's/.* --config \([^ ]*\).*/\1/p')"
BUNDLE="$(sed -n 's/^Environment=SSL_CERT_FILE=//p' "${UNIT_FILE}" | head -n 1)"

[ -x "${PYTHON}" ] || could_not "${UNIT} starts ${PYTHON:-nothing}, which is not an executable"
[ -n "${CONFIG}" ] || could_not "${UNIT} names no configuration"
if [ -n "${BUNDLE}" ]; then
  export SSL_CERT_FILE="${BUNDLE}"
fi

# Pursuits running come back from Python as 3 and leave here as 1, because
# 1 is also what Python exits with when it raises, and a crash read as
# pursuits running would pass the installer, which refuses only on 2.
set +e
"${PYTHON}" -P - "${CONFIG}" <<'ASK'
import sys
from pathlib import Path

try:
    import httpx

    from conductor.adapters.http_turning import RUNNING
    from conductor.config import load_turner

    config = load_turner(Path(sys.argv[1]))
    answered = httpx.get(
        f"{config.base_url}/pursuits",
        params={"status": RUNNING},
        headers={"Authorization": f"Bearer {config.token}"},
        timeout=15.0,
    )
    if answered.status_code != 200:
        raise RuntimeError(
            f"{config.base_url} answered {answered.status_code}: {answered.text[:200]}"
        )
    page = answered.json()
    running = sorted(
        (str(row["created_at"]), str(row["beamline"]), str(row["pursuit_id"]), str(row["goal"]))
        for row in page["items"]
    )
except Exception as unread:
    print(
        "the pursuits could not be read, so nothing can say the turner is safe "
        f"to bring back: {unread}"
    )
    sys.exit(2)

if not running:
    print("no pursuit is running, so the turner can come back as it was")
    sys.exit(0)

counted = f"{len(running)} or more" if page.get("next_cursor") else str(len(running))
print(
    f"{counted} pursuit(s) are running, and the turner moves each one on, "
    "dispatching whatever its next answer proposes:"
)
print("    beamline started pursuit goal")
for started, beamline, pursuit, goal in running:
    print(f"    {beamline} {started} {pursuit} {goal}")
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
