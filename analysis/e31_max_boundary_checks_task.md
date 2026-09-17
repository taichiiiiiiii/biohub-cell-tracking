Issue17 active Goal, authoring only qwen3.8-max subscription. No tools/network/filesystem. Return only minimal apply_patch-format patch for src/biohub/primary_consensus_observer.py and tests/test_primary_consensus_observer.py. Existing 23 tests pass. Independent review found frames=1 skips time checks; insert _require(bool((coords[:, 0] == 0).all()), 'single-frame coords times must equal zero') in end_video else branch immediately before expected=n. Add 3 targeted tests using existing helpers: (1) frames1 invalid time1 rejected, valid empty frame accepted using distinct observers; (2) parameterized raw record node_id or t float/bool rejection using _run_full_simple(obs) whose dataset is vid, raw=_raw_nodes_from_coords (returns DICT mapping IDs to records, NEVER list()), mutate raw[101][field], call frames_for('vid',raw), expect 'raw node_id and t must be ints'; (3) run full twoframe pipeline manually using grid=_simple_frames2_coords(), fwd/rev=_make_unique_logits(2,2), then end_video with finalcoords=grid.copy(); finalcoords[:,1:]*=2 (times unchanged), pre_graph and selected_graph using finalcoords and _build_graph(finalcoords,ids), frames_for('scaled',_raw_nodes_from_coords(finalcoords,ids,[0,1,2,3])) must yield same consensus as unscaled _run_full_simple observer output. start_video args(name,2,2,(1,4,4),(1.625,0.40625,0.40625),'softmax'), hooks primary(fwd,None,None),reverse(rev),secondary(None,None,None),mixed(None,None). No scientific changes. Test append after existing test_start_pair_incorrect_times_rejected final line assert obs._failed is True. Current snippets:
    fwd, rev = _make_unique_logits(2, 2)
    assert observer.primary(fwd, None, None) == "reverse"
    assert observer.reverse(rev) == "secondary"
    assert observer.secondary(None, None, None) == "mixed"
    assert observer.mixed(None, None) == "pair"
    assert observer.end_video(coords, None) == name
    graph = _build_graph(coords, ids)
    assert observer.pre_graph(coords, None, ids, graph) == name
    sel_graph = _build_graph(coords, ids)
    assert observer.selected_graph(sel_graph) == name
    return observer


def _raw_nodes_from_coords(coords, node_ids, indices):
    """Generate raw_nodes dict from final coords for given node indices."""
    out = {}
    for idx in indices:
        nid = node_ids[idx]
        out[nid] = {
            "node_id": nid,
            "t": int(coords[idx, 0]),
            "z": int(coords[idx, 1]),
            "y": int(coords[idx, 2]),
            "x": int(coords[idx, 3]),
        }
    return out


# ---------------------------------------------------------------------------
# Helper equivalence
# ---------------------------------------------------------------------------


def test_helper_equivalence_primary_only():
    """Observer uses primary_reciprocal_consensus_pairs, not reimplemented logic."""
    from biohub.consensus_edges import map_consensus_to_raw, primary_reciprocal_consensus_pairs

    fwd_np = np.array([[1.0, 0.2], [0.3, 0.8]], dtype=np.float32)
    rev_np = np.array([[0.9, 0.1], [0.2, 0.7]], dtype=np.float32)
    expected = primary_reciprocal_consensus_pairs(fwd_np, rev_np)
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    obs.start_video("h", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    obs.primary(_FakeTensor(fwd_np.reshape(1, 2, 2)), None, None)
    obs.reverse(_FakeTensor(rev_np.reshape(1, 2, 2)))
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    ids = _ids_simple()
    graph = _build_graph(coords, ids)
    obs.pre_graph(coords, None, ids, graph)
    obs.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    result = obs.frames_for("h", raw)
            )
        video.selected_ids = set(selected)
        return video.name

    def _pending(self, where: str) -> _Video:
        _require(
            self._active is None,
            f"{where} requires end_video to close the active video",
        )
        if where == "pre_graph":
            waiting = [v for v in self._videos.values() if v.final_coords is not None and v.graph_to_detector is None]
        else:
            waiting = [v for v in self._videos.values() if v.graph_to_detector is not None and v.selected_ids is None]
        _require(not any(w.selected_ids is not None for w in waiting), "already completed or no video awaiting graph")
        _require(bool(waiting), "already completed or no video awaiting graph")
        return waiting[-1]

    # ----------------------------------------------------------------- lookup

    @_fail_closed("frames_for")
    def frames_for(self, dataset: str, raw_nodes: dict[int, dict[str, Any]]) -> dict[int, list[tuple[int, int]]]:
        _require(dataset in self._videos, f"unknown dataset {dataset!r}")
        video = self._videos[dataset]
        _require(
            video.selected_ids is not None,
            f"{dataset} has not completed selected_graph",
        )
        _require(type(raw_nodes) is dict, "raw_nodes must be an exact dict")
        mapping = video.graph_to_detector
        times: dict[int, int] = {}
        for node_id, record in raw_nodes.items():
            _require(
                _is_int(node_id) and int(node_id) >= 0,
                "raw node keys must be nonnegative ints",
            )
            node_id = int(node_id)
            _require(isinstance(record, dict), "raw node records must be dicts")
            _require(
                set(record) >= set(_NODE_KEYS),
                "raw node records need at least node_id, t, z, y, x",
            )
            _require(
                _is_int(record["node_id"]) and _is_int(record["t"]),
                "raw node_id and t must be ints",
            )
            _require(
                record["node_id"] == node_id,
                "raw node key must match its node_id attribute",
            )
            _require(
                node_id in mapping,
                "raw node id is outside the recorded graph mapping",
            )
            _require(
                node_id in video.selected_ids,
                "raw node id is not in the selected graph",
            )
            want = video.final_coords[mapping[node_id]]
            got = np.asarray([record["t"], record["z"], record["y"], record["x"]])
            _require(got.shape == (4,), "raw coordinate arity mismatch")
            _require(
                bool((got == want).all()),
                "raw coordinates must match the recorded voxel coords",
            )
            times[node_id] = int(record["t"])
        present = set(times.values())
        result: dict[int, list[tuple[int, int]]] = {}
        for t_idx in range(video.frames - 1):
            if t_idx not in present or t_idx + 1 not in present:
                continue
            _, s_src, e_src, s_tgt, e_tgt = video.ranges[t_idx]
            raw_ids = [gid for gid, stamp in times.items() if stamp in (t_idx, t_idx + 1)]
            result[t_idx] = map_consensus_to_raw(
                video.local_pairs[t_idx],
                list(range(s_src, e_src)),
                list(range(s_tgt, e_tgt)),
                mapping,
                raw_ids,
            )
        return result

end_video current exact branch:
        if video.frames > 1:
            expected = video.ranges[-1][4]
        else:
            expected = n

