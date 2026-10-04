"""Offline tests for scripts/submission_status.py (higher-is-better conversion).

No network: `fetch` is monkeypatched to return plain objects that carry the
attributes the script reads (ref, public_score, url, date, status, ...).
The script is imported by relative path from this file.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "submission_status.py"
_spec = importlib.util.spec_from_file_location("submission_status_under_test", SCRIPT)
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)


class FakeSub:
    """Just enough of a Kaggle submission object for submission_status.py."""

    def __init__(
        self,
        ref,
        public_score,
        slug="kernel-a",
        version="1",
        day=1,
        status="COMPLETE",
        error_description="",
        total_bytes=1024,
    ):
        self.ref = ref
        self.public_score = public_score
        url = f"https://www.kaggle.com/competitions/demo/submissions/code/user/{slug}"
        if version is not None:
            url += f"?scriptVersionId={version}"
        self.url = url
        self.date = datetime(2026, 8, day, 12, 0)
        self.status = status
        self.error_description = error_description
        self.total_bytes = total_bytes
        self.private_score = ""


def run_main(monkeypatch, capsys, subs, argv):
    monkeypatch.setattr(ss, "COMPETITION", "demo-comp")
    monkeypatch.setattr(ss, "fetch", lambda group=None: subs)
    rc = ss.main(list(argv))
    return rc, capsys.readouterr().out


def run_final_check(monkeypatch, capsys, subs, refs, selected=None):
    selected = set(refs) if selected is None else set(selected)
    sel = [s for s in subs if str(s.ref) in selected]
    monkeypatch.setattr(ss, "fetch", lambda group=None: sel if group is not None else subs)
    monkeypatch.setattr(sys, "argv", ["submission_status.py", "--final-check", *refs])
    rc = ss.final_check(subs)
    return rc, capsys.readouterr().out


def test_score_of_keeps_zero_and_drops_unscored():
    assert ss.score_of(FakeSub(1, 0.0)) == "0.0"
    assert ss.score_of(FakeSub(2, 0.85)) == "0.85"
    assert ss.score_of(FakeSub(3, None)) == ""
    assert ss.score_of(FakeSub(4, "  ")) == ""


def test_kernel_rows_descending_and_earliest_tie(monkeypatch, capsys):
    subs = [
        FakeSub(1, 0.55, slug="kernel-a", day=2),
        FakeSub(2, 0.55, slug="kernel-a", day=3),
        FakeSub(3, 0.50, slug="kernel-a", day=1),
        FakeSub(4, 0.60, slug="kernel-b", day=1),
        FakeSub(5, 0.40, slug="kernel-b", day=2),
    ]
    rc, out = run_main(monkeypatch, capsys, subs, ["--all"])
    assert rc == 0
    table = out.split("unscored")[0]
    assert table.index("kernel-b") < table.index("kernel-a")
    line_a = next(line for line in table.splitlines() if "kernel-a" in line)
    assert "0.550" in line_a
    assert " 1  kernel-a" in line_a
    assert "[TIE x2: 2]" in line_a
    section = out.split("all scored, best first:")[1]
    refs = [int(line.split()[1]) for line in section.splitlines() if line.strip()]
    assert refs == [4, 1, 2, 3, 5]


def test_kernel_rows_best_tie_is_broken_by_slug(monkeypatch, capsys):
    subs = [
        FakeSub(1, 0.60, slug="kernel-z"),
        FakeSub(2, 0.60, slug="kernel-a"),
        FakeSub(3, 0.50, slug="kernel-m"),
    ]
    rc, out = run_main(monkeypatch, capsys, subs, [])
    assert rc == 0
    table = out.split("unscored")[0]
    assert table.index("kernel-a") < table.index("kernel-z") < table.index("kernel-m")


def test_zero_score_is_scored_and_listed(monkeypatch, capsys):
    subs = [
        FakeSub(1, 0.0, slug="kernel-a"),
        FakeSub(2, 0.50, slug="kernel-b"),
        FakeSub(
            3,
            None,
            slug="kernel-c",
            status="ERROR",
            error_description="runtime exceeded",
        ),
    ]
    rc, out = run_main(monkeypatch, capsys, subs, ["--all"])
    assert rc == 0
    assert "scored=2" in out
    section = out.split("all scored, best first:")[1]
    refs = [int(line.split()[1]) for line in section.splitlines() if line.strip()]
    assert refs == [2, 1]
    assert "0.000" in section
    assert " 3  TIMEOUT  kernel-c" in out


def test_final_check_auto_top_two_are_the_highest(monkeypatch, capsys):
    subs = [
        FakeSub(10, 0.90, slug="kernel-a"),
        FakeSub(20, 0.80, slug="kernel-b"),
        FakeSub(30, 0.70, slug="kernel-c"),
    ]
    rc, out = run_final_check(monkeypatch, capsys, subs, ["10", "20"])
    assert rc == 0
    lines = out.splitlines()
    top1 = next(line for line in lines if line.strip().startswith("#1"))
    top2 = next(line for line in lines if line.strip().startswith("#2"))
    assert "ref=10" in top1 and "0.9" in top1
    assert "ref=20" in top2 and "0.8" in top2
    assert "auto-selection happens to match the plan" in out
    assert "CONFIRMED" in out

    rc, out = run_final_check(monkeypatch, capsys, subs, ["10", "30"])
    assert rc == 0
    assert "AUTO-SELECTION DOES NOT MATCH THE PLAN" in out


def test_final_check_warns_when_auto_top_two_boundary_is_tied(monkeypatch, capsys):
    subs = [
        FakeSub(10, 0.90, slug="kernel-a"),
        FakeSub(20, 0.80, slug="kernel-b"),
        FakeSub(30, 0.80, slug="kernel-c"),
    ]
    rc, out = run_final_check(monkeypatch, capsys, subs, ["10", "30"])
    assert rc == 0
    assert "auto-selection ambiguous; manual selection/readback required" in out
    assert "top-2 boundary" in out
    assert "auto-selection happens to match the plan" not in out
    assert "AUTO-SELECTION DOES NOT MATCH THE PLAN" not in out
    assert "CONFIRMED" in out
    assert "RESULT: PASS" in out


def test_final_check_better_peer_same_version_fails(monkeypatch, capsys):
    subs = [
        FakeSub(10, 0.50, slug="kernel-a", version="7", day=1),
        FakeSub(11, 0.60, slug="kernel-a", version="7", day=2),
        FakeSub(20, 0.55, slug="kernel-b", version="1", day=1),
    ]
    rc, out = run_final_check(monkeypatch, capsys, subs, ["10", "20"])
    assert rc == 1
    slot1 = out.split("=== slot2")[0]
    assert "FAIL: not this kernel's best draw -- 0.600 is" in slot1
    assert "ref 11, same scriptVersionId 7" in slot1
    assert "RESULT: FAIL" in out


def test_final_check_better_peer_other_version_warns(monkeypatch, capsys):
    subs = [
        FakeSub(10, 0.50, slug="kernel-a", version="7", day=1),
        FakeSub(12, 0.60, slug="kernel-a", version="8", day=2),
        FakeSub(20, 0.55, slug="kernel-b", version="1", day=1),
    ]
    rc, out = run_final_check(monkeypatch, capsys, subs, ["10", "20"])
    assert rc == 0
    slot1 = out.split("=== slot2")[0]
    assert "FAIL: not this kernel's best draw" not in slot1
    assert "WARN: better draw exists -- 0.600 is" in slot1
    assert "ref 12" in slot1
    assert "another or unknown" in slot1


@pytest.mark.parametrize("slot_version, peer_version", [(None, None), ("7", None)])
def test_final_check_better_peer_unknown_version_warns(
    monkeypatch, capsys, slot_version, peer_version
):
    subs = [
        FakeSub(10, 0.50, slug="kernel-a", version=slot_version, day=1),
        FakeSub(13, 0.60, slug="kernel-a", version=peer_version, day=2),
        FakeSub(20, 0.55, slug="kernel-b", version="1", day=1),
    ]
    rc, out = run_final_check(monkeypatch, capsys, subs, ["10", "20"])
    assert rc == 0
    slot1 = out.split("=== slot2")[0]
    assert "FAIL: not this kernel's best draw" not in slot1
    assert "WARN: better draw exists -- 0.600 is" in slot1


def test_final_check_tie_at_best_boundary_warns_not_fails(monkeypatch, capsys):
    subs = [
        FakeSub(21, 0.55, slug="kernel-a", version="1", day=1),
        FakeSub(20, 0.55, slug="kernel-a", version="1", day=2),
        FakeSub(30, 0.40, slug="kernel-b", version="1", day=1),
    ]
    rc, out = run_final_check(monkeypatch, capsys, subs, ["20", "30"])
    assert rc == 0
    slot1 = out.split("=== slot2")[0]
    assert "FAIL" not in slot1
    assert "WARN: tie at 0.550 across refs ['21', '20']" in slot1
    assert "earliest is 21" in slot1
