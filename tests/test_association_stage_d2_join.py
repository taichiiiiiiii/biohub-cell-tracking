import copy
from collections import Counter

import pytest

from biohub.association_stage_diagnostic import _index_stage_d2, join_d2_transitions
from biohub.e26_edge_diagnostic import transition

DS = "d1"
EDGE_A, EDGE_B = 11, 22


def _stage(edge_id, source_id, target_id, dataset=DS):
    return {"dataset": dataset, "gt_edge_id": edge_id,
            "gt_source_id": source_id, "gt_target_id": target_id}


def _d2(edge_id, source_id, target_id, dataset=DS, baseline=None, candidate=None):
    nested = {"gt_edge_id": edge_id, "gt_source_id": source_id, "gt_target_id": target_id}
    return {"dataset": dataset, "gt_edge_id": edge_id,
            "baseline": dict(nested) if baseline is None else baseline,
            "candidate": dict(nested) if candidate is None else candidate}


def test_happy_case_reordered_and_unique_endpoints():
    stage = [_stage(EDGE_A, 1, 2), _stage(EDGE_B, 3, 4)]
    d2 = [_d2(EDGE_B, 3, 4), _d2(EDGE_A, 1, 2)]
    out = _index_stage_d2(DS, stage, d2)
    assert sorted(out) == [EDGE_A, EDGE_B]
    assert out[EDGE_A] is d2[1]


def test_empty_sets_valid():
    assert _index_stage_d2(DS, [], []) == {}


@pytest.mark.parametrize("records", [
    [_stage(EDGE_A, 1, 2), _stage(EDGE_A, 3, 4)],
    [_d2(EDGE_A, 1, 2), _d2(EDGE_A, 3, 4)],
])
def test_duplicate_edge_ids_rejected(records):
    other = ([_d2(EDGE_A, 1, 2)] if records[0]["gt_edge_id"] == EDGE_A and "baseline" not in records[0]
             else [_stage(EDGE_A, 1, 2)])
    with pytest.raises(ValueError):
        _index_stage_d2(DS, records if "baseline" not in records[0] else other,
                        records if "baseline" in records[0] else other)


def test_duplicate_stage_endpoint_pair_rejected():
    stage = [_stage(EDGE_A, 1, 2), _stage(EDGE_B, 1, 2)]
    d2 = [_d2(EDGE_A, 1, 2), _d2(EDGE_B, 1, 2)]
    with pytest.raises(ValueError):
        _index_stage_d2(DS, stage, d2)


def test_missing_and_extra_d2_rows_rejected():
    stage = [_stage(EDGE_A, 1, 2), _stage(EDGE_B, 3, 4)]
    with pytest.raises(ValueError):
        _index_stage_d2(DS, stage, [_d2(EDGE_A, 1, 2)])
    with pytest.raises(ValueError):
        _index_stage_d2(DS, [_stage(EDGE_A, 1, 2)], [_d2(EDGE_A, 1, 2), _d2(EDGE_B, 3, 4)])


def test_reversed_endpoint_pair_rejected():
    with pytest.raises(ValueError):
        _index_stage_d2(DS, [_stage(EDGE_A, 1, 2)], [_d2(EDGE_A, 2, 1)])


def test_candidate_endpoint_disagreement_rejected():
    row = _d2(EDGE_A, 1, 2, candidate={"gt_edge_id": EDGE_A, "gt_source_id": 1, "gt_target_id": 3})
    with pytest.raises(ValueError):
        _index_stage_d2(DS, [_stage(EDGE_A, 1, 2)], [row])


@pytest.mark.parametrize("mutate", [
    lambda r: r.update({"dataset": "other"}),
    lambda r: r["baseline"].update({"gt_source_id": True}),
    lambda r: r["candidate"].update({"gt_target_id": 2.0}),
    lambda r: r.update({"gt_edge_id": 1.0}),
])
def test_bad_dataset_or_identity_types_rejected(mutate):
    stage = [_stage(EDGE_A, 1, 2)]
    d2 = [_d2(EDGE_A, 1, 2)]
    mutate(d2[0] if mutate is not None and "dataset" not in str(mutate) else d2[0])
    with pytest.raises(ValueError):
        _index_stage_d2(DS, stage, d2)


def test_wrong_dataset_on_stage_row_rejected():
    with pytest.raises(ValueError):
        _index_stage_d2(DS, [_stage(EDGE_A, 1, 2, dataset="x")], [_d2(EDGE_A, 1, 2)])


def test_large_ids_supported():
    big = 2 ** 53 + 1
    stage = [_stage(big, big, 2)]
    d2 = [_d2(big, big, 2)]
    assert list(_index_stage_d2(DS, stage, d2)) == [big]


def test_inputs_not_mutated():
    stage = [_stage(EDGE_A, 1, 2)]
    d2 = [_d2(EDGE_A, 1, 2)]
    before = (copy.deepcopy(stage), copy.deepcopy(d2))
    _index_stage_d2(DS, stage, d2)
    assert (stage, d2) == before


# --- appended to tests/test_association_stage_d2_join.py ---


_JOIN_TRANSITIONS = [
    ("tp", "tp", "retained_tp"),
    ("tp", "both_unmatched", "lost_tp"),
    ("both_unmatched", "tp", "gained_tp"),
    ("both_unmatched", "both_unmatched", "shared_fn"),
]


def _join_arm(edge_id, source_id, target_id, state, csv_edge_present):
    matched = state != "both_unmatched"
    def endpoint(node_id):
        if not matched:
            return None
        return {"submitted_node_id": node_id}

    return {
        "gt_edge_id": edge_id,
        "gt_source_id": source_id,
        "gt_target_id": target_id,
        "matched_source": endpoint(source_id),
        "matched_target": endpoint(target_id),
        "csv_edge_present": csv_edge_present if matched else False,
        "state": state,
    }


def _join_fixtures(dataset="synthetic-join4"):
    stage_records = []
    d2_records = []
    pre_counts = Counter()
    for index, (baseline_state, candidate_state, _name) in enumerate(_JOIN_TRANSITIONS):
        edge_id = 100 + index
        source_id = 200 + index
        target_id = 300 + index
        matched = baseline_state != "both_unmatched"
        stage_records.append(
            {
                "dataset": dataset,
                "gt_edge_id": edge_id,
                "gt_source_id": source_id,
                "gt_target_id": target_id,
                "stage_views": {
                    "final": {
                        "source_id": source_id if matched else None,
                        "target_id": target_id if matched else None,
                        "both_matched": matched,
                        "edge_present": matched,
                    }
                },
                "fixed_pre_pair_state": "origin_candidate_retained",
                "matrix_read": False,
                "official_tp_claimed": False,
            }
        )
        pre_counts["origin_candidate_retained"] += 1
        d2_records.append(
            {
                "dataset": dataset,
                "gt_edge_id": edge_id,
                "transition": _name,
                "baseline": _join_arm(
                    edge_id, source_id, target_id, baseline_state, True
                ),
                "candidate": _join_arm(
                    edge_id, source_id, target_id, candidate_state, True
                ),
            }
        )
    stage = {
        "schema_version": "biohub.association.graph_stage_diagnostic.v1",
        "status": "GRAPH_STAGE_DIAGNOSTIC_COMPLETE",
        "matching_mode": "distance7um_without_edge_short_circuit",
        "dataset": dataset,
        "records": stage_records,
        "summary": {
            "gt_edges": len(stage_records),
            "fixed_pre_pair_states": dict(pre_counts),
        },
        "official_score_computed": False,
        "causal_intervention_performed": False,
        "matrix_read": False,
        "submission_authorized": False,
    }
    return stage, d2_records


def test_join_orders_by_stage_and_counts_all_transitions():
    stage, d2_records = _join_fixtures()
    shuffled = list(reversed(d2_records))
    result = join_d2_transitions(stage, shuffled)
    assert result["schema_version"] == "biohub.association.stage_d2_join.v1"
    assert result["status"] == "STAGE_D2_JOIN_COMPLETE_NOT_ADOPTION"
    assert result["dataset"] == stage["dataset"]
    assert [row["gt_edge_id"] for row in result["records"]] == [
        row["gt_edge_id"] for row in stage["records"]
    ]
    assert result["summary"]["d2_transitions"] == {
        "retained_tp": 1,
        "lost_tp": 1,
        "gained_tp": 1,
        "shared_fn": 1,
    }
    assert sum(result["summary"]["d2_transitions"].values()) == result["summary"]["gt_edges"]
    assert result["summary"]["baseline_final_assignment_differences"] == 0
    assert result["summary"]["baseline_final_csv_edge_presence_differences"] == 0
    for flag in (
        "official_score_computed",
        "causal_intervention_performed",
        "matrix_read",
        "submission_authorized",
    ):
        assert result[flag] is False


def test_join_does_not_mutate_or_alias_inputs():
    stage, d2_records = _join_fixtures()
    stage_before = copy.deepcopy(stage)
    d2_before = copy.deepcopy(d2_records)
    result = join_d2_transitions(stage, d2_records)
    row = result["records"][0]
    row["stage_views"]["final"]["source_id"] = -1
    row["extra"] = True
    result["records"].append({})
    result["summary"]["d2_transitions"]["retained_tp"] = 99
    assert stage == stage_before
    assert d2_records == d2_before


def test_join_accepts_empty_records():
    stage, d2_records = _join_fixtures()
    empty_stage = copy.deepcopy(stage)
    empty_stage["records"] = []
    empty_stage["summary"] = {"gt_edges": 0, "fixed_pre_pair_states": {}}
    result = join_d2_transitions(empty_stage, [])
    assert result["records"] == []
    assert result["summary"]["gt_edges"] == 0
    assert result["summary"]["d2_transitions"] == {
        "retained_tp": 0,
        "lost_tp": 0,
        "gained_tp": 0,
        "shared_fn": 0,
    }


def test_join_allows_official_short_circuit_assignment_difference():
    stage, d2_records = _join_fixtures()
    index = 2
    final = stage["records"][index]["stage_views"]["final"]
    final["source_id"] = 200 + index + 2
    final["target_id"] = 300 + index + 2
    final["both_matched"] = True
    final["edge_present"] = False
    result = join_d2_transitions(stage, d2_records)
    row = result["records"][index]
    assert row["baseline_final_assignment_equal"] is False
    assert row["baseline_final_csv_edge_presence_equal"] is True
    assert result["summary"]["baseline_final_assignment_differences"] == 1
    assert result["summary"]["baseline_final_csv_edge_presence_differences"] == 0


def test_join_allows_both_matched_edge_not_official_tp():
    stage, d2_records = _join_fixtures()
    d2_records[0]["baseline"]["state"] = "both_matched_edge_not_official_tp"
    candidate = d2_records[0]["candidate"]
    candidate["state"] = "both_unmatched"
    candidate["matched_source"] = None
    candidate["matched_target"] = None
    candidate["csv_edge_present"] = False
    d2_records[0]["transition"] = transition(
        "both_matched_edge_not_official_tp", "both_unmatched"
    )
    stage["records"][0]["stage_views"]["final"]["edge_present"] = True
    result = join_d2_transitions(stage, d2_records)
    assert result["records"][0]["d2_baseline_state"] == "both_matched_edge_not_official_tp"


def test_join_empty_dataset_string_rejected():
    stage, d2_records = _join_fixtures()
    stage["dataset"] = ""
    with pytest.raises(ValueError):
        join_d2_transitions(stage, d2_records)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda stage, d2: stage.__setitem__("matrix_read", True),
        lambda stage, d2: stage["records"][0].__setitem__("official_tp_claimed", True),
        lambda stage, d2: stage["summary"].__setitem__("gt_edges", 3),
        lambda stage, d2: stage["summary"].__setitem__(
            "fixed_pre_pair_states", {"origin_candidate_retained": 3}
        ),
        lambda stage, d2: stage["records"][0]["stage_views"]["final"].__setitem__(
            "both_matched", 1
        ),
        lambda stage, d2: stage["records"][0]["stage_views"]["final"].__setitem__(
            "source_id", 1.0
        ),
        lambda stage, d2: stage["records"][0]["stage_views"]["final"].__setitem__(
            "edge_present", 1
        ),
        lambda stage, d2: d2[0]["baseline"].__setitem__("state", "both_unmatched"),
        lambda stage, d2: d2[0].__setitem__("transition", "gained_tp"),
    ],
)
def test_join_rejects_malformed_inputs(mutate):
    stage, d2_records = _join_fixtures()
    mutate(stage, d2_records)
    with pytest.raises(ValueError):
        join_d2_transitions(stage, d2_records)


@pytest.mark.parametrize("zero_baseline", [False, True])
def test_join_uses_real_diagnostic_api(zero_baseline):
    import copy
    import warnings

    import polars as pl

    from biohub.association_stage_diagnostic import diagnose_stages
    from biohub.e26_edge_diagnostic import compare_arms, diagnose_arm
    from biohub.evaluate import graph_from_rows

    nodes = pl.DataFrame(
        [(10, 0, 0.0, 0.0, 0.0), (20, 1, 0.0, 0.0, 0.0)],
        schema={"node_id": pl.Int64, "t": pl.Int64, "z": pl.Float64,
                "y": pl.Float64, "x": pl.Float64}, orient="row")
    full_edges = pl.DataFrame({"source_id": [10], "target_id": [20]},
                              schema={"source_id": pl.Int64, "target_id": pl.Int64})
    empty_edges = full_edges.head(0)
    gt = graph_from_rows(nodes, full_edges)
    baseline_edges = empty_edges if zero_baseline else full_edges

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        arm_b = diagnose_arm("synthetic", nodes, baseline_edges, gt, (1., 1., 1.), 2.)
        arm_c = diagnose_arm("synthetic", nodes, empty_edges, gt, (1., 1., 1.), 2.)
    records, _summary = compare_arms(arm_b, arm_c)

    stage = diagnose_stages("synthetic", (nodes, full_edges), (nodes, full_edges),
                            (nodes, baseline_edges), gt, (1., 1., 1.))
    b_copy, c_copy = copy.deepcopy(records), copy.deepcopy(stage)
    join = join_d2_transitions(stage, records)

    assert stage["summary"]["gt_edges"] == 1
    assert len(join["records"]) == 1
    row = join["records"][0]
    stage_record = stage["records"][0]
    baseline_record = records[0]["baseline"]
    assert row["gt_edge_id"] == stage_record["gt_edge_id"]
    assert row["gt_edge_id"] == baseline_record["gt_edge_id"]
    assert row["gt_source_id"] == stage_record["gt_source_id"]
    assert row["gt_source_id"] == baseline_record["gt_source_id"]
    assert row["gt_target_id"] == stage_record["gt_target_id"]
    assert row["gt_target_id"] == baseline_record["gt_target_id"]
    assert join["summary"]["gt_edges"] == 1
    assert join["official_score_computed"] is False
    assert join["matrix_read"] is False
    assert row["d2_transition"] == ("shared_fn" if zero_baseline else "lost_tp")
    assert stage_record["stage_views"]["final"]["both_matched"] is True
    assert row["d2_baseline_state"] == ("both_unmatched" if zero_baseline else "tp")
    assert join["summary"]["baseline_final_assignment_differences"] == (1 if zero_baseline else 0)
    assert join["summary"]["baseline_final_csv_edge_presence_differences"] == 0
    assert records == b_copy
    assert stage == c_copy
