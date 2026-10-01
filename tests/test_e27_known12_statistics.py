"""Unit + functional coverage for E27's known-12 baseline raw telemetry validator.

The frozen E26 validator is never edited or monkeypatched here; these tests exercise
the local E27 function directly so the arm/cardinality correction cannot silently
widen any other check.
"""

import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

import scripts.experiments.e27.e27_association_prior_screen as m
from biohub import e26_screen as e

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "outputs" / "local" / "e27_baseline_parity_20260913_v1"
EXPECTED_SHA = {
    "raw_statistics.json": "70df692ecd3768b1a73b830f269aad5b05a1677c6a3368de017d26f349632959",
    "submission.csv": "d4c976c69f850f3f1738523482a272d3468eaf8c99082e128069b9f690ff42a9",
    "CONTROL.json": "85131ef96333b910c89becddce6fade9c2e14d827d4000592a2f85bbe888f315",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_row(dataset: str) -> dict:
    row = {key: 0 for key in e._RAW_REQUIRED_KEYS}
    row["dataset"] = dataset
    row["raw_nodes"] = 1
    row["raw_edges"] = 0
    row["nodes"] = 1
    row["edges"] = 0
    row["division_like_sources"] = 0
    row["motion_relink_fallback_raw"] = 1
    return row


def _raw_rows() -> list[dict]:
    return [_default_row(name) for name in m.STEMS]


def _report() -> dict:
    return {
        "datasets": list(m.STEMS),
        "total_rows": 12,
        "total_nodes": 12,
        "total_edges": 0,
        "per_dataset": [
            {"dataset": name, "nodes": 1, "edges": 0, "forks": 0} for name in m.STEMS
        ],
    }


def test_happy_path_normalizes_twelve_rows_and_preserves_inputs():
    raw_rows = _raw_rows()
    report = _report()
    raw_snapshot = copy.deepcopy(raw_rows)
    report_snapshot = copy.deepcopy(report)

    normalized = m.validate_known12_statistics(raw_rows, arm="baseline", csv_report=report)

    assert [row["dataset"] for row in normalized] == list(m.STEMS)
    assert all(len(row) == len(e._RAW_REQUIRED_KEYS) + 2 for row in normalized)
    for row in normalized:
        assert row["gap_close_effective_max_gap"] is None
        assert row["gap_close_effective_max_gap_absence_reason"] == "not_emitted_by_core"
    assert raw_rows == raw_snapshot
    assert report == report_snapshot


def test_optional_gap_key_is_passed_through():
    raw_rows = _raw_rows()
    raw_rows[0]["gap_close_effective_max_gap"] = 3
    normalized = m.validate_known12_statistics(raw_rows, arm="baseline", csv_report=_report())
    assert normalized[0]["gap_close_effective_max_gap"] == 3
    assert normalized[0]["gap_close_effective_max_gap_absence_reason"] is None


@pytest.mark.parametrize(
    "arm",
    ["candidate", "public4_parity", "eval36", "BASELINE", ""],
)
def test_rejects_arm_other_than_exact_baseline_string(arm):
    with pytest.raises(e.E26Error, match="baseline arm only"):
        m.validate_known12_statistics(_raw_rows(), arm=arm, csv_report=_report())


def test_rejects_nonstring_arm():
    with pytest.raises(e.E26Error, match="baseline arm only"):
        m.validate_known12_statistics(_raw_rows(), arm=None, csv_report=_report())


def test_rejects_wrong_raw_cardinality():
    with pytest.raises(e.E26Error, match="exactly one row per STEMS dataset"):
        m.validate_known12_statistics(_raw_rows()[:11], arm="baseline", csv_report=_report())


def test_rejects_padding_to_thirty_six_rows():
    rows = _raw_rows()
    rows += [_default_row(m.STEMS[0]) for _ in range(24)]
    with pytest.raises(e.E26Error, match="exactly one row per STEMS dataset"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_report_datasets_outside_stems_order():
    report = _report()
    report["datasets"] = list(reversed(m.STEMS))
    with pytest.raises(e.E26Error, match="differs from the known-12 STEMS"):
        m.validate_known12_statistics(_raw_rows(), arm="baseline", csv_report=report)


def test_rejects_raw_row_order_mismatch():
    rows = _raw_rows()
    rows[0], rows[1] = rows[1], rows[0]
    with pytest.raises(e.E26Error, match="raw statistics dataset order mismatch"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_extra_raw_key():
    rows = _raw_rows()
    rows[3]["mystery_counter"] = 1
    with pytest.raises(e.E26Error, match="missing or unexpected keys"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_missing_raw_key():
    rows = _raw_rows()
    del rows[3]["raw_nodes"]
    with pytest.raises(e.E26Error, match="missing or unexpected keys"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_bool_count():
    rows = _raw_rows()
    rows[2]["raw_nodes"] = True
    with pytest.raises(e.E26Error):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_negative_count():
    rows = _raw_rows()
    rows[2]["raw_edges"] = -1
    with pytest.raises(e.E26Error):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_nonfinite_ratio():
    ratio_key = next(iter(sorted(e._RAW_RATIO_KEYS)))
    rows = _raw_rows()
    rows[1][ratio_key] = float("nan")
    with pytest.raises(e.E26Error):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_accepts_integer_zero_ratios():
    rows = _raw_rows()
    for key in e._RAW_RATIO_KEYS:
        rows[0][key] = 0
    normalized = m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())
    assert normalized[0][next(iter(sorted(e._RAW_RATIO_KEYS)))] == 0


def test_rejects_csv_count_mismatch():
    rows = _raw_rows()
    rows[4]["nodes"] = 2
    with pytest.raises(e.E26Error, match="differs from reparsed CSV"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_motion_component_inconsistency():
    rows = _raw_rows()
    rows[5]["motion_relink_tight_edges"] = 1
    with pytest.raises(e.E26Error, match="motion edge component counts differ"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_bad_fallback_flag():
    rows = _raw_rows()
    rows[6]["motion_relink_fallback_raw"] = 2
    with pytest.raises(e.E26Error, match="fallback/skip must be binary"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_fallback_inconsistent_with_motion_edges():
    rows = _raw_rows()
    row = rows[7]
    row["motion_relink_fallback_raw"] = 1
    row["motion_relink_edges"] = 2
    row["motion_relink_tight_edges"] = 1
    row["motion_relink_relaxed_edges"] = 1
    row["raw_edges"] = 5
    with pytest.raises(e.E26Error, match="enabled motion fallback inconsistent"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_rejects_too_many_replaced_raw_edges():
    rows = _raw_rows()
    row = rows[8]
    row["motion_relink_fallback_raw"] = 0
    row["motion_relink_edges"] = 2
    row["motion_relink_tight_edges"] = 2
    row["motion_relink_relaxed_edges"] = 0
    row["motion_relink_replaced_raw_edges"] = 3
    row["raw_edges"] = 2
    with pytest.raises(e.E26Error, match="motion replacement exceeds raw edges"):
        m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())


def test_accepts_consistent_replacement_when_not_falling_back():
    rows = _raw_rows()
    row = rows[8]
    row["motion_relink_fallback_raw"] = 0
    row["motion_relink_edges"] = 2
    row["motion_relink_tight_edges"] = 2
    row["motion_relink_relaxed_edges"] = 0
    row["motion_relink_replaced_raw_edges"] = 2
    row["raw_edges"] = 3
    normalized = m.validate_known12_statistics(rows, arm="baseline", csv_report=_report())
    assert normalized[8]["motion_relink_replaced_raw_edges"] == 2


def test_rejects_per_dataset_missing_entry():
    report = _report()
    report["per_dataset"] = report["per_dataset"][:-1]
    with pytest.raises(e.E26Error, match="per_dataset count mismatch"):
        m.validate_known12_statistics(_raw_rows(), arm="baseline", csv_report=report)


def test_execute_baseline_core_no_longer_imports_e26_validator():
    source = inspect.getsource(m.execute_baseline_core)
    assert "validate_raw_statistics" not in source
    assert "validate_known12_statistics(raw_rows, arm=\"baseline\", csv_report=report)" in source


@pytest.mark.skipif(
    not all((ARTIFACT_DIR / name).is_file() for name in EXPECTED_SHA),
    reason="recorded E27 baseline parity artifacts are absent in this environment",
)
def test_recorded_artifacts_pass_hashpinned_validation(tmp_path):
    paths = {name: ARTIFACT_DIR / name for name in EXPECTED_SHA}
    before = {name: _sha256(path) for name, path in paths.items()}
    assert before == EXPECTED_SHA, "artifact bytes drifted from the pinned hashes"

    control = json.loads(paths["CONTROL.json"].read_text(encoding="utf-8"))
    binding = control["generation_input_binding"]["eval36"]["videos"]
    stems = set(m.STEMS)
    shapes = {
        entry["dataset"]: tuple(entry["metadata"]["shape_tzyx"])
        for entry in binding
        if entry["dataset"] in stems
    }
    assert set(shapes) == stems

    report = e.validate_generated_csv(
        paths["submission.csv"], datasets=m.STEMS, shapes=shapes
    )
    raw_rows = json.loads(paths["raw_statistics.json"].read_text(encoding="utf-8"))

    normalized = m.validate_known12_statistics(raw_rows, arm="baseline", csv_report=report)

    assert [row["dataset"] for row in normalized] == list(m.STEMS)
    assert report["total_nodes"] == 250465
    assert report["total_edges"] == 240852
    assert report["total_rows"] == 491317

    after = {name: _sha256(path) for name, path in paths.items()}
    assert after == EXPECTED_SHA

