#!/usr/bin/env bash
# Brings this host's units back after a boot that came up without them.
#
#   after-boot.sh check
#   after-boot.sh arm NAME UNIT[=GUARD]...
#   after-boot.sh run NAME UNIT[=GUARD]...
#
# An installer calls the first two and cron calls the third. The same bytes
# serve every app that installs `systemd --user` units, so each mirror
# carries its own copy, as it carries its own push.sh, and a test in the
# development tree proves the copies identical.
#
# ## What goes wrong without it
#
# `systemd --user` reads units only from the account's home, and the home
# on these hosts is NFS. A lingering user manager starts at boot whether or
# not that home has been mounted yet. When it has not, the manager finds no
# unit directory, starts an empty default target, and nothing makes it look
# again: the units a boot starts are the ones the manager found when it
# started. So every unit stays down, `is-enabled` still reads enabled from
# the symlink on disk, and the journal says nothing, because nothing was
# ever attempted.
#
# The tell is in `systemctl --user show`: an empty UnitFileState, and a
# ConditionResult of no with no timestamp, because the condition was never
# evaluated. Those were the tells on the central host when a reboot left
# its keeper down for about two weeks, enabled, pinned to that host and
# lingering, and a reload and a start typed by hand brought it back. A
# home mounted after the manager started is the explanation that fits and
# was not measured. Nothing here depends on it: this acts on the state,
# whatever left it, with the one repair that was measured to work.
#
# ## Why cron, and why it is per host
#
# The repair has to start from somewhere that does not wait on the home,
# and the account owns exactly one such place without an administrator:
# its crontab. That lives in the host's own spool on local disk, so it is
# per host where the unit directory is per account. A line armed on one
# host exists there and nowhere else, which is the scoping ConditionHost
# gives a unit, reached from the other side.
#
# Every five minutes rather than once at boot. cron changes into the home
# before it runs a job, so a job fired while the home is missing does not
# run, and one chance at boot would be the same race this exists to stop
# losing. A tick that finds no home fails, and a later one finds it there.
#
# This script sits in the home it waits for, and that is not a
# contradiction. cron cannot reach it until the home is mounted, and until
# then there is nothing it could do: the units, the code and the
# virtualenv they start are all in that home too.
#
# ## What it starts, and what it leaves alone
#
# A unit named on the line is started only when all of these hold:
#
#   - its file is in the unit directory, and it is enabled there
#   - its ConditionHost names this host
#   - it is not running, and has not begun to start since the manager came up
#
# The last is what keeps this from fighting a person. A unit somebody
# stopped has run since the manager started, so it stays stopped, and one
# somebody disabled is not considered at all. What is left is exactly what
# the boot would have started and did not, which is all this does.
#
# A unit with no ConditionHost is never started here, even though a boot
# would start it. On a home shared by a dozen machines a unit pinned to
# nothing is not this host's to claim, and starting it here would only add
# a copy.
#
# The manager is told to reload only when it cannot see a named unit's
# file, which is the state a boot without the home leaves behind and the
# only one a reload repairs.
#
# ## Guards
#
# A unit may name a guard after an equals sign: an executable that has to
# succeed before this job starts that unit, and whose output says why when
# it does not. An installer starting a unit is a person deciding to. This
# job starting one is nobody deciding, so a unit whose return could
# surprise somebody carries a guard, and its installer names it here.
#
# A guard is called with the unit's name, which is how one guard stands
# beside several units and answers for each. A guard that needs nothing
# to know which unit it holds ignores the name.
#
# A guard holds only this job. A person starting the unit by hand is not
# asked, because a person is the decision the guard was waiting for.
#
# ## Where it writes
#
# Nothing when there is nothing to do, which is every tick but the ones
# after a boot that went wrong. What it does do goes to the journal under
# the job's own name:
#
#   journalctl --user -t NAME
#
# The account can read those lines only where the journal is persistent,
# which means /var/log/journal exists on the host. A volatile journal keeps
# them where only an administrator can read them.
#
# Not to a file, because the crontab line carries no redirection. cron
# runs a line with whatever shell the crontab names, which on an account
# shared with a beamline is not this script's to choose, and the shells
# spell redirection differently. So the line is plain words every one of
# them parses alike, and this script routes its own output.

set -euo pipefail

SCHEDULE="*/5 * * * *"

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

UNIT_DIR="${HOME}/.config/systemd/user"

# Where enabling puts its symlink, read from disk rather than asked of the
# manager. A manager that started before the home did cannot answer for a
# directory it never read, which is the whole situation this handles.
WANTS="${UNIT_DIR}/default.target.wants"

PATH="${PATH}:/usr/local/bin:/usr/bin:/bin"

refuse() { printf 'refused: %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '4,6p' "${SELF}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

# The words a crontab line may carry. cron hands the line to a shell, so
# anything a shell would read as more than a word cannot be in it.
safe_word() {
  case "$1" in
    "" | *[!A-Za-z0-9/._@+=-]*) return 1 ;;
  esac
}

valid_name() {
  case "$1" in
    "" | *[!A-Za-z0-9._-]*) return 1 ;;
  esac
}

valid_spec() {
  local unit="${1%%=*}" guard=""
  [ "$1" = "${unit}" ] || guard="${1#*=}"
  safe_word "$1" || return 1
  case "${unit}" in
    */* | .service) return 1 ;;
    *.service) ;;
    *) return 1 ;;
  esac
  case "${guard}" in
    "" | /*) ;;
    *) return 1 ;;
  esac
}

# This account's crontab, or nothing when it has none.
#
# "No crontab" and "may not use cron" both exit 1, and only the first is
# safe to read as empty. Reading the second as empty would write a crontab
# holding one line over whatever the account already had, and an account
# shared with a beamline may have plenty, so anything but the first is a
# refusal.
read_crontab() {
  local err out
  err="$(mktemp)"
  if out="$(crontab -l 2>"${err}")"; then
    rm -f "${err}"
    printf '%s' "${out}"
    return 0
  fi
  if grep -q '^no crontab for ' "${err}"; then
    rm -f "${err}"
    return 0
  fi
  cat "${err}" >&2
  rm -f "${err}"
  return 1
}

check() {
  command -v crontab >/dev/null 2>&1 \
    || refuse "there is no crontab command on this host, so nothing would bring these units back after it reboots"
  command -v flock >/dev/null 2>&1 \
    || refuse "there is no flock on this host, and the job will not run without one"
  systemctl is-active --quiet crond.service 2>/dev/null \
    || systemctl is-active --quiet cron.service 2>/dev/null \
    || refuse "cron is not running on this host, so nothing would bring these units back after it reboots"
  read_crontab >/dev/null \
    || refuse "this account cannot use cron on this host, so nothing would bring these units back after it reboots. An administrator can allow it in /etc/cron.allow"
}

# Write this job's line into the account's crontab on this host, replacing
# the line it wrote last time and leaving every other line as it was.
arm() {
  local name="${1:-}"
  valid_name "${name}" || refuse "arm needs a name made of letters, digits, dots and dashes"
  shift
  [ "$#" -gt 0 ] || refuse "arm needs at least one unit"
  safe_word "${SELF}" || refuse "${SELF} cannot be written into a crontab line as one word"

  local spec guard
  for spec in "$@"; do
    valid_spec "${spec}" || refuse "${spec} is not a unit, or a unit and an absolute guard, that a crontab line can carry"
    guard=""
    [ "${spec}" = "${spec%%=*}" ] || guard="${spec#*=}"
    if [ -n "${guard}" ] && [ ! -x "${guard}" ]; then
      refuse "the guard ${guard} is not an executable file"
    fi
  done

  local line="${SCHEDULE} /bin/bash ${SELF} run ${name} $* # ${name}"
  local current kept after
  current="$(read_crontab)" \
    || refuse "this account's crontab could not be read, so it is left exactly as it was"
  kept="$(grep -v -e " # ${name}\$" <<<"${current}" || true)"
  {
    if [ -n "${kept}" ]; then
      printf '%s\n' "${kept}"
    fi
    printf '%s\n' "${line}"
  } | crontab - \
    || refuse "cron would not take the new line"

  after="$(read_crontab)" \
    || refuse "the crontab could not be read back, so nothing is known to be armed"
  grep -qxF -- "${line}" <<<"${after}" \
    || refuse "the line was written and did not read back, so nothing is known to be armed"
  printf '%s\n' "${line}"
}

# Whether a unit has begun to start since the manager came up.
#
# The monotonic stamp is zero until the unit first leaves inactive, and a
# reload carries it across for every unit that was already loaded, so zero
# means this boot never tried. A unit that ran and was stopped since is
# not zero, and that is the one a person meant to leave down.
has_run_this_boot() {
  local state since
  state="$(systemctl --user show -p ActiveState --value "$1")"
  since="$(systemctl --user show -p InactiveExitTimestampMonotonic --value "$1")"
  case "${state}" in
    active | activating | reloading | deactivating) return 0 ;;
  esac
  [ "${since:-0}" != "0" ]
}

run() {
  local name="$1"
  shift

  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

  # No manager yet is the ordinary state for the first moments of a boot,
  # and the next tick is soon. Nothing is said, because nothing is wrong.
  systemctl --user show-environment >/dev/null 2>&1 || return 0

  # One run at a time. A guard may wait on a database for minutes, and the
  # next tick should find this one still at work rather than start beside it.
  #
  # Opening the lock also stamps it, so its modification time is the last
  # tick that found a manager. That is how the account itself can tell cron
  # is running this at all, since cron's own log belongs to root on a stock
  # install.
  exec 9>"${XDG_RUNTIME_DIR}/${name}.lock"
  flock -n 9 || return 0

  local host spec unit guard pinned
  host="$(hostname)"
  local -a units=() guards=()
  for spec in "$@"; do
    unit="${spec%%=*}"
    guard=""
    [ "${spec}" = "${unit}" ] || guard="${spec#*=}"
    [ -f "${UNIT_DIR}/${unit}" ] || continue
    [ -L "${WANTS}/${unit}" ] || [ -f "${WANTS}/${unit}" ] || continue
    pinned="$(sed -n 's/^ConditionHost=//p' "${UNIT_DIR}/${unit}" | head -n 1)"
    [ -n "${pinned}" ] && [ "${pinned}" = "${host}" ] || continue
    units+=("${unit}")
    guards+=("${guard}")
  done
  [ "${#units[@]}" -gt 0 ] || return 0

  local -a unseen=()
  for unit in "${units[@]}"; do
    if [ "$(systemctl --user show -p LoadState --value "${unit}")" != "loaded" ]; then
      unseen+=("${unit}")
    fi
  done
  if [ "${#unseen[@]}" -gt 0 ]; then
    echo "the user manager here had not read ${unseen[*]}, so it is told to read its unit directory again"
    systemctl --user daemon-reload
  fi

  local i
  for i in "${!units[@]}"; do
    unit="${units[${i}]}"
    guard="${guards[${i}]}"
    has_run_this_boot "${unit}" && continue
    if [ -n "${guard}" ] && ! "${guard}" "${unit}"; then
      echo "holding ${unit}: ${guard} would not let this job start it, so it waits for a person"
      continue
    fi
    if systemctl --user start "${unit}"; then
      echo "started ${unit}, which this boot had not"
    else
      echo "could not start ${unit}. journalctl --user -u ${unit} says why"
    fi
  done
}

case "${1:-}" in
  check)
    check
    ;;
  arm)
    shift
    arm "$@"
    ;;
  run)
    shift
    valid_name "${1:-}" || usage
    name="$1"
    run "$@" 2>&1 | logger -t "${name}"
    ;;
  *)
    usage
    ;;
esac
