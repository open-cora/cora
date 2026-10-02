"""Every app that deploys from a commit ships the same script to do it.

`infra/deploy/push.sh` reads which app it belongs to from where it sits,
so the same bytes serve a conductor and a reporter. That is what lets each
mirror carry its own copy, as it carries its own licence, and it is also
what makes the copies able to drift: nothing in either project compares
them, because each project's suite enumerates only its own directory.

It is not in `SHARED_FILES` because that rule requires a copy in every
project including the checkout itself, and only the apps installed into a
home directory have one. The keeper deploys into `/local/cora` and has no
business with this script. So this ranges over whoever has one, which
means an app that gains a copy later is covered without anybody
remembering to list it, and the thinker is the one that did.

What the thinker's copy proved is that the script was never only about
beamlines. It required one, and a thinker has none to give, so the
requirement moved into the two installers that genuinely cannot work
without it and the shipping script stopped asking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

RELATIVE = "infra/deploy/push.sh"
"""Where an app keeps the script, under its own root."""

MINIMUM = 2
"""How many copies must exist before comparing them means anything.

A rule ranging over one file passes by agreeing with itself, and one
ranging over none passes louder. Two is where this stops being free.
"""


def _copies() -> dict[str, Path]:
    apps = TREE_ROOT / "apps"
    return {
        app.name: app / RELATIVE for app in sorted(apps.iterdir()) if (app / RELATIVE).is_file()
    }


def test_enough_apps_deploy_this_way_for_the_comparison_to_mean_anything() -> None:
    found = _copies()
    assert len(found) >= MINIMUM, (
        f"Found {sorted(found)} carrying {RELATIVE}, and comparing fewer than "
        f"{MINIMUM} copies proves nothing. If an app stopped deploying this "
        "way, say so here rather than leaving a rule that cannot fail."
    )


def test_every_copy_of_the_push_script_is_byte_identical() -> None:
    contents = {app: path.read_bytes() for app, path in _copies().items()}
    assert len(set(contents.values())) == 1, (
        f"{RELATIVE} differs between {sorted(contents)}: "
        f"{ {app: len(body) for app, body in contents.items()} }.\n"
        "These are duplicated rather than shared, so nothing but this check "
        "keeps them in step. The script reads its app from its own path, so "
        "a difference between them is a copy someone forgot to carry across "
        "rather than something one app needs and another does not."
    )


def test_the_script_reads_its_app_from_its_path_rather_than_naming_one() -> None:
    """The property that makes one file serve several apps.

    A copy that named its own app would work where it sits and ship the
    wrong directory from anywhere else, and the identity check above would
    still pass as long as every copy named the same wrong one.
    """
    for app, path in _copies().items():
        body = path.read_text(encoding="utf-8")
        assert 'APP="$(basename "${APP_DIR}")"' in body, (
            f"{app}'s copy does not derive its app from its own location."
        )
        assert 'git archive --format=tar "${SHA}:apps/${APP}"' in body, (
            f"{app}'s copy exports a directory it did not derive."
        )
