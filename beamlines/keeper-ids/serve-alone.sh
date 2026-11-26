#!/usr/bin/env bash
# Starts a server only when nothing else already serves its names.
#
#   serve-alone.sh CLIENT_ENV CONTROL NAME... -- COMMAND...
#
# A unit runs this as its ExecStart, with the server as COMMAND, so every
# start passes through it: a boot, a restart after a crash, the after-boot
# job and a person typing systemctl alike. It asks Channel Access whether
# CONTROL answers and whether any NAME does, and then either becomes
# COMMAND or exits saying why not:
#
#   (exec)  CONTROL answers and no NAME does, so the server starts
#   78      something already answers a NAME, or the unit's own line cannot
#           be read, so it refuses, and the unit stays down
#   75      nothing can be concluded yet, so systemd tries again
#
# The same bytes serve every installer that starts a soft IOC under names
# a station may also serve, and a test in the development tree proves the
# copies identical.
#
# ## Why every start, and not only the install
#
# Two servers answering one name is a race whose loser is silent: clients
# reach whichever answers first, and for the keeper id records that files
# a scan against the wrong work. Each installer refuses to install when a
# name already answers, but an installer runs once, and a unit is started
# by a boot, by Restart=always and by the after-boot job with nobody
# looking. The day a station's own database gains these records, the next
# of those starts would put a second server beside it.
#
# ## Why 78 stays down and 75 does not
#
# A refusal is permanent until a person acts, so the unit names 78 in
# RestartPreventExitStatus and systemd does not bring it back fifteen
# seconds later to refuse again, which would bury the reason under a loop.
# It stays failed, systemctl status shows exit status 78, and the log
# carries the record that answered.
#
# A silent CONTROL is not a refusal. An absent record and an unreachable
# station fail identically, so without CONTROL answering, silence proves
# nothing about the names. At boot that is usually the station's own IOC
# not being up yet, so this exits 75 and Restart=always asks again until it
# is. A caget that is not there yet is the same: EPICS base can sit on a
# mount that arrives after the home does.
#
# ## Whose Channel Access settings
#
# The installer's, captured in CLIENT_ENV when its own preflight proved
# them able to see the station: the caget it used, and every EPICS_CA_
# variable its shell had. Not the unit's, for two reasons. The user
# manager's environment is not an operator's login, so the address list
# that found the station at install time is not in it. And what the unit
# does set is the server's: a server port that a client would read as the
# port to search on, and a client address list that softIoc would also
# read as where to send its beacons. So the question runs with the unit's
# EPICS_CA_ and EPICS_CAS_ variables removed and the captured ones in
# their place, and COMMAND starts with the unit's environment untouched.
#
# The names are asked about together rather than in turn, so a start
# waits one timeout and not one per name. The timeout is the installers'
# own: shortening it would let a slow server look absent, which is the one
# mistake this exists to stop.

set -euo pipefail

REFUSED=78
NOT_YET=75
WAIT=5

PATH="${PATH}:/usr/local/bin:/usr/bin:/bin"

say() { printf 'serve-alone: %s\n' "$*"; }

[ "$#" -ge 4 ] || {
  say "the unit's line is not CLIENT_ENV CONTROL NAME... -- COMMAND..., so nothing is started"
  exit "${REFUSED}"
}

CLIENT_ENV="$1"
CONTROL="$2"
shift 2
NAMES=()
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
  NAMES+=("$1")
  shift
done
if [ "${#NAMES[@]}" -eq 0 ] || [ "${1:-}" != "--" ] || [ "$#" -lt 2 ]; then
  say "the unit's line names no records, or no -- before the server, so nothing is started"
  exit "${REFUSED}"
fi
shift

if [ ! -r "${CLIENT_ENV}" ]; then
  say "there are no client settings at ${CLIENT_ENV}, so nothing can ask whether these names are already served. Run the installer again to write them."
  exit "${REFUSED}"
fi

caget=""
assignments=()
while IFS= read -r line || [ -n "${line}" ]; do
  case "${line}" in
    CAGET=*) caget="${line#CAGET=}" ;;
    EPICS_CA_[A-Z]*=*) assignments+=("${line}") ;;
    *) ;;
  esac
done < "${CLIENT_ENV}"

if [ -z "${caget}" ] || [ ! -x "${caget}" ]; then
  say "${CLIENT_ENV} names caget at '${caget}', which is not an executable here yet, so nothing is concluded"
  exit "${NOT_YET}"
fi

# Whether a record answers, asked as the installer asked it.
answers() {
  (
    for variable in $(compgen -e); do
      case "${variable}" in
        EPICS_CA_* | EPICS_CAS_*) unset "${variable}" ;;
      esac
    done
    if [ "${#assignments[@]}" -gt 0 ]; then
      for assignment in "${assignments[@]}"; do
        export "${assignment?}"
      done
    fi
    "${caget}" -w "${WAIT}" "$1" >/dev/null 2>&1
  )
}

if ! answers "${CONTROL}"; then
  say "${CONTROL} did not answer, so a silent name below would prove nothing; asking again at the next start"
  exit "${NOT_YET}"
fi

pids=()
for name in "${NAMES[@]}"; do
  answers "${name}" &
  pids+=("$!")
done
served=()
for i in "${!NAMES[@]}"; do
  if wait "${pids[${i}]}"; then
    served+=("${NAMES[${i}]}")
  fi
done

if [ "${#served[@]}" -gt 0 ]; then
  say "already served by something else: ${served[*]}. A second server is not started beside it. Find what serves it with 'cainfo ${served[0]}'. If the station's own database has gained these records, this unit has done its job: disable it."
  exit "${REFUSED}"
fi

say "${CONTROL} answers and nothing serves ${NAMES[*]}, so the server starts"
exec "$@"
