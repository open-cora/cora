#!/usr/bin/env bash
# Serves a simulated TomoScan at one beamline as a `systemd --user` service,
# so a conductor can be commissioned without starting a scan.
#
#   BEAMLINE=2-bm PREFIX=corasim2bmb:TomoScan: ./install.sh
#
# Re-running it is how a changed unit is deployed. It restarts rather than
# relying on `enable --now`, which is a no-op against something already
# running and would leave a changed unit on disk that never reaches the
# process.
#
# ## The prefix is checked for the one thing it must not be
#
# This serves a StartScan that a conductor will write. If the prefix named
# the station's real TomoScan, the write would reach it and a scan would
# begin. So the script refuses a prefix that already answers: either it
# belongs to something else, in which case serving it is a race, or it is
# the real server, in which case the whole point has been inverted.
#
# The check is worth nothing unless a name that IS there would answer, and
# a wrong address list fails exactly the way an absent record does. CONTROL
# names a record that must answer first, through the same environment.
#
# ## caproto, and why it is a local wheel
#
# A beamline soft IOC host has no route to a package index, measured rather
# than assumed. caproto has no required dependencies and ships as a pure
# Python wheel, so one file copied in is the whole installation. WHEEL
# points at it. A venv that already has caproto needs neither.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=2-bm}"
PREFIX="${PREFIX:?PREFIX is required, for example PREFIX=corasim2bmb:TomoScan:}"
CONTROL="${CONTROL:?CONTROL is required: a record at this beamline that must answer}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM="${SCRIPT_DIR}/tomoscan_sim.py"

APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV="${VENV:-${APP_DIR}/.venv}"
PYTHON="${PYTHON:-${VENV}/bin/python3}"

SCAN_SECONDS="${SCAN_SECONDS:-6}"
ETC="${ETC:-${HOME}/.config/cora}"
LOG="${LOG:-${ETC}/tomoscan-sim-${BEAMLINE}.log}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-tomoscan-sim.service"
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

say "beamline    ${BEAMLINE}"
say "prefix      ${PREFIX}"
say "host        ${DEPLOY_HOST}"

[ -r "${SIM}" ] || die "no tomoscan_sim.py beside this script at ${SIM}"
[ -x "${PYTHON}" ] || die "no interpreter at ${PYTHON}. Set PYTHON or VENV."

CAGET="${CAGET:-$(command -v caget || true)}"
[ -x "${CAGET:-}" ] || die "caget not found, and the preflight cannot run without it."

if ! "${PYTHON}" -c "import caproto" 2>/dev/null; then
    [ -n "${WHEEL:-}" ] || die "caproto is not installed in ${VENV} and no WHEEL was given.
    This host has no package index. Copy a caproto wheel here and set
    WHEEL=/path/to/caproto-*.whl, or point VENV at an environment that has it."
    [ -r "${WHEEL}" ] || die "WHEEL is set to ${WHEEL}, which cannot be read"
    "${PYTHON}" -m pip install --no-index --no-deps "${WHEEL}" >/dev/null \
        || die "installing ${WHEEL} failed"
    "${PYTHON}" -c "import caproto" 2>/dev/null \
        || die "${WHEEL} installed and caproto still will not import"
    say "caproto     installed from ${WHEEL}"
else
    say "caproto     already present"
fi

if ! "${CAGET}" -w 5 "${CONTROL}" >/dev/null 2>&1; then
    die "the control record ${CONTROL} did not answer, so the Channel Access
    environment here cannot see this beamline. Nothing is concluded about the
    prefix below, because an absent record and an unreachable beamline fail
    identically. Fix EPICS_CA_ADDR_LIST and run again."
fi
say "control     ${CONTROL} answered, so a silent record below means absent"

if "${CAGET}" -w 5 "${PREFIX}StartScan" >/dev/null 2>&1; then
    die "${PREFIX}StartScan already answers. If that is the station's real
    TomoScan then this prefix would put a conductor onto real hardware, which
    is the opposite of what this is for. If it is something else, serving the
    same name twice makes every write a race. Check with
    'cainfo ${PREFIX}StartScan'."
fi
say "preflight   ${PREFIX}StartScan is served by nothing, so this is additive"

mkdir -p "${ETC}" "${UNIT_DIR}"

sed -e "s|@BEAMLINE@|${BEAMLINE}|g" \
    -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@PYTHON@|${PYTHON}|g" \
    -e "s|@SIM@|${SIM}|g" \
    -e "s|@PREFIX@|${PREFIX}|g" \
    -e "s|@SCAN_SECONDS@|${SCAN_SECONDS}|g" \
    -e "s|@LOG@|${LOG}|g" \
    "${SCRIPT_DIR}/tomoscan-sim.service.in" > "${UNIT_DIR}/${UNIT}"
say "unit        ${UNIT_DIR}/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
systemctl --user restart "${UNIT}"

systemctl --user is-active --quiet "${UNIT}" \
    || die "the service did not stay up. systemctl --user status ${UNIT}"

for attempt in 1 2 3 4 5 6 7 8 9 10; do
    "${CAGET}" -w 3 "${PREFIX}ServerRunning" >/dev/null 2>&1 && break
    [ "${attempt}" -lt 10 ] || die "the service is up but ${PREFIX}ServerRunning does not
    answer from here. An IOC on this host is normally found by broadcast, which
    is EPICS_CA_AUTO_ADDR_LIST and is on unless something turned it off."
    sleep 2
done

for suffix in ServerRunning StartScan ScanStatus FullFileName KeeperExecutionId KeeperStepId; do
    "${CAGET}" -w 5 "${PREFIX}${suffix}" >/dev/null 2>&1 || die "${PREFIX}${suffix} does not answer"
done

say "serving     every record a conductor and a reporter need"
say "done        point run.prefix at ${PREFIX} to commission against this"
