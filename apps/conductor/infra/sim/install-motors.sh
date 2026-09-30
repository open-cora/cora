#!/usr/bin/env bash
# Serves simulated motors at one beamline as a `systemd --user` service, so a
# conductor's control seam can be commissioned without moving anything.
#
#   BEAMLINE=19-bm PREFIX=corasim19bm: CONTROL=19bmSoft:m1 ./install-motors.sh
#
# Three motors, mtr1 to mtr3, from caproto's own fake motor record. The unit
# file beside this says why they are not written here.
#
# Re-running it is how a changed unit is deployed. The service is stopped
# before the preflight runs, because otherwise the preflight finds this
# service's own records and refuses the redeploy.
#
# ## Separate from the TomoScan simulator on purpose
#
# A beamline testing whether a conductor can reach it and set a value needs
# motors and no engine at all. Installing a scan simulator to find that out
# would be installing a second thing to supervise for a question it does not
# answer. The two are independent services and either can run alone.
#
# ## The prefix is checked for the one thing it must not be
#
# A conductor writes to whatever a step names, and what it may name is a
# list in its own configuration. This serves records under a prefix meant to
# go in that list, so the prefix must not already belong to something: if it
# did, either the list would point a conductor at somebody else's hardware,
# or two servers would answer one name and every write would be a race.
#
# The check is worth nothing unless a name that IS there would answer, and a
# wrong address list fails exactly the way an absent record does. CONTROL
# names a record that must answer first, through the same environment.
#
# ## caproto, and why it is a local wheel
#
# A beamline soft IOC host has no route to a package index, measured rather
# than assumed. caproto has no required dependencies and ships as a pure
# Python wheel, so one file copied in is the whole installation. WHEEL
# points at it. A venv that already has caproto needs neither.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=19-bm}"
PREFIX="${PREFIX:?PREFIX is required, for example PREFIX=corasim19bm:}"
CONTROL="${CONTROL:?CONTROL is required: a record at this beamline that must answer}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV="${VENV:-${APP_DIR}/.venv}"
PYTHON="${PYTHON:-${VENV}/bin/python3}"

ENTRY_POINT="caproto.ioc_examples.fake_motor_record"
MOTORS="mtr1 mtr2 mtr3"

ETC="${ETC:-${HOME}/.config/cora}"
LOG="${LOG:-${ETC}/motor-sim-${BEAMLINE}.log}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-motor-sim.service"
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

say "beamline    ${BEAMLINE}"
say "prefix      ${PREFIX}"
say "host        ${DEPLOY_HOST}"

[ -x "${PYTHON}" ] || die "no interpreter at ${PYTHON}. Set PYTHON or VENV."

CAGET="${CAGET:-$(command -v caget || true)}"
[ -x "${CAGET:-}" ] || die "caget not found, and the preflight cannot run without it."

# `caproto.ChannelType` rather than a bare import, for the reason the
# reporter's installer spells out: a directory of the right name in the
# home imports as an empty namespace package and satisfies `import`.
if ! "${PYTHON}" -c "import caproto; caproto.ChannelType" 2>/dev/null; then
    [ -n "${WHEEL:-}" ] || die "caproto is not installed in ${VENV} and no WHEEL was given.
    This host has no package index. Copy a caproto wheel here and set
    WHEEL=/path/to/caproto-*.whl, or point VENV at an environment that has it."
    [ -r "${WHEEL}" ] || die "WHEEL is set to ${WHEEL}, which cannot be read"
    # uv rather than pip, because a uv-built virtualenv has no pip in it
    # and the error for that reads as a broken interpreter rather than a
    # missing tool.
    if command -v uv >/dev/null; then
        uv pip install --python "${PYTHON}" --no-index --no-deps "${WHEEL}" >/dev/null \
            || die "installing ${WHEEL} with uv failed"
    elif "${PYTHON}" -m pip --version >/dev/null 2>&1; then
        "${PYTHON}" -m pip install --no-index --no-deps "${WHEEL}" >/dev/null \
            || die "installing ${WHEEL} with pip failed"
    else
        die "neither uv nor pip is available to install ${WHEEL} into ${VENV}"
    fi
    "${PYTHON}" -c "import caproto; caproto.ChannelType" 2>/dev/null \
        || die "${WHEEL} installed and caproto still will not import"
    say "caproto     installed from ${WHEEL}"
else
    say "caproto     already present"
fi

# The simulator is a module inside caproto rather than a file beside this
# script, so importing caproto is not evidence it is there. A caproto built
# without its examples would pass every check above and fail at ExecStart,
# which systemd reports as a service that will not start and nothing else.
"${PYTHON}" -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('${ENTRY_POINT}') else 1)" \
    || die "caproto is installed here and does not carry ${ENTRY_POINT}, which is
    what this unit runs. Use a caproto that ships its examples."
say "simulator   ${ENTRY_POINT}"

if ! "${CAGET}" -w 5 "${CONTROL}" >/dev/null 2>&1; then
    die "the control record ${CONTROL} did not answer, so the Channel Access
    environment here cannot see this beamline. Nothing is concluded about the
    prefix below, because an absent record and an unreachable beamline fail
    identically. Fix EPICS_CA_ADDR_LIST and run again."
fi
say "control     ${CONTROL} answered, so a silent record below means absent"

# Ours answering our own prefix is the previous install rather than a
# collision. Stopping first is what makes a redeploy work, and it sharpens
# the question below: whatever still answers belongs to something else.
if systemctl --user is-active --quiet "${UNIT}" 2>/dev/null; then
    systemctl --user stop "${UNIT}"
    say "stopped     ${UNIT}, which was serving a previous install"
fi

for motor in ${MOTORS}; do
    if "${CAGET}" -w 5 "${PREFIX}${motor}" >/dev/null 2>&1; then
        die "${PREFIX}${motor} already answers, and nothing of ours is serving it.
    If that is real hardware then naming this prefix in a conductor's writable
    list would put it onto the floor, which is the opposite of what this is
    for. If it is something else, serving one name twice makes every write a
    race. Check with 'cainfo ${PREFIX}${motor}'."
    fi
done
say "preflight   ${PREFIX}{${MOTORS// /,}} are served by nothing, so this is additive"

mkdir -p "${ETC}" "${UNIT_DIR}"

sed -e "s|@BEAMLINE@|${BEAMLINE}|g" \
    -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@PYTHON@|${PYTHON}|g" \
    -e "s|@ENTRY_POINT@|${ENTRY_POINT}|g" \
    -e "s|@PREFIX@|${PREFIX}|g" \
    -e "s|@LOG@|${LOG}|g" \
    "${SCRIPT_DIR}/motor-sim.service.in" > "${UNIT_DIR}/${UNIT}"
say "unit        ${UNIT_DIR}/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
systemctl --user restart "${UNIT}"

systemctl --user is-active --quiet "${UNIT}" \
    || die "the service did not stay up. systemctl --user status ${UNIT}"

for attempt in 1 2 3 4 5 6 7 8 9 10; do
    "${CAGET}" -w 3 "${PREFIX}mtr1" >/dev/null 2>&1 && break
    [ "${attempt}" -lt 10 ] || die "the service is up but ${PREFIX}mtr1 does not
    answer from here. An IOC on this host is normally found by broadcast, which
    is EPICS_CA_AUTO_ADDR_LIST and is on unless something turned it off."
    sleep 2
done

# The fields, not just the record. The control seam reads a readback, asks
# whether motion finished and refuses a motor being held, so a simulator
# serving only the setpoint would pass the check above and fail every set.
for motor in ${MOTORS}; do
    for field in "" .RBV .DMOV .SPMG .STOP; do
        "${CAGET}" -w 5 "${PREFIX}${motor}${field}" >/dev/null 2>&1 \
            || die "${PREFIX}${motor}${field} does not answer"
    done
done

say "serving     every field the control seam reads and writes"
echo
echo "Point a conductor at these by naming the prefix in its configuration:"
echo
echo "    [control]"
echo "    writable = [\"${PREFIX}\"]"
echo
echo "Without that table the conductor may write nothing at all, which is"
echo "the default and is deliberate."
