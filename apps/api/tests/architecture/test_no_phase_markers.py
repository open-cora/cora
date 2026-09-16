"""No phase, iteration, or audit tags in source.

`Phase 8f-d`, `Iter B-3`, `slice 5g-c`, `audit-2026-05-20`: these name a moment
in a plan, and they rot the moment the plan moves. The current code is what is
true; ordering lives in git history.

The check is literal AND shape-based, because the literal forms are easy to
avoid by accident while the shape (`6g-c`, `5g-a`) reads as a coordinate and
sneaks through review.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import re

import pytest

from tests.architecture.conftest import tracked_python_files

pytestmark = pytest.mark.architecture

_PATTERNS = (
    re.compile(r"\bPhase\s+\d", re.IGNORECASE),
    re.compile(r"\bIter(ation)?\s+[A-Z]-?\d", re.IGNORECASE),
    re.compile(r"\bslice\s+\d+[a-z]\b", re.IGNORECASE),
    re.compile(r"\baudit-20\d\d-\d\d-\d\d\b", re.IGNORECASE),
    # A bare plan coordinate such as 6g-c or 5g-a: digit, letter, dash, letter.
    re.compile(r"\b\d+[a-z]-[a-z]\b"),
    # A review-finding reference: `gate-review F2`, `SEC S2`, `impl#11`,
    # `test#6`, `BLOCKING F1`. Same rot as a phase tag and one step worse:
    # it points at a numbered finding in a review whose document does not
    # travel with the code, so a reader cannot look it up even in principle.
    # 25 of these came across with the chassis.
    re.compile(r"\bgate.review\b", re.IGNORECASE),
    re.compile(r"\b(impl|test|review)#\d+", re.IGNORECASE),
)


def test_tracked_python_files_carry_no_phase_markers() -> None:
    hits: list[str] = []
    for path in sorted(tracked_python_files()):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for pattern in _PATTERNS:
                if pattern.search(line):
                    hits.append(f"{path}:{lineno}: {line.strip()}")
                    break
    assert not hits, (
        "Phase / iteration / audit tag in source. Git log is the right home:\n" + "\n".join(hits)
    )
