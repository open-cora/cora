#!/usr/bin/env bash
# Serves the two keeper id records at one beamline as a `systemd --user`
# service, with no root, no system package and no change to any file the
# beamline owns.
#
#   BEAMLINE=2-bm P=2bmb: R=TomoScan: CONTROL=2bmb:TomoScan:ServerRunning ./install.sh
#
# Re-running it is how a changed unit is deployed. It restarts the service
# rather than relying on `enable --now`, which is a no-op against something
# already running and would leave a changed unit on disk that never reaches
# the process.
#
# ## The preflight is the point of this script
#
# Serving a record name that something else already serves is the worst
# failure available here. Both servers answer, clients reach whichever wins
# the race, and because these records carry which step a scan belongs to, the
# symptom is a scan filed against the wrong work rather than an error.
#
# So the script refuses to start if either name already answers. That check
# is only worth anything if a name that IS there would have answered, and a
# wrong address list fails exactly the way an absent record does. CONTROL is
# how that is settled: a record that must answer, at the same beamline,
# through the same environment. If the control is silent the environment is
# wrong and the script stops without concluding anything about the two names.
#
# ## What it does not do
#
# It does not edit the beamline's IOC, its startup script or its templates.
# That is the whole reason this route exists, and it is what makes it safe to
# run while users are on the floor.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=2-bm}"
P="${P:?P is required, the first macro of the prefix, for example P=2bmb:}"
R="${R:?R is required, the second macro, for example R=TomoScan:}"
CONTROL="${CONTROL:?CONTROL is required: a record at this beamline that must answer}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECORDS_DB="${SCRIPT_DIR}/records.db"

ETC="${ETC:-${HOME}/.config/cora}"
LOG="${LOG:-${ETC}/keeper-ids-${BEAMLINE}.log}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-keeper-ids.service"
DEPLOY_HOST="$(hostname)"

EXECUTION_RECORD="${P}${R}KeeperExecutionId"
STEP_RECORD="${P}${R}KeeperStepId"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

say "beamline    ${BEAMLINE}"
say "records     ${EXECUTION_RECORD}"
say "            ${STEP_RECORD}"
say "host        ${DEPLOY_HOST}"

[ -r "${RECORDS_DB}" ] || die "no records.db beside this script at ${RECORDS_DB}"

SOFTIOC="${SOFTIOC:-$(command -v softIoc || true)}"
[ -x "${SOFTIOC:-}" ] || die "softIoc not found. Set SOFTIOC to its path, or put EPICS base on PATH."
CAGET="${CAGET:-$(command -v caget || true)}"
[ -x "${CAGET:-}" ] || die "caget not found, and the preflight cannot run without it."
say "softIoc     ${SOFTIOC}"

if ! "${CAGET}" -w 5 "${CONTROL}" >/dev/null 2>&1; then
    die "the control record ${CONTROL} did not answer, so the Channel Access
    environment here cannot see this beamline. Nothing is concluded about the
    two record names, because an absent record and an unreachable beamline
    fail identically. Fix EPICS_CA_ADDR_LIST and run again."
fi
say "control     ${CONTROL} answered, so a silent record below means absent"

for record in "${EXECUTION_RECORD}" "${STEP_RECORD}"; do
    if "${CAGET}" -w 5 "${record}" >/dev/null 2>&1; then
        die "${record} is already served by something. Starting a second server
    for it would make every scan's attribution a race. Find what serves it
    with 'cainfo ${record}' before going further."
    fi
done
say "preflight   neither name is served, so this is additive"

mkdir -p "${ETC}" "${UNIT_DIR}"

sed -e "s|@BEAMLINE@|${BEAMLINE}|g" \
    -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@SOFTIOC@|${SOFTIOC}|g" \
    -e "s|@P@|${P}|g" \
    -e "s|@R@|${R}|g" \
    -e "s|@RECORDS_DB@|${RECORDS_DB}|g" \
    -e "s|@LOG@|${LOG}|g" \
    "${SCRIPT_DIR}/keeper-ids.service.in" > "${UNIT_DIR}/${UNIT}"
say "unit        ${UNIT_DIR}/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
systemctl --user restart "${UNIT}"

systemctl --user is-active --quiet "${UNIT}" || die "the service did not stay up. systemctl --user status ${UNIT}"

for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if "${CAGET}" -w 3 "${EXECUTION_RECORD}" >/dev/null 2>&1; then
        break
    fi
    [ "${attempt}" -lt 10 ] || die "the service is up but ${EXECUTION_RECORD} does not answer from
    here. A client on this host needs 127.0.0.1 in EPICS_CA_ADDR_LIST to
    reach an IOC on this host, and this beamline's list may not have it."
    sleep 2
done

for record in "${EXECUTION_RECORD}" "${STEP_RECORD}"; do
    "${CAGET}" -w 5 "${record}" >/dev/null 2>&1 || die "${record} does not answer"
done

say "serving     both records answer"
say "done        the conductor may now write them and the reporter read them"
