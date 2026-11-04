#!/usr/bin/env bash
# Installs the pursuit turner as a `systemd --user` service, with no root
# and no system package.
#
#   ./install-turner.sh
#
# Re-running it is how a new revision is deployed, and `push.sh` beside it
# is how the files get here. It restarts rather than relying on `enable
# --now`, which is a no-op against something already running and would
# leave a changed unit on disk that never reaches the process.
#
# ## One of these, and not one per beamline
#
# A turner is central. It takes no beamline because the pursuits it turns
# name their own, and there is no second copy to install anywhere: this
# serves the facility. That is why nothing here asks which beamline it is
# for, and why the unit carries no beamline in its name.
#
# ## What it does not do
#
# It does not write the configuration, because that file names a bearer
# token. Minting and distributing those belongs to whoever runs the
# keeper, and a token this script could create is one it could create for
# anybody.
#
# It does not install dependencies when a virtualenv is already present.
# The package declares no core dependencies on purpose, so this needs
# `--extra service` for the HTTP client. It does not need `--extra epics`:
# a turner reaches the record and nothing else, which is most of why it
# can run where no beamline network does.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ETC="${ETC:-${HOME}/.config/cora}"
CONFIG="${CONFIG:-${ETC}/turner.toml}"
CA_BUNDLE="${CA_BUNDLE:-${ETC}/ca-bundle.crt}"
LOG="${LOG:-${ETC}/turner.log}"

VENV="${VENV:-${APP_DIR}/.venv}"
PYTHON="${PYTHON:-${VENV}/bin/python3}"

UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="cora-turner.service"
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'refused: %s\n' "$*" >&2; exit 1; }

say "host        ${DEPLOY_HOST}"
say "config      ${CONFIG}"

[ -x "${PYTHON}" ] || die "no interpreter at ${PYTHON}. Set PYTHON or VENV."

# The configuration is read before the unit is written, so a file that is
# missing or malformed is a message now rather than a service that
# restarts every fifteen seconds for a reason only its log carries.
[ -r "${CONFIG}" ] || die "no configuration at ${CONFIG}. It needs a keeper
    base_url and a token_file, and no beamline: a turner watches every pursuit
    the record will show it. Write it at mode 600 and run this again."

"${PYTHON}" - "${CONFIG}" <<'PY' || die "the configuration above was refused"
import sys
from pathlib import Path

from conductor.config import ConfigError, load_turner

try:
    config = load_turner(Path(sys.argv[1]))
except ConfigError as wrong:
    print(f"  {wrong}")
    raise SystemExit(1) from None
print(f"  keeper      {config.base_url}")
print(f"  pause       {config.pause}s between passes")
PY

mkdir -p "${ETC}" "${UNIT_DIR}"

sed -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
    -e "s|@PYTHON@|${PYTHON}|g" \
    -e "s|@CONFIG@|${CONFIG}|g" \
    -e "s|@CA_BUNDLE@|${CA_BUNDLE}|g" \
    -e "s|@LOG@|${LOG}|g" \
    "${SCRIPT_DIR}/cora-turner.service.in" > "${UNIT_DIR}/${UNIT}"
say "unit        ${UNIT_DIR}/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable "${UNIT}"
systemctl --user restart "${UNIT}"

systemctl --user is-active --quiet "${UNIT}" \
    || die "the service did not stay up. systemctl --user status ${UNIT}"

say "running     one turner for the facility"
say "done        it will say what it did in ${LOG}"
