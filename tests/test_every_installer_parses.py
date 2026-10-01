"""Every shell script this tree ships is at least syntactically a script.

An installer is the one artefact here that no other test runs. The suites
exercise Python, the docs build checks prose, and a `.sh` file is copied
to a beamline and run by hand, where a syntax error is found by whoever
ran it, at the machine, with the floor waiting.

This is the cheapest possible guard and it is not a substitute for reading
them. `bash -n` parses without executing, so it catches an unbalanced
quote, an unterminated block, a `fi` that should be `done`. It cannot
catch a wrong path, a missing preflight, or a command that does the
opposite of what its message says.

## The error that prompted it

```
    PREFIX="${PREFIX:?PREFIX is required, the engine's record prefix}"
```

Bash parses the word after `:?` with its own quoting rules, so the
apostrophe in `engine's` opened a single-quoted string that ran to the
end of the file. The script was eighty lines of correct logic that could
never run, and every other check in this tree passed on it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

TREE = Path(__file__).resolve().parents[1]

EXPECTED_SCRIPTS = 10
"""How many shell scripts this tree tracks.

Pinned because the check below ranges over what git reports, and a rule
ranging over nothing passes. Raise it when a script is added, which is
also the moment to confirm this saw it.

Ten, and more than the installers: six that install something, one that
ships a conductor to a beamline host from a commit, two that scan
migrations for destructive DDL, and the one those two share. The
scanners are already run by the keeper's own lane, so they are covered
twice, which is cheaper than explaining which of the ten are exempt.
"""


def _tracked_scripts() -> list[Path]:
    """Every tracked `.sh`, which is how every other rule here enumerates.

    Through git rather than a glob, so a file git has never seen is
    absent here too rather than silently included from a scratch
    directory.
    """
    listed = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=TREE,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(TREE / name for name in listed)


def test_the_tree_still_has_the_scripts_this_ranges_over() -> None:
    """Guard the enumeration, so a green run below means something."""
    found = _tracked_scripts()
    assert len(found) == EXPECTED_SCRIPTS, (
        f"tracked shell scripts moved: {[str(p.relative_to(TREE)) for p in found]}"
    )


@pytest.mark.parametrize("script", _tracked_scripts(), ids=lambda p: str(p.relative_to(TREE)))
def test_a_tracked_shell_script_parses(script: Path) -> None:
    parsed = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert parsed.returncode == 0, (
        f"{script.relative_to(TREE)} is not valid bash, so it would fail at the "
        f"beamline rather than here:\n{parsed.stderr.strip()}"
    )


def test_the_parse_check_would_catch_something(tmp_path: Path) -> None:
    """A checker that accepted anything would pass on a tree of broken scripts.

    The shape it is written for, rather than an arbitrary one: an
    apostrophe inside the word of a `${name:?word}` expansion, which
    reads as ordinary prose and opens a quote.
    """
    broken = tmp_path / "broken.sh"
    broken.write_text('X="${X:?the engine\'s prefix}"\necho "$X"\n', encoding="utf-8")

    parsed = subprocess.run(
        ["bash", "-n", str(broken)], capture_output=True, text=True, check=False
    )

    assert parsed.returncode != 0
    assert "quote" in parsed.stderr or "EOF" in parsed.stderr
