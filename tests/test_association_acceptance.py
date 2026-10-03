import copy

import numpy as np
import pytest

from biohub.association_acceptance import acceptance_spec, paired_readout, video_metrics
from biohub.association_artifacts import SELECTOR
from biohub.training_history import (
    _validate_per_video_acceptance,
    _validate_progression,
    atomic_write_json,
    sha256_file,
)

STEMS = ("44b6_a", "44b6_b", "6bba_c", "6bba_d")


def report(values):
    def group(value):
        return {"losses": {"total_loss": {"value": value}},
                "task_metrics": {"precision": 0.9, "recall": 0.9, "accuracy": 0.9}}
    return {**group(sum(values) / 4),
            "by_video": {stem: group(value) for stem, value in zip(STEMS, values, strict=True)},
            "by_lineage": {"44b6": group(sum(values[:2]) / 2), "6bba": group(sum(values[2:]) / 2)}}


@pytest.mark.parametrize("base,values,error", [
    ([1., 1., 1., 1.], [0.98, 0.98, 0.98, 1.01], None),
    ([1., 1., 1., 1.], [0.90, 1., 1., 1.], "improved_videos"),
    ([1., 1., 1., 1.], [0.9, 0.9, 0.9, 1.03], "video_6bba_d"),
    ([0., 1., 1., 1.], [0., 0.98, 0.98, 0.98], None),
    ([0., 1., 1., 1.], [0.0001, 0.98, 0.98, 0.98], "video_44b6_a"),
])
def test_frozen_criteria_feed_existing_numeric_gate(tmp_path, base, values, error):
    baseline, candidate = report(base), report(values)
    spec = acceptance_spec(baseline)
    paired = paired_readout(baseline, candidate)
    path = tmp_path / spec["per_video"]["path"]
    atomic_write_json(path, paired)
    spec["per_video"]["sha256"] = sha256_file(path)
    row = {"val": {"losses": candidate["losses"]}, "best_so_far": True,
           "task_metrics": {name: group["task_metrics"] for name, group in candidate["by_lineage"].items()},
           "val_by_lineage": {name: {"loss": group["losses"]["total_loss"]["value"]}
                              for name, group in candidate["by_lineage"].items()}}
    row["task_metrics"].update(video_metrics(candidate, spec))
    manifest = {"purpose": "candidate", "selector": SELECTOR, "acceptance_thresholds": spec,
                "split": {"validation": {"stems": list(STEMS)}}}
    errors = []
    _validate_progression(tmp_path, manifest, [row], errors)
    if error is None:
        assert not errors
    else:
        assert any(error in value for value in errors), errors


def test_four_video_bootstrap_matches_exact_enumeration():
    baseline, candidate = report([1., 2., 0., 4.]), report([0.9, 1.9, 0., 4.01])
    actual = paired_readout(baseline, candidate)
    excesses = np.array(list(actual["values"].values()))
    grid = np.indices((4, 4, 4, 4)).reshape(4, -1)
    expected = np.percentile(excesses[grid].mean(axis=0), 95, method="linear")
    assert actual["uncertainty"]["upper"] == pytest.approx(expected, abs=1e-15)
    assert actual["values"]["6bba_c"] == 0  # Exact absolute zero, no epsilon or video omission.


@pytest.mark.parametrize("damage", ["pooled_zero", "null_metric", "nan_video", "three_videos"])
def test_undefined_or_incomplete_baseline_is_rejected(damage):
    baseline = report([1., 1., 1., 1.])
    if damage == "pooled_zero":
        baseline["losses"]["total_loss"]["value"] = 0.
    elif damage == "null_metric":
        baseline["by_lineage"]["44b6"]["task_metrics"]["precision"] = None
    elif damage == "nan_video":
        baseline["by_video"]["44b6_a"]["losses"]["total_loss"]["value"] = float("nan")
    else:
        baseline["by_video"].pop("44b6_a")
    with pytest.raises(ValueError):
        acceptance_spec(baseline)


def test_exact_ties_and_video_replacement_do_not_count_as_improvement():
    baseline = report([1., 1., 1., 1.])
    assert video_metrics(copy.deepcopy(baseline), acceptance_spec(baseline))["improved_videos"] == 0
    candidate = copy.deepcopy(baseline)
    candidate["by_video"]["44b6_other"] = candidate["by_video"].pop("44b6_a")
    with pytest.raises(ValueError):
        paired_readout(baseline, candidate)


def test_rehashed_readout_must_still_match_selected_history(tmp_path):
    baseline, candidate = report([1.] * 4), report([0.98] * 4)
    spec = acceptance_spec(baseline)
    path = tmp_path / spec["per_video"]["path"]
    atomic_write_json(path, {"values": dict.fromkeys(STEMS, -100.), "uncertainty": {"upper": -100.}})
    spec["per_video"]["sha256"] = sha256_file(path)  # Correct byte hash does not prove the derivation.
    row = {"val": {"losses": candidate["losses"]}, "task_metrics": video_metrics(candidate, spec)}
    manifest = {"execution_hash_policy": "predeclared_with_result_bindings_v1",
                "acceptance_thresholds": spec, "split": {"validation": {"stems": list(STEMS)}}}
    errors = []
    _validate_per_video_acceptance(tmp_path, manifest, spec["per_video"], errors, rows=[row])
    assert errors == ["Per-video readout differs from selected history"]
