"""No emoji anywhere in source.

Comments, docstrings, log strings, error messages, and `Field(description=...)`
alike. Emoji in source is a documented LLM tell that accumulates as noise
across reviews, and it has no place in a log line an operator greps.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import re

import pytest

from tests.architecture.conftest import tracked_python_files

pytestmark = pytest.mark.architecture

# Pictographic ranges only. Deliberately does NOT include the arrows and
# mathematical-symbol blocks: docstrings legitimately use characters such as
# the rightwards arrow to draw a state transition or a mapping.
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictographs, emoticons, transport, symbols
    "\U0001f000-\U0001f0ff"  # mahjong, dominoes, cards
    "←-⇿"  # arrows, excluded below via the allowlist comment
    "]"
)
_ALLOWED = {"→", "←", "↔", "↳"}


def test_tracked_python_files_carry_no_emoji() -> None:
    hits: list[str] = []
    for path in sorted(tracked_python_files()):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            found = [c for c in _EMOJI.findall(line) if c not in _ALLOWED]
            if found:
                hits.append(f"{path}:{lineno}: {found!r} in {line.strip()}")
    assert not hits, "Emoji in source:\n" + "\n".join(hits)
