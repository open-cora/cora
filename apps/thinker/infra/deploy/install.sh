#!/usr/bin/env bash
# Installs the thinker as a `systemd --user` service, with no root and no
# system package.
#
#   ./install.sh
#   WAIT=30 ./install.sh
#
# Re-running it is how a new revision is deployed. It restarts the service
# rather than relying on `enable --now`, which is a no-op against something
# already running and would leave a changed unit on disk that never reaches
# the process.
#
# ## Why there is no beamline here
#
# Every sibling installer takes one and this takes none. A thinker asks the
# keeper for any question nobody has taken up, and an inquiry names an
# execution rather than a beamline, so there is nothing to tell it and
# nothing a second installation would divide.
#
# ## What it does not do
#
# It does not write the configuration, because that file holds the bearer
# token. Minting and distributing those belongs to whoever runs the keeper,
# and a token that this script could create is a token this script could
# create for any caller.
#
# It does not install dependencies when a virtualenv is already present.
# The package declares no core dependencies on purpose, so a working
# install needs `--extra service` for the HTTP client. Set SYNC=1 to do
# that here, which needs a package index.
#
# ## Why it proves two things before it starts anything
#
# A thinker that cannot work is not an error anybody notices. It starts,
# fails, is restarted, fails again, and looks exactly like a facility where
# nobody is asking questions. Both ways that happens are checked here.
#
# The first is the profile. The thinking is named by a dotted path and
# imported at startup, so a path naming nothing is a service that will
# never answer anything. It is loaded here through the entrypoint's own
# loader rather than with a bare import, because the dotted path, the
# attribute lookup and the call are what a deployment depends on and a
# plain import would pass against a profile the service could not load.
#
# The second is the keeper. A token that is refused produces the same
# silence as a facility with no questions in it, and the long poll hides
# it: the service stays up, retrying, reporting nothing. One unwaited ask
# answers it, and proves the address and the certificate on the way.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ETC="${ETC:-${HOME}/.config/cora}"
CONFIG="${CONFIG:-${ETC}/thinker.toml}"
CA_BUNDLE="${CA_BUNDLE:-${ETC}/ca-bundle.crt}"
LOG="${LOG:-${ETC}/thinker.log}"

PROFILE_PATH="${PROFILE_PATH:-${APP_DIR}/infra/thinking}"
WAIT="${WAIT:-30}"

# What a thinking is configured with, which is not what the thinker is.
# Absent for a profile that needs no settings, which is the shipped
# default, and written by whoever deploys one that does.
THINKING_ENV="${THINKING_ENV:-${ETC}/thinking.env}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-thinker.service"
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

echo "Installing a thinker on ${DEPLOY_HOST}"
say "host        ${DEPLOY_HOST}"

[ -r "${CONFIG}" ] || die "no configuration at ${CONFIG}. This script will not write
    it: the file holds a bearer token, and a script that could mint one for
    this caller could mint one for any."

mode="$(stat -c '%a' "${CONFIG}" 2>/dev/null || stat -f '%A' "${CONFIG}")"
[ "${mode}" = "600" ] || die "${CONFIG} is mode ${mode} and holds a token. chmod 600 it."
say "config      ${CONFIG}, mode ${mode}"

[ -r "${CA_BUNDLE}" ] || die "no CA bundle at ${CA_BUNDLE}. The keeper presents a
    certificate from a private CA, so this needs a bundle carrying the system
    anchors plus that one."

[ -d "${PROFILE_PATH}" ] || die "no directory at ${PROFILE_PATH}, so the thinking
    cannot be imported. This repository ships one under infra/thinking; a
    deployment with its own points PROFILE_PATH at that."
say "profile     ${PROFILE_PATH}"
THINKING_ENVIRONMENT=""
if [ -r "${THINKING_ENV}" ]; then
    THINKING_ENVIRONMENT="EnvironmentFile=${THINKING_ENV}"
    say "thinking env ${THINKING_ENV}"
else
    say "thinking env none, so the profile is configured by nothing but itself"
fi
say "thinking    $(sed -n 's/^profile *= *"\(.*\)"/\1/p' "${CONFIG}" 2>/dev/null || echo unknown)"

if [ "${SYNC:-0}" = "1" ]; then
    command -v uv >/dev/null || die "SYNC=1 needs uv on PATH"
    (cd "${APP_DIR}" && uv sync --locked --no-dev --extra service)
fi
[ -x "${APP_DIR}/.venv/bin/python3" ] || die "no virtualenv at ${APP_DIR}/.venv.
    Run again with SYNC=1, or share one built on a machine that can reach a
    package index."

"${APP_DIR}/.venv/bin/python3" -c "import httpx" 2>/dev/null \
    || die "the virtualenv has no httpx, so nothing can reach the keeper.
    Re-sync with --extra service."

# Under the environment the unit is about to be given, or the preflight
# proves a profile loads in conditions the service will not have.
set -a
# shellcheck disable=SC1090
[ -r "${THINKING_ENV}" ] && . "${THINKING_ENV}"
set +a
PYTHONPATH="${PROFILE_PATH}" \
"${APP_DIR}/.venv/bin/python3" - "${CONFIG}" <<'PREFLIGHT' \
    || die "the thinking named by this configuration will not load, so the service
    would start, fail, and be restarted forever while looking like a facility
    nobody is asking questions about."
import sys
from pathlib import Path

import httpx

from thinker.__main__ import concluding_for
from thinker.adapters.http_keeper import HttpKeeper
from thinker.config import load

# The profile is handed the seam that reads the record, so the preflight
# has to build one. Nothing is sent here: a client is opened and a
# profile is constructed, and whether the record answers is the next
# check rather than this one.
config = load(Path(sys.argv[1]))
try:
    with httpx.Client(timeout=15.0) as http:
        thinking = concluding_for(
            config,
            looking=HttpKeeper(http=http, base_url=config.base_url, token=config.token),
        )
except Exception as refused:
    print(f"  {refused}", file=sys.stderr)
    sys.exit(1)
print(f"  profile loaded, and hands back {type(thinking).__name__}")
PREFLIGHT
say "preflight   the thinking loads by the path the configuration names"

SSL_CERT_FILE="${CA_BUNDLE}" "${APP_DIR}/.venv/bin/python3" - "${CONFIG}" <<'PREFLIGHT' \
    || die "the keeper did not answer, or did not accept this token. A thinker
    installed against either stays up, retries, and reports nothing, which
    reads from the outside as a facility with no questions in it."
import sys
from pathlib import Path

import httpx

from thinker.config import load

config = load(Path(sys.argv[1]))
try:
    answered = httpx.get(
        f"{config.base_url.rstrip('/')}/inquiries",
        params={"status": "Open", "limit": 1, "wait": 0},
        headers={"Authorization": f"Bearer {config.token}"},
        timeout=15.0,
    )
except Exception as unreachable:
    print(f"  {config.base_url} could not be reached: {unreachable}", file=sys.stderr)
    sys.exit(1)

if answered.status_code != 200:
    print(
        f"  {config.base_url} answered {answered.status_code}: {answered.text[:200]}",
        file=sys.stderr,
    )
    sys.exit(1)
print(f"  {config.base_url} answered and accepted the token")
PREFLIGHT
say "preflight   the keeper answers and accepts this token"

mkdir -p "${ETC}" "${UNIT_DIR}"

sed -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    -e "s|@CONFIG@|${CONFIG}|g" \
    -e "s|@CA_BUNDLE@|${CA_BUNDLE}|g" \
    -e "s|@PROFILE_PATH@|${PROFILE_PATH}|g" \
    -e "s|@THINKING_ENVIRONMENT@|${THINKING_ENVIRONMENT}|g" \
    -e "s|@WAIT@|${WAIT}|g" \
    -e "s|@LOG@|${LOG}|g" \
    "${SCRIPT_DIR}/cora-thinker.service.in" > "${UNIT_DIR}/${UNIT}"
say "unit        ${UNIT_DIR}/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
systemctl --user restart "${UNIT}"

sleep 3
systemctl --user is-active --quiet "${UNIT}" \
    || die "the service did not stay up. systemctl --user status ${UNIT}"

if systemctl --user show "${UNIT}" --property=NRestarts --value | grep -qv '^0$'; then
    die "the service is up but has already restarted, so it is failing and
    being brought back. Read ${LOG} before believing it works."
fi

say "running     the thinker is holding a request open for up to ${WAIT}s at a time"
say "done        a question nobody has taken up will be claimed and answered"
