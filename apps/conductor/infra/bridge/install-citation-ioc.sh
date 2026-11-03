#!/usr/bin/env bash
# Serves the keeper's two citation records beside an acquisition server
# whose own database does not carry them, as a `systemd --user` service.
#
#   BEAMLINE=19-bm PREFIX=19bm:TomoScan: SERVER_PORT=5067 ./install-citation-ioc.sh
#
# Re-running it is how a changed unit is deployed. It restarts rather than
# relying on `enable --now`, which is a no-op against something already
# running and would leave a changed unit on disk that never reaches the
# process. The service is stopped before the preflight runs, because
# otherwise the preflight finds this service's own records and refuses the
# redeploy this paragraph promises.
#
# ## The preflight is the simulator's, inverted, and that is the whole point
#
# install-tomoscan.sh refuses a prefix that already answers, because a
# simulator serving the station's real prefix would put a conductor onto
# real hardware. This serves the station's real prefix deliberately, so it
# asks the opposite pair of questions:
#
#     ${PREFIX}ServerRunning        must answer.  The station is there and
#                                   this host can see it.
#     ${PREFIX}KeeperExecutionId    must not.     Nothing else serves the
#     ${PREFIX}KeeperStepId         must not.     names this is about to.
#
# The first is the control. A silent record and an unreachable beamline
# fail identically over Channel Access, so without something that must
# answer, the two checks below would pass against a broken address list
# and conclude that a name is free when nothing at all is reachable.
#
# ## Refusing when the records already exist is the retirement mechanism
#
# This unit is temporary. The records belong in the station's TomoScan
# database, and when somebody adds them there, two servers answer one name:
# the race this beamline has already met, where every reference drew a
# duplicate-server warning and answered from a machine nobody meant to
# serve it. There is no scheduled date for that and there should not be, so
# instead the check below turns it into a refusal. The day the records land
# upstream, re-running this says so and stops, and stopping and disabling
# this unit is what the operator does next.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=19-bm}"
PREFIX="${PREFIX:?PREFIX is required, and it is the acquisition server prefix
    the station already uses, for example PREFIX=19bm:TomoScan:}"
SERVER_PORT="${SERVER_PORT:?SERVER_PORT is required: the Channel Access port this
    server listens on. Other servers share this host, so one taking the standard
    port leaves this falling back to an ephemeral one that a client with an
    explicit address list cannot find.}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${SCRIPT_DIR}/citation_ioc.py"

# Two layouts reach this script and only one of them is the repository.
# Here it sits at infra/bridge/ under the project, so the environment is
# two directories up. A deployment copies these three files alone into a
# directory of their own, where that guess lands outside the account
# entirely, which is what it did the first time this was run. The
# fallback is the conductor's own deployment, named by the convention
# every deployed directory at these beamlines follows: cora- and the app.
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV="${VENV:-${APP_DIR}/.venv}"
if [ ! -x "${VENV}/bin/python3" ] && [ -x "${HOME}/cora-conductor/.venv/bin/python3" ]; then
    VENV="${HOME}/cora-conductor/.venv"
fi
PYTHON="${PYTHON:-${VENV}/bin/python3}"

ETC="${ETC:-${HOME}/.config/cora}"
LOG="${LOG:-${ETC}/citation-ioc-${BEAMLINE}.log}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-citation-ioc.service"
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

say "beamline    ${BEAMLINE}"
say "prefix      ${PREFIX}"
say "host        ${DEPLOY_HOST}"
say "ca port     ${SERVER_PORT}"

[ -r "${SCRIPT}" ] || die "no citation_ioc.py beside this script at ${SCRIPT}"
[ -x "${PYTHON}" ] || die "no interpreter at ${PYTHON}. Set PYTHON or VENV."

CAGET="${CAGET:-$(command -v caget || true)}"
[ -x "${CAGET:-}" ] || die "caget not found, and the preflight cannot run without it."

# `caproto.ChannelType` rather than a bare import, for the reason the
# sibling installers spell out: a directory of the right name in the home
# imports as an empty namespace package and satisfies `import`.
"${PYTHON}" -c "import caproto; caproto.ChannelType" 2>/dev/null \
    || die "caproto is not installed in ${VENV}. Point VENV at an environment
    that has it, or install a caproto wheel there as install-tomoscan.sh does."
say "caproto     present"

# Stopped before the preflight, for the reason the header gives: otherwise
# this service's own records are what the two checks below find.
if systemctl --user is-active --quiet "${UNIT}" 2>/dev/null; then
    systemctl --user stop "${UNIT}"
    say "stopped     ${UNIT}, which was serving a previous install"
fi

if ! "${CAGET}" -w 5 "${PREFIX}ServerRunning" >/dev/null 2>&1; then
    die "${PREFIX}ServerRunning did not answer, so the Channel Access environment
    here cannot see this station. Nothing is concluded about the two records
    below, because an absent record and an unreachable beamline fail
    identically. Fix EPICS_CA_ADDR_LIST and run again."
fi
say "control     ${PREFIX}ServerRunning answered, so a silent record means absent"

for suffix in KeeperExecutionId KeeperStepId; do
    if "${CAGET}" -w 5 "${PREFIX}${suffix}" >/dev/null 2>&1; then
        die "${PREFIX}${suffix} already answers. If the station's own database has
    gained these records then this unit has done its job and should be stopped
    and disabled rather than redeployed, because two servers answering one name
    is a race whose loser is silent. Check with 'cainfo ${PREFIX}${suffix}'."
    fi
done
say "preflight   neither citation record is served by anything, so this is additive"

mkdir -p "${ETC}" "${UNIT_DIR}"

sed -e "s|@BEAMLINE@|${BEAMLINE}|g" \
    -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@PYTHON@|${PYTHON}|g" \
    -e "s|@SCRIPT@|${SCRIPT}|g" \
    -e "s|@PREFIX@|${PREFIX}|g" \
    -e "s|@SERVER_PORT@|${SERVER_PORT}|g" \
    -e "s|@LOG@|${LOG}|g" \
    "${SCRIPT_DIR}/cora-citation-ioc.service.in" > "${UNIT_DIR}/${UNIT}"
say "unit        ${UNIT_DIR}/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
systemctl --user restart "${UNIT}"

systemctl --user is-active --quiet "${UNIT}" \
    || die "the service did not stay up. systemctl --user status ${UNIT}"

# Pinned to the server this script just started, which the preflight
# above deliberately does not do. The preflight asks whether anything
# anywhere answers a name, so it has to use the environment it was
# given. This asks whether the server configured a moment ago is
# serving, and that server listens on a port no broadcast search
# reaches, so an ambient environment answers no by construction. The
# first run of this script refused here against a service that was up
# and entirely correct.
ours() {
    EPICS_CA_AUTO_ADDR_LIST=NO \
    EPICS_CA_ADDR_LIST="${DEPLOY_HOST}:${SERVER_PORT}" \
    "${CAGET}" -w "$1" "$2" >/dev/null 2>&1
}

for attempt in 1 2 3 4 5 6 7 8 9 10; do
    ours 3 "${PREFIX}KeeperExecutionId" && break
    [ "${attempt}" -lt 10 ] || die "the service is up and ${PREFIX}KeeperExecutionId
    does not answer on ${DEPLOY_HOST}:${SERVER_PORT}, which is where this script
    just configured it. Check 'systemctl --user status ${UNIT}' and ${LOG}."
    sleep 2
done

for suffix in KeeperExecutionId KeeperStepId; do
    ours 5 "${PREFIX}${suffix}" \
        || die "${PREFIX}${suffix} does not answer on ${DEPLOY_HOST}:${SERVER_PORT}"
done

say "serving     ${PREFIX}KeeperExecutionId and ${PREFIX}KeeperStepId"
say "done        add ${DEPLOY_HOST}:${SERVER_PORT} to the address list of every"
say "            client that must reach them, which is the conductor and the reporter"
