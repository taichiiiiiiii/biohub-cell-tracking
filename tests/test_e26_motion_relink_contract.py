"""E26 motion-relink contract tests — isolated control-flow verification.

Hypothesis: removing only E23 motion relink may improve association.
These tests verify the config diff and pipeline conditional logic without
real images, models, or ground-truth data.
"""

import copy
import dataclasses
from pathlib import Path

from biohub.public_postproc import pipeline
from biohub.public_postproc.config import build_config


def _build_tiny_graph() -> tuple[dict[int, dict], list[dict]]:
    """Return a minimal two-node graph t=0 -> t=1 with close finite coordinates."""
    nodes_by_id = {
        1: {"id": 1, "t": 0, "z": 10.0, "y": 50.0, "x": 50.0},
        2: {"id": 2, "t": 1, "z": 10.5, "y": 51.0, "x": 51.0},
    }
    raw_edges = [
        {"source_id": 1, "target_id": 2, "edge_prob": 0.9},
    ]
    return nodes_by_id, raw_edges


class TestMotionRelinkConfigDiff:
    """Test 1: Verify that disabling OUTPUT_MOTION_RELINK is the ONLY config change."""

    def test_only_motion_relink_differs(self, tmp_path: Path) -> None:
        baseline = build_config(test_dir=tmp_path, profile="e23")
        candidate = build_config(
            test_dir=tmp_path,
            profile="e23",
            overrides={"BIOHUB_OUTPUT_MOTION_RELINK": "0"},
        )

        # Compare all fields
        baseline_dict = dataclasses.asdict(baseline)
        candidate_dict = dataclasses.asdict(candidate)

        differing_keys = [
            k for k in baseline_dict if baseline_dict[k] != candidate_dict[k]
        ]

        assert differing_keys == ["OUTPUT_MOTION_RELINK"], (
            f"Expected only OUTPUT_MOTION_RELINK to differ, got: {differing_keys}"
        )
        assert baseline.OUTPUT_MOTION_RELINK is True
        assert candidate.OUTPUT_MOTION_RELINK is False

        # Explicit assertions on other critical fields
        assert baseline.OUTPUT_STEAL_TWIN_REWIRE is False
        assert candidate.OUTPUT_STEAL_TWIN_REWIRE is False
        assert baseline.EXPERIMENT_TAG == candidate.EXPERIMENT_TAG
        assert baseline.TEST_DIR == candidate.TEST_DIR


class TestMotionRelinkDisabledNoCall:
    """Test 2: With MOTION_RELINK=False, motion_relink_edges must never be called."""

    def test_motion_relink_not_called_when_disabled(self, tmp_path: Path) -> None:
        cfg = build_config(
            test_dir=tmp_path,
            profile="e23",
            overrides={"BIOHUB_OUTPUT_MOTION_RELINK": "0"},
        )

        nodes_by_id, raw_edges = _build_tiny_graph()

        # Monkeypatch refine_all_centroids to avoid ValueError when dataset=None
        original_refine = pipeline.refine_all_centroids

        def fake_refine(cfg_arg, nodes_arg, dataset_arg, frame_cache_arg, stats_arg):
            assert dataset_arg is None, "dataset must be None in this test"
            return nodes_arg

        # Monkeypatch motion_relink_edges to raise if called
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("motion_relink_edges should not be called when OUTPUT_MOTION_RELINK is False")

        try:
            pipeline.refine_all_centroids = fake_refine  # type: ignore[assignment]
            pipeline.motion_relink_edges = fail_if_called  # type: ignore[assignment]

            result_nodes, result_edges, result_stats = pipeline.filter_output_graph_pre_linefit(
                cfg=cfg,
                nodes_by_id=nodes_by_id,
                raw_edges=raw_edges,
                dataset=None,
            )

            # Assert all motion_relink_* stats remain 0
            motion_keys = [k for k in result_stats if k.startswith("motion_relink_")]
            for key in motion_keys:
                assert result_stats[key] == 0, f"{key} should be 0, got {result_stats[key]}"

        finally:
            pipeline.refine_all_centroids = original_refine  # type: ignore[assignment]
            # Restore original motion_relink_edges
            from biohub.public_postproc.graph_ops import motion_relink_edges as original_motion
            pipeline.motion_relink_edges = original_motion  # type: ignore[assignment]


class TestMotionRelinkEnabledFallback:
    """Test 3: With MOTION_RELINK=True, motion_relink_edges is called and returns fallback."""

    def test_motion_relink_called_and_fallback_when_enabled(self, tmp_path: Path) -> None:
        cfg = build_config(test_dir=tmp_path, profile="e23")

        # Fresh copy of tiny graph (pipeline mutates inputs)
        nodes_by_id, raw_edges = _build_tiny_graph()
        nodes_by_id = copy.deepcopy(nodes_by_id)
        raw_edges = copy.deepcopy(raw_edges)

        call_count = 0

        # Monkeypatch refine_all_centroids to avoid ValueError when dataset=None
        original_refine = pipeline.refine_all_centroids

        def fake_refine(cfg_arg, nodes_arg, dataset_arg, frame_cache_arg, stats_arg):
            assert dataset_arg is None, "dataset must be None in this test"
            return nodes_arg

        # Monkeypatch motion_relink_edges to record calls and return []
        def record_call(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            return []

        try:
            pipeline.refine_all_centroids = fake_refine  # type: ignore[assignment]
            pipeline.motion_relink_edges = record_call  # type: ignore[assignment]

            result_nodes, result_edges, result_stats = pipeline.filter_output_graph_pre_linefit(
                cfg=cfg,
                nodes_by_id=nodes_by_id,
                raw_edges=raw_edges,
                dataset=None,
            )

            assert call_count == 1, f"motion_relink_edges should be called exactly once, got {call_count}"
            assert result_stats["motion_relink_fallback_raw"] == 1, (
                f"Expected motion_relink_fallback_raw==1, got {result_stats['motion_relink_fallback_raw']}"
            )

        finally:
            pipeline.refine_all_centroids = original_refine  # type: ignore[assignment]
            from biohub.public_postproc.graph_ops import motion_relink_edges as original_motion
            pipeline.motion_relink_edges = original_motion  # type: ignore[assignment]
