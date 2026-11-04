#!/usr/bin/env bash
# Installs the watcher as a `systemd --user` service, with no root and no
# system package.
#
#   ./install-watcher.sh
#   BEAMLINE=19-bm ./install-watcher.sh
#
# It finishes the record of work that outlived the walk that started it:
# a transfer or a reconstruction the driver stopped waiting for, whose
# service still knows how it turned out. Left without a beamline it
# accounts for every one the record will show it, which is the right
# arrangement while one deployment moves data off site.
#
# ## What it does not do
#
# It does not write the configuration, because that file holds a bearer
# token. Minting and distributing those belongs to whoever runs the
# keeper, and a token this script could create is a token it could create
# for anyone. It reuses the reporter's own configuration by default,
# because both speak to the keeper as the same principal.
#
# It does not install dependencies unless asked. This one needs
# `--extra service` for the HTTP client and `--extra watch` for the two
# Globus SDKs and the token store, which the ordinary beamline reporter
# does not have and should not.
#
# ## Where it belongs
#
# Wherever the token store is and wherever Globus is reachable, which is
# not necessarily a beamline host and at this facility is not the host
# that reaches the detectors. The account the token store belongs to is
# the account this has to run as.

set -euo pipefail

BEAMLINE="${BEAMLINE:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ETC="${ETC:-${HOME}/.config/cora}"
CA_BUNDLE="${CA_BUNDLE:-${ETC}/ca-bundle.crt}"
PAUSE="${PAUSE:-60}"

# The reporter's own, because both reach one keeper as one principal. A
# deployment running the watcher somewhere the reporter is not points
# CONFIG at whatever it put there instead.
if [ -n "${BEAMLINE}" ]; then
    CONFIG="${CONFIG:-${ETC}/reporter-${BEAMLINE}.toml}"
else
    CONFIG="${CONFIG:?CONFIG is required when no BEAMLINE is given, because there is no per-beamline file to guess}"
fi

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-watcher.service"
DEPLOY_HOST="$(hostname)"
SCOPE="${BEAMLINE:-every beamline}"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

echo "Installing the watcher on ${DEPLOY_HOST}"
say "app         ${APP_DIR}"
say "unit        ${UNIT}"
say "accounts for ${SCOPE}"
say "config      ${CONFIG}"
echo

echo "Preflight"
systemctl --user show-environment >/dev/null 2>&1 \
    || die "no systemd --user manager is running for this account"

linger="$(loginctl show-user "$(whoami)" -p Linger --value 2>/dev/null || echo no)"
[ "${linger}" = "yes" ] \
    || die "lingering is off, so this would stop at logout. Try: loginctl enable-linger $(whoami)"

[ -r "${CONFIG}" ] || die "no configuration at ${CONFIG}. This script will not write
    it: the file holds a bearer token, and a script that could mint one for
    this caller could mint one for any."

mode="$(stat -c '%a' "${CONFIG}" 2>/dev/null || stat -f '%A' "${CONFIG}")"
[ "${mode}" = "600" ] || die "${CONFIG} is mode ${mode} and holds a token. chmod 600 it."
say "config      mode ${mode}"

[ -r "${CA_BUNDLE}" ] || die "no CA bundle at ${CA_BUNDLE}. The keeper presents a
    certificate from a private CA, so this needs a bundle carrying the system
    anchors plus that one."

if [ "${SYNC:-0}" = "1" ]; then
    command -v uv >/dev/null || die "SYNC=1 needs uv on PATH"
    (cd "${APP_DIR}" && uv sync --locked --no-dev --extra service --extra watch)
fi
[ -x "${APP_DIR}/.venv/bin/python3" ] || die "no virtualenv at ${APP_DIR}/.venv.
    Run again with SYNC=1, or share one built on a machine that can reach a
    package index."

# Every library this one actually needs, named rather than assumed. The
# ordinary beamline reporter has none of the three below, which is the
# whole reason they are an extra, so a host that runs both has to have
# been synced for both.
"${APP_DIR}/.venv/bin/python3" -c "import httpx, globus_sdk, globus_compute_sdk, alcf_tokens" 2>/dev/null \
    || die "the virtualenv is missing something this needs. Re-sync with
    --extra service --extra watch."
say "libraries   httpx and the two Globus SDKs are importable"

# The credential, before the service is started rather than at its first
# pass. A token store that is absent or belongs to nobody makes a watcher
# that starts, fails every pass, and is restarted forever while looking
# like a facility with nothing outstanding.
"${APP_DIR}/.venv/bin/python3" - <<'PREFLIGHT' \
    || die "the stored Globus credential could not be read, so every pass would
    fail. Whoever owns the token store runs the login for this account."
import sys

from alcf_tokens.auth import ServiceName, get_service_authorizer

try:
    get_service_authorizer(ServiceName("globus-transfer"))
except Exception as unreadable:
    print(f"{type(unreadable).__name__}: {unreadable}", file=sys.stderr)
    raise SystemExit(1) from unreadable
PREFLIGHT
say "credential  the stored transfer token reads"
echo

echo "Unit"
mkdir -p "${UNIT_DIR}"
beamline_argument=""
[ -n "${BEAMLINE}" ] && beamline_argument="--beamline ${BEAMLINE}"

sed -e "s|@SCOPE@|${SCOPE}|g" \
    -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    -e "s|@CONFIG@|${CONFIG}|g" \
    -e "s|@CA_BUNDLE@|${CA_BUNDLE}|g" \
    -e "s|@BEAMLINE_ARGUMENT@|${beamline_argument}|" \
    -e "s|@PAUSE@|${PAUSE}|g" \
    "${SCRIPT_DIR}/cora-watcher.service.in" > "${UNIT_DIR}/${UNIT}"

# Where the journal stands before this start, so the checks below read
# only what arrives after it. A whole-history grep answers with the past
# rather than with this deployment, in both directions: last week's
# success phrase satisfies a process that never started, and last week's
# failures fail an install that went perfectly.
before="$(journalctl --user -u "${UNIT}" --lines 0 --show-cursor --no-pager 2>/dev/null \
    | sed -n 's/^-- cursor: //p')"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}" >/dev/null
systemctl --user restart "${UNIT}"
say "ok"
echo

echo "Accounting"
# Active is not enough. A watcher that cannot reach the keeper stays
# active and retries, which from systemd looks exactly like a healthy one
# with nothing outstanding. What separates them is whether it got as far
# as saying what it is accounting for.
since_start() {
    if [ -n "${before}" ]; then
        journalctl --user -u "${UNIT}" --after-cursor "${before}" --no-pager 2>/dev/null || true
    else
        journalctl --user -u "${UNIT}" --no-pager 2>/dev/null || true
    fi
}

for _ in $(seq 1 15); do
    since_start | grep -q "accounting for work handed off" && break
    sleep 2
done
systemctl --user is-active --quiet "${UNIT}" \
    || die "${UNIT} did not stay up; see: journalctl --user -u ${UNIT}"
since_start | grep -q "accounting for work handed off" \
    || die "it started and never said what it was accounting for; see: journalctl --user -u ${UNIT}"

# A pass that fails is reported and the loop carries on, which is right
# at runtime and is not what a fresh install should look like.
recent="$(since_start | grep -c "pass failed" || true)"
[ "${recent}" = "0" ] \
    || die "it started, and ${recent} passes have already failed; see: journalctl --user -u ${UNIT}"

say "running, and no pass has failed"
echo
echo "Done. Follow it with:"
echo "    journalctl --user -u ${UNIT} -f"
