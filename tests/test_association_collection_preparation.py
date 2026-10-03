"""Collection planning is image/GT-free and preserves the diagnostic12 boundary."""

from pathlib import Path

import pytest

from scripts.experiments.e23.prepare_e23_association_collection import AUDIT, build, plan_groups, reference_counts

ROOT = Path(__file__).resolve().parents[1]


def videos():
    names = [f"{lineage}_{i:08x}" for lineage in ("44b6", "6bba") for i in range(18)]
    return names, names[:6] + names[18:24]


def test_groups_cover36_once_with_diagnostic12_first_and_balanced_lineages():
    names, first = videos()
    groups = plan_groups(list(reversed(names)), list(reversed(first)))
    assert len(groups) == 9
    flattened = [n for g in groups for n in g["datasets"]]
    assert len(flattened) == len(set(flattened)) == 36
    assert set(flattened) == set(names) and set(flattened[:12]) == set(first)
    for g in groups:
        assert g["datasets"] == sorted(g["datasets"])
        assert sum(n.startswith("44b6_") for n in g["datasets"]) == 2
        assert sum(n.startswith("6bba_") for n in g["datasets"]) == 2


@pytest.mark.parametrize("case", ["missing", "duplicate", "foreign", "unbalanced", "unsafe", "duplicate12"])
def test_invalid_collection_rejected(case):
    names, first = videos()
    if case == "missing":
        names.pop()
    elif case == "duplicate":
        names[-1] = names[0]
    elif case == "foreign":
        first[-1] = "6bba_ffffffff"
    elif case == "unbalanced":
        first = names[:12]
    elif case == "unsafe":
        names[-1] = "../outside"
    else:
        first[-1] = first[0]
    with pytest.raises(ValueError):
        plan_groups(names, first)


def reference():
    return {"dtype": "<i2", "columns": ["t", "z", "y", "x"],
            "stage": "post_detection_pre_graph_pre_ilp", "coordinate_sha256": "1" * 64,
            "frame_counts": [[0, 2], [99, 3]], "rows": 5}


def test_missing_frames_are_literal_zero_not_interpolated():
    counts = reference_counts(reference())
    assert counts == [2] + [0] * 98 + [3]


@pytest.mark.parametrize("change", [
    {"dtype": "<f4"}, {"rows": 4}, {"frame_counts": [[0, 2], [0, 3]]},
    {"frame_counts": [[100, 5]]}, {"frame_counts": [[0, -1], [1, 6]]},
    {"frame_counts": [[0, 2.0], [99, 3]]}, {"coordinate_sha256": "bad"},
    {"frame_counts": [[0, 2049]], "rows": 2049},
    {"frame_counts": [[0, 1001], [1, 1001]], "rows": 2002},
])
def test_invalid_coordinate_reference_rejected(change):
    with pytest.raises(ValueError):
        reference_counts({**reference(), **change})


def test_forged_public4_acceptance_rejected_before_reference_access(tmp_path):
    target = tmp_path / AUDIT
    target.parent.mkdir(parents=True)
    target.write_text('{"status":"PARENT_PUBLIC4_ARTIFACT_AUDIT_PASS"}')
    with pytest.raises(ValueError, match="frozen input changed"):
        build(tmp_path)


def test_real_frozen36_reference_inventory_and_budget():
    if not (ROOT / AUDIT).exists():
        pytest.skip("local frozen artifact audit unavailable")
    result = build(ROOT)
    assert result["status"] == "REFERENCES_PREPARED_NOT_DISPATCHED"
    assert len(result["datasets"]) == 36 and result["expected_pair_packets"] == 3564
    assert result["expected_dense_pairs"] == 341106074
    assert result["raw_inventory"]["files"] == 1188
    assert result["raw_inventory"]["bytes"] == 10090215
    assert result["limits"]["whole_job_wall_seconds"] == 14400
    assert result["limits"]["whole_observer_seconds"] == 1200
    assert not result["submission_authorized"] and not result["gt_read"]
    assert not result["collection_runner_implemented"]
