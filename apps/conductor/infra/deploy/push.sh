#!/usr/bin/env bash
# Ships a conductor to one beamline host from a revision, and records which.
#
#   BEAMLINE=19-bm HOST=radon ./push.sh          # ships HEAD
#   BEAMLINE=7-bm  HOST=karman ./push.sh v0.4.0  # ships a tag
#
# ## Why this exists rather than an rsync of src
#
# Deploying used to be `rsync -a --delete apps/conductor/src/ host:...`, which
# reads the working tree. Whatever sits open in an editor at that moment is
# what reaches the beamline, and nothing between a keystroke and a running
# experiment refuses it. That is not hypothetical: this tree held an
# unfinished change to the filing seam for most of one day, and either of the
# two deployed beamlines would have taken it.
#
# `git archive` of a commit cannot do that. What lands is something that
# exists in history, so it can be named, compared between beamlines, and
# rolled back to.
#
# ## Why it writes a revision file
#
# A host that cannot say what it runs makes every later question
# unanswerable: whether a fix reached it, whether two beamlines match, what
# to go back to. Before this, the only way to ask was to grep the deployed
# source for a function name and infer.
#
# ## What it does not do
#
# It does not build the virtualenv, which `install.sh` does and only when
# one is missing, and it does not touch the configuration, which holds the
# beamline's token and belongs to whoever runs the keeper.

set -euo pipefail

BEAMLINE="${BEAMLINE:?BEAMLINE is required, for example BEAMLINE=19-bm}"
HOST="${HOST:?HOST is required, for example HOST=radon}"
REF="${1:-HEAD}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TREE="$(cd "${APP_DIR}/../.." && pwd)"
REMOTE="${REMOTE:-cora-conductor}"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

cd "${TREE}"

SHA="$(git rev-parse --verify --quiet "${REF}^{commit}")" \
  || die "no commit named ${REF}"
SUBJECT="$(git log -1 --format=%s "${SHA}")"
DESCRIBED="$(git describe --tags --always "${SHA}" 2>/dev/null || echo "${SHA}")"

echo "Shipping a conductor for ${BEAMLINE} to ${HOST}"
say "revision  ${DESCRIBED} (${SHA})"
say "subject   ${SUBJECT}"
echo

# The whole point of the script, so it is said out loud rather than left for
# the operator to realise afterwards. Shipping a commit while the tree holds
# something else is correct and is usually what is wanted, but it must never
# be a surprise.
DIFFERS="$(git diff --name-only "${SHA}" -- apps/conductor | wc -l | tr -d ' ')"
if [ "${DIFFERS}" != "0" ]; then
  echo "Note"
  say "the working tree differs from ${REF} in ${DIFFERS} file(s) under apps/conductor"
  say "those differences are NOT being shipped. ${DESCRIBED} is."
  git diff --name-only "${SHA}" -- apps/conductor | sed 's/^/    /'
  echo
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT

echo "Export"
git archive --format=tar "${SHA}:apps/conductor" | tar -x -C "${STAGING}" \
  || die "could not export apps/conductor from ${REF}"
[ -f "${STAGING}/infra/deploy/install.sh" ] \
  || die "${REF} has no infra/deploy/install.sh, so it cannot install itself"

# Written into the exported copy so it travels with the code rather than
# being applied afterwards, which would leave a window where a host carries
# the code and not the answer to what it is.
cat > "${STAGING}/REVISION" <<REV
revision ${SHA}
described ${DESCRIBED}
ref ${REF}
subject ${SUBJECT}
beamline ${BEAMLINE}
pushed $(date -u '+%Y-%m-%dT%H:%M:%SZ') by $(whoami)@$(hostname -s)
REV
say "ok"
echo

echo "Copy"
# The virtualenv is not in git and must survive, and on a host that cannot
# reach a package index it cannot be rebuilt at all. Everything else under
# the app directory is replaced, so a file deleted in the revision is
# deleted on the host.
rsync -a --delete --exclude '.venv/' "${STAGING}/" "${HOST}:${REMOTE}/"
say "ok"
echo

echo "Install"
ssh "${HOST}" "cd ${REMOTE}/infra/deploy && BEAMLINE=${BEAMLINE} ./install.sh"
