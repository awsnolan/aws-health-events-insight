"""Code-hygiene checks for the backfill scripts.

Concrete, verifiable debt from the backlog, encoded as source scans. Items that
are still present are marked xfail(strict=True) so they flip to a failure (a
prompt to drop the marker) once cleaned up. Checks that already hold are plain
asserts and act as regression guards.
"""
import re

import pytest

from conftest import read_source

SINGLE = "HealthEventBackFill.py"
ORG = "HealthEventBackFillOrg.py"


@pytest.mark.xfail(strict=True, reason="backlog: stray debug print(event_data) in get_event_data")
def test_single_has_no_debug_print():
    assert "print(event_data)" not in read_source(SINGLE)


@pytest.mark.xfail(strict=True, reason="backlog: commented-out dead first backfill() block")
def test_single_has_no_commented_dead_backfill():
    assert "# def backfill" not in read_source(SINGLE)


@pytest.mark.xfail(strict=True, reason="backlog: no __main__ guard; backfill() runs on import")
def test_single_has_main_guard_and_no_toplevel_call():
    src = read_source(SINGLE)
    assert 'if __name__ == "__main__":' in src or "if __name__ == '__main__':" in src
    # a bare, unindented backfill() call means it executes on import
    assert not re.search(r"(?m)^backfill\(\)\s*$", src)


def test_org_has_main_guard():
    # Characterization: the org script already guards execution -- keep it that way.
    src = read_source(ORG)
    assert 'if __name__ == "__main__":' in src or "if __name__ == '__main__':" in src


def test_org_has_no_debug_print():
    # Characterization: org script uses logging, not bare prints.
    assert "print(" not in read_source(ORG)


@pytest.mark.xfail(strict=True, reason="backlog: consolidate overlapping backfill implementations")
def test_backfill_logic_not_duplicated():
    import pathlib
    utils = pathlib.Path(__file__).resolve().parents[1] / "src" / "Setup" / "utils"
    definers = [p.name for p in utils.glob("*.py")
                if re.search(r"(?m)^def backfill\(", p.read_text())]
    assert len(definers) <= 1, f"backfill() defined in multiple scripts: {definers}"
