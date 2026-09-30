#!/usr/bin/env bash
# Installs a conductor at one beamline as a `systemd --user` service, with no
# root and no system package.
#
#   BEAMLINE=7-bm ./install.sh
#
# Re-running it is how a new revision is deployed. It restarts the service
# rather than relying on `enable --now`, which is a no-op against something
# already running and would leave a changed unit on disk that never reaches
# the process.
#
# ## What it does not do
#
# It does not write the configuration, because that file holds the beamline's
# bearer token. Minting and distributing those belongs to whoever runs the
# keeper, and a token that this script could create is a token this script
# could create for any beamline.
#
# It does not install dependencies when a virtualenv is already present. The
# package declares no core dependencies on purpose, so a working install needs
# `--extra service` for the HTTP client and `--extra epics` for Channel
# Access. Set SYNC=1 to do that here, which needs a package index: a beamline
# whose conductor host cannot reach one builds the virtualenv on a machine
# that can and shares it, which is what the shared home is for. Build on the
# older platform when the two differ, because a binary wheel built against a
# newer C library will not load on an older one.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=7-bm}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ETC="${ETC:-${HOME}/.config/cora}"
CONFIG="${CONFIG:-${ETC}/conductor-${BEAMLINE}.toml}"
CA_BUNDLE="${CA_BUNDLE:-${ETC}/ca-bundle.crt}"
EPICS_ENV="${EPICS_ENV:-${ETC}/epics.env}"
LOG="${LOG:-${ETC}/conductor-${BEAMLINE}.log}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-conductor.service"
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

echo "Installing a conductor for ${BEAMLINE} on ${DEPLOY_HOST}"
say "app     ${APP_DIR}"
say "config  ${CONFIG}"
echo

echo "Preflight"
systemctl --user show-environment >/dev/null 2>&1 \
  || die "no systemd --user manager is running for this account"

linger="$(loginctl show-user "$(whoami)" -p Linger --value 2>/dev/null || echo no)"
[ "${linger}" = "yes" ] \
  || die "lingering is off, so this would stop at logout. Try: loginctl enable-linger $(whoami)"

[ -f "${CONFIG}" ] || die "no configuration at ${CONFIG}; it carries the token and is not written here"

# The token is in it, so a configuration anyone at this beamline can read is
# a token anyone at this beamline can read. Everything at a beamline runs as
# one account today, so this protects against a mistake rather than a person.
perms="$(stat -c '%a' "${CONFIG}")"
[ "${perms}" = "600" ] || die "${CONFIG} is mode ${perms}; it holds a token and must be 600"

[ -f "${CA_BUNDLE}" ] || die "no CA bundle at ${CA_BUNDLE}; the keeper's certificate could not be verified"

if [ ! -x "${APP_DIR}/.venv/bin/python3" ] || [ "${SYNC:-0}" = "1" ]; then
  command -v uv >/dev/null 2>&1 || die "no virtualenv at ${APP_DIR}/.venv and no uv to build one"
  say "building the virtualenv"
  (cd "${APP_DIR}" && uv sync --locked --no-dev --extra service --extra epics >/dev/null)
fi
"${APP_DIR}/.venv/bin/python3" -c 'import httpx, epics' 2>/dev/null \
  || die "the virtualenv is missing httpx or pyepics; rebuild it with --extra service --extra epics"
say "ok"
echo

echo "Unit"
mkdir -p "${UNIT_DIR}"
epics_line=""
[ -f "${EPICS_ENV}" ] && epics_line="EnvironmentFile=${EPICS_ENV}"

sed -e "s|@BEAMLINE@|${BEAMLINE}|g" \
    -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    -e "s|@CONFIG@|${CONFIG}|g" \
    -e "s|@CA_BUNDLE@|${CA_BUNDLE}|g" \
    -e "s|@LOG@|${LOG}|g" \
    -e "s|@EPICS_ENVIRONMENT@|${epics_line}|" \
    "${SCRIPT_DIR}/conductor.service.in" > "${UNIT_DIR}/${UNIT}"

# Where the log ends before this start. The checks below read only what is
# appended past here, because the log is appended to across installs and
# never rotated, so a whole-file grep answers with history rather than with
# this deployment. Both directions were wrong and both were seen at a
# beamline: last week's success phrase satisfies "it asked" for a process
# that never started, and last week's failures fail an install that went
# perfectly.
before="$(wc -c < "${LOG}" 2>/dev/null || echo 0)"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}" >/dev/null
systemctl --user restart "${UNIT}"
say "ok"
echo

echo "Asking for work"
# Active is not enough: a conductor that cannot reach the keeper stays active
# and retries, which looks identical to a healthy idle one from systemd. What
# separates them is whether it got as far as asking, and whether anything is
# still going wrong after it did.
# Only this start's output. A function rather than a variable, because the
# process is still writing and each check wants what is there when it asks.
since_start() { tail -c "+$((before + 1))" "${LOG}" 2>/dev/null || true; }

for _ in $(seq 1 15); do
  since_start | grep -q "asking for work at ${BEAMLINE}" && break
  sleep 2
done
systemctl --user is-active --quiet "${UNIT}" \
  || die "${UNIT} did not stay up; see ${LOG}"
since_start | grep -q "asking for work at ${BEAMLINE}" \
  || die "it started but never asked the keeper for work; see ${LOG}"

# Not "refused". A step this conductor refuses is a claim conflict, which is
# the one outcome that is unambiguously good news, and every real failure
# here is named SomethingError anyway.
recent="$(since_start | grep -ciE "error|traceback" || true)"
[ "${recent}" = "0" ] \
  || die "it asked, and then failed ${recent} times; see ${LOG}"

say "running, and the keeper answered"
echo
echo "Done. Follow it with:"
echo "    journalctl --user -u ${UNIT} -f"
echo "    tail -f ${LOG}"
