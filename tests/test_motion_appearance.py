import numpy as np
import pytest

from biohub.public_postproc import graph_ops as go
from biohub.public_postproc.config import build_config
from biohub.public_postproc.pipeline import new_stats


def test_assignment_cost_and_geometric_gate(tmp_path, monkeypatch):
    cfg = build_config(
        {
            "BIOHUB_OUTPUT_MOTION_RELINK": "1",
            "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
            "BIOHUB_MOTION_RELINK_RELAXED_UM": "10.0",
        },
        test_dir=tmp_path,
    )

    def nodes(x3):
        return {
            1: {"node_id": 1, "t": 0, "z": 0, "y": 0, "x": 0},
            2: {"node_id": 2, "t": 1, "z": 0, "y": 0, "x": 1},
            3: {"node_id": 3, "t": 1, "z": 0, "y": 0, "x": x3},
        }

    probs = {(1, 2): 0.8, (1, 3): 0.7}
    e0 = np.zeros(32, dtype=np.float32)
    e0[0] = 1
    frame = {
        "t_source": 0,
        "t_target": 1,
        "source_ids": [1],
        "target_ids": [2, 3],
        "primary_source_features": e0[None, :],
        "primary_target_features": np.stack([-e0, e0]),
        "secondary_source_features": e0[None, :],
        "secondary_target_features": np.stack([-e0, e0]),
    }

    calls = []
    real = go.linear_sum_assignment

    def spy(cost):
        calls.append(np.asarray(cost).copy())
        return real(cost)

    monkeypatch.setattr(go, "linear_sum_assignment", spy)

    base = go.motion_relink_edges(cfg, nodes(2), new_stats(), learned_edge_probs=probs)
    baseline_cost = calls[0].copy()
    del calls[:]
    cand = go.motion_relink_edges(
        cfg, nodes(2), new_stats(), learned_edge_probs=probs, appearance_frames={0: frame}
    )
    cand_cost = calls[0].copy()
    del calls[:]
    assert cand_cost.shape == (1, 2)
    np.testing.assert_allclose(cand_cost - baseline_cost, [[2.0, 0.0]], rtol=0, atol=1e-12)
    assert len(base) == 1 and base[0]["source_id"] == 1 and base[0]["target_id"] == 2
    assert len(cand) == 1 and cand[0]["source_id"] == 1 and cand[0]["target_id"] == 3
    assert abs(cand[0]["distance_um"] - 0.8125) < 1e-9
    assert abs(cand[0]["motion_distance_um"] - 0.8125) < 1e-9
    assert abs(cand[0]["edge_prob"] - 0.7) < 1e-9
    assert cand[0]["motion_pass"] == "tight"

    far = nodes(100)
    edges_b = go.motion_relink_edges(cfg, far, new_stats(), learned_edge_probs=probs)
    blocked_base = calls[0].copy()
    del calls[:]
    edges_c = go.motion_relink_edges(
        cfg, far, new_stats(), learned_edge_probs=probs, appearance_frames={0: frame}
    )
    blocked_cand = calls[0].copy()
    del calls[:]
    assert blocked_base[0, 1] == 6001.0
    assert blocked_cand[0, 1] == 6001.0
    assert edges_b == edges_c
    assert len(edges_b) == 1
    assert edges_b[0]["source_id"] == 1 and edges_b[0]["target_id"] == 2


def test_consensus_reservation_precedes_assignment(tmp_path):
    cfg = build_config(
        {
            "BIOHUB_OUTPUT_MOTION_RELINK": "1",
            "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
            "BIOHUB_MOTION_RELINK_RELAXED_UM": "10.0",
        },
        test_dir=tmp_path,
    )
    nodes = {
        1: {"node_id": 1, "t": 0, "z": 0, "y": 0, "x": 0},
        2: {"node_id": 2, "t": 1, "z": 0, "y": 0, "x": 1},
        3: {"node_id": 3, "t": 1, "z": 0, "y": 0, "x": 0.5},
    }
    stats = new_stats()
    edges = go.motion_relink_edges(
        cfg,
        nodes,
        stats,
        learned_edge_probs={(1, 2): 0.1, (1, 3): 0.99},
        consensus_pairs_by_t={0: [(1, 2)]},
    )
    assert [(e["source_id"], e["target_id"]) for e in edges] == [(1, 2)]
    assert edges[0]["motion_pass"] == "consensus_reserved"
    assert stats["motion_relink_consensus_reserved_edges"] == 1


def test_consensus_soft_preference_uses_assignment_and_preserves_probability(tmp_path):
    cfg = build_config(
        {
            "BIOHUB_OUTPUT_MOTION_RELINK": "1",
            "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
            "BIOHUB_MOTION_RELINK_RELAXED_UM": "10.0",
            "BIOHUB_MOTION_RELINK_LEARNED_BONUS": "1.0",
        },
        test_dir=tmp_path,
    )
    nodes = {
        1: {"node_id": 1, "t": 0, "z": 0, "y": 0, "x": 0},
        2: {"node_id": 2, "t": 1, "z": 0, "y": 0, "x": 0.8},
        3: {"node_id": 3, "t": 1, "z": 0, "y": 0, "x": 0.5},
    }
    stats = new_stats()
    edges = go.motion_relink_edges(
        cfg,
        nodes,
        stats,
        learned_edge_probs={(1, 2): 0.0, (1, 3): 0.0},
        consensus_soft_pairs_by_t={0: [(1, 2)]},
    )

    assert [(edge["source_id"], edge["target_id"]) for edge in edges] == [(1, 2)]
    assert edges[0]["motion_pass"] == "tight"
    assert edges[0]["edge_prob"] == 0.0
    assert stats.get("motion_relink_consensus_reserved_edges", 0) == 0


def test_hard_and_soft_consensus_are_mutually_exclusive(tmp_path):
    cfg = build_config(
        {"BIOHUB_OUTPUT_MOTION_RELINK": "1"},
        test_dir=tmp_path,
    )
    nodes = {
        1: {"node_id": 1, "t": 0, "z": 0, "y": 0, "x": 0},
        2: {"node_id": 2, "t": 1, "z": 0, "y": 0, "x": 1},
    }
    with pytest.raises(ValueError, match="hard and soft"):
        go.motion_relink_edges(
            cfg,
            nodes,
            new_stats(),
            consensus_pairs_by_t={0: [(1, 2)]},
            consensus_soft_pairs_by_t={0: [(1, 2)]},
        )


def _mk_frame(t_source, t_target, source_ids, target_ids, src_feats, tgt_feats):
    return {
        "t_source": t_source,
        "t_target": t_target,
        "source_ids": sorted(int(i) for i in source_ids),
        "target_ids": sorted(int(i) for i in target_ids),
        "primary_source_features": np.asarray(src_feats, dtype=np.float32),
        "primary_target_features": np.asarray(tgt_feats, dtype=np.float32),
        "secondary_source_features": np.asarray(src_feats, dtype=np.float32),
        "secondary_target_features": np.asarray(tgt_feats, dtype=np.float32),
    }


def test_none_zero_and_velocity_parity(tmp_path):
    cfg = build_config(
        {
            "BIOHUB_OUTPUT_MOTION_RELINK": "1",
            "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
            "BIOHUB_MOTION_RELINK_RELAXED_UM": "10.0",
            "BIOHUB_MOTION_RELINK_VELOCITY_WEIGHT": "0.5",
        },
        test_dir=tmp_path,
    )
    nodes = {
        1: {"node_id": 1, "t": 0, "z": 0, "y": 0, "x": 0},
        2: {"node_id": 2, "t": 1, "z": 0, "y": 0, "x": 1},
        3: {"node_id": 3, "t": 2, "z": 0, "y": 0, "x": 2},
    }
    e0 = np.zeros(32, dtype=np.float32)
    e0[0] = 1.0
    feats = e0[None, :]
    frames = {
        0: _mk_frame(0, 1, [1], [2], feats, feats),
        1: _mk_frame(1, 2, [2], [3], feats, feats),
    }

    stats_a = new_stats()
    edges_a = go.motion_relink_edges(cfg, nodes, stats_a)
    stats_b = new_stats()
    edges_b = go.motion_relink_edges(cfg, nodes, stats_b, appearance_frames=None)
    stats_c = new_stats()
    edges_c = go.motion_relink_edges(cfg, nodes, stats_c, appearance_frames=frames)

    assert edges_a == edges_b == edges_c
    assert stats_a == stats_b == stats_c

    pairs = sorted((e["source_id"], e["target_id"]) for e in edges_a)
    assert pairs == [(1, 2), (2, 3)]

    per_edge = {e["source_id"]: e for e in edges_a}
    assert per_edge[1]["motion_distance_um"] == 0.40625
    assert per_edge[2]["motion_distance_um"] == 0.203125
    assert per_edge[1]["distance_um"] == 0.40625
    assert per_edge[2]["distance_um"] == 0.40625


def test_relaxed_subset_indexes_full_frame_once(tmp_path, monkeypatch):
    cfg = build_config(
        {
            "BIOHUB_OUTPUT_MOTION_RELINK": "1",
            "BIOHUB_MOTION_RELINK_TIGHT_UM": "6.0",
            "BIOHUB_MOTION_RELINK_RELAXED_UM": "10.0",
            "BIOHUB_MOTION_RELINK_VELOCITY_WEIGHT": "0.5",
        },
        test_dir=tmp_path,
    )
    nodes = {
        1: {"node_id": 1, "t": 0, "z": 0, "y": 0, "x": 0},
        2: {"node_id": 2, "t": 0, "z": 0, "y": 0, "x": 50},
        3: {"node_id": 3, "t": 1, "z": 0, "y": 0, "x": 1},
        4: {"node_id": 4, "t": 1, "z": 0, "y": 0, "x": 68},
    }
    e0 = np.zeros(32, dtype=np.float32)
    e0[0] = 1.0
    e1 = np.zeros(32, dtype=np.float32)
    e1[1] = 1.0
    frame = _mk_frame(
        0, 1, [1, 2], [3, 4], np.stack([e0, e1]), np.stack([e0, -e1])
    )

    costs = []
    real_lsa = go.linear_sum_assignment

    def spy_lsa(cost):
        costs.append(np.array(cost, copy=True))
        return real_lsa(cost)

    monkeypatch.setattr(go, "linear_sum_assignment", spy_lsa)

    base_edges = go.motion_relink_edges(cfg, nodes, new_stats())
    baseline_second = costs[1].copy()
    costs.clear()

    helper_calls = []
    real_helper = go.frame_appearance_penalty

    def spy_helper(*args):
        helper_calls.append(args)
        return real_helper(*args)

    monkeypatch.setattr(go, "frame_appearance_penalty", spy_helper)

    cand_edges = go.motion_relink_edges(
        cfg, nodes, new_stats(), appearance_frames={0: frame}
    )

    assert baseline_second.shape == (1, 1)
    assert costs[1].shape == (1, 1)
    np.testing.assert_allclose(
        costs[1] - baseline_second, [[2.0]], rtol=0, atol=1e-12
    )
    assert len(helper_calls) == 1

    base_pairs = sorted((e["source_id"], e["target_id"]) for e in base_edges)
    cand_pairs = sorted((e["source_id"], e["target_id"]) for e in cand_edges)
    assert base_pairs == cand_pairs == [(1, 3), (2, 4)]
    assert base_edges == cand_edges

    per_edge = {e["source_id"]: e for e in cand_edges}
    assert per_edge[2]["distance_um"] == 7.3125
    assert per_edge[2]["motion_distance_um"] == 7.3125
    assert per_edge[1]["motion_pass"] == "tight"
    assert per_edge[2]["motion_pass"] == "relaxed"
