#!/usr/bin/env bash
# Installs the watcher as a `systemd --user` service, with no root and no
# system package.
#
#   ./install-watcher.sh
#   BEAMLINE=19-bm ./install-watcher.sh
#   BEAMLINE=19-bm WATCH="tomoscan" INSTANCE=scans ./install-watcher.sh
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
# ## Where it belongs, and why there may be two
#
# Wherever the token store is and wherever Globus is reachable, which is
# not necessarily a beamline host and at this facility is not the host
# that reaches the detectors. The account the token store belongs to is
# the account this has to run as.
#
# A scan is the exception and it is why `WATCH` exists. Asking a
# TomoScan server how a scan turned out needs Channel Access to a
# beamline subnet, and asking Globus needs egress to the internet, and
# at this facility no host has both. So a deployment that hands off
# both kinds of work runs two watchers, each told what it can reach,
# and each leaves alone the references it does not recognise.
#
# `INSTANCE` is what lets the second one exist. A unit directory here is
# one NFS directory mounted by every machine in the account, so two
# installs under one unit name are not two services: the second
# overwrites the first, and because `ConditionHost` is written from the
# hostname, it also stops the first from ever starting again. That is a
# running watcher silently replaced by one pinned to another host.

set -euo pipefail

BEAMLINE="${BEAMLINE:-}"
INSTANCE="${INSTANCE:-}"

# Which services this one asks. Space separated, and the default is the
# pair that was here before a third existed, so a deployment already
# running this is unchanged by the option appearing.
WATCH="${WATCH:-globus-transfer globus-compute}"

KNOWN_FAR_SIDES="globus-transfer globus-compute tomoscan"

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
# Spelled out rather than built, so that one grep for a unit name seen on
# a host finds this script. The second line is what an instance renames
# it to, and a deployment running two watchers needs it: see the note
# above on one unit directory serving every machine in the account.
UNIT="cora-watcher.service"
[ -n "${INSTANCE}" ] && UNIT="cora-watcher-${INSTANCE}.service"
DEPLOY_HOST="$(hostname)"
SCOPE="${BEAMLINE:-every beamline}"

watch_argument=""
for far_side in ${WATCH}; do
    case " ${KNOWN_FAR_SIDES} " in
        *" ${far_side} "*) ;;
        *) printf 'refused: %s is not a far side this knows. Pick from: %s\n' \
               "${far_side}" "${KNOWN_FAR_SIDES}" >&2; exit 1;;
    esac
    watch_argument="${watch_argument} --watch ${far_side}"
done
[ -n "${watch_argument}" ] || { printf 'refused: WATCH named nothing\n' >&2; exit 1; }

# What the preflight below has to check, decided from what was asked for
# rather than from a guess. A watcher asking only about scans has no use
# for a Globus credential, and refusing to install without one would
# refuse the only watcher a beamline host can run.
asks_globus=no
asks_scans=no
case " ${WATCH} " in *" globus-"*) asks_globus=yes;; esac
case " ${WATCH} " in *" tomoscan "*) asks_scans=yes;; esac

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

echo "Installing the watcher on ${DEPLOY_HOST}"
say "app         ${APP_DIR}"
say "unit        ${UNIT}"
say "accounts for ${SCOPE}"
say "asking      ${WATCH}"
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
    extras="--extra service"
    [ "${asks_globus}" = yes ] && extras="${extras} --extra watch"
    [ "${asks_scans}" = yes ] && extras="${extras} --extra epics"
    # Unquoted on purpose: these are several arguments rather than one.
    # shellcheck disable=SC2086
    (cd "${APP_DIR}" && uv sync --locked --no-dev ${extras})
fi
[ -x "${APP_DIR}/.venv/bin/python3" ] || die "no virtualenv at ${APP_DIR}/.venv.
    Run again with SYNC=1, or share one built on a machine that can reach a
    package index."

# Every library this one actually needs, named rather than assumed, and
# only the ones the far sides asked for need. The ordinary beamline
# reporter has none of them, which is the whole reason they are extras,
# so a host that runs both has to have been synced for both.
needed="httpx"
[ "${asks_globus}" = yes ] && needed="${needed}, globus_sdk, globus_compute_sdk, alcf_tokens"
[ "${asks_scans}" = yes ] && needed="${needed}, epics"
"${APP_DIR}/.venv/bin/python3" -c "import ${needed}" 2>/dev/null \
    || die "the virtualenv cannot import ${needed}, which this watcher needs.
    Re-sync with SYNC=1, which picks the extras from WATCH."
say "libraries   ${needed} importable"

# The credential, before the service is started rather than at its first
# pass. A token store that is absent or belongs to nobody makes a watcher
# that starts, fails every pass, and is restarted forever while looking
# like a facility with nothing outstanding.
#
# Only when a Globus far side was asked for. A watcher that asks a scan
# server has no credential of any kind, and requiring one would refuse
# the only watcher a beamline host is able to run.
if [ "${asks_globus}" = yes ]; then
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
fi

# What a scan watcher needs instead, and for the same reason: a client
# that cannot reach the control system fails every pass while looking
# healthy. This asks only whether a channel to the beamline's scan
# server answers, which is the cheapest thing that distinguishes the
# two.
if [ "${asks_scans}" = yes ]; then
    [ -n "${SCAN_PREFIX:-}" ] \
        || die "WATCH names tomoscan, so SCAN_PREFIX is required: it is the
    scan server this host must be able to reach, for example
    SCAN_PREFIX=19bm:TomoScan:. It is checked here and not used by the
    service, which reads the prefix out of each reference instead."
    "${APP_DIR}/.venv/bin/python3" - "${SCAN_PREFIX}" <<'PREFLIGHT' \
        || die "no answer from ${SCAN_PREFIX}StartScan, so every pass would fail.
    Channel Access needs a route to that subnet from this host."
import sys

import epics

prefix = sys.argv[1]
if epics.caget(f"{prefix}StartScan", as_string=True, timeout=5) is None:
    print(f"no answer from {prefix}StartScan", file=sys.stderr)
    raise SystemExit(1)
PREFLIGHT
    say "channel     ${SCAN_PREFIX}StartScan answers"
fi
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
    -e "s|@WATCH_ARGUMENT@|${watch_argument}|" \
    -e "s|@PAUSE@|${PAUSE}|g" \
    "${SCRIPT_DIR}/cora-watcher.service.in" > "${UNIT_DIR}/${UNIT}"

# Where the journal stands before this start, so the checks below read
# only what arrives after it. A whole-history grep answers with the past
# rather than with this deployment, in both directions: last week's
# success phrase satisfies a process that never started, and last week's
# failures fail an install that went perfectly.
# `|| true` because a unit being installed for the first time has no
# journal at all, and journalctl exits non-zero saying so. Under
# `set -euo pipefail` that aborted the script here, after the unit file
# was written and before it was enabled or started, printing nothing.
# So the first install of any unit left it present, disabled and dead,
# and the second install of the same unit worked, which is why this
# survived. An empty cursor is read below as the whole journal, which
# for a unit that has none is exactly this install's own output.
before="$(journalctl --user -u "${UNIT}" --lines 0 --show-cursor --no-pager 2>/dev/null \
    | sed -n 's/^-- cursor: //p' || true)"

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
