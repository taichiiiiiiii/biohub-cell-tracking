QwenCloud qwen3.8-max implementation, Issue16/17, no tools/IO/network/agents. Current real test outcome20passed2failed; route positive test now flash and max passed. Return ONLY one small unified diff for src/biohub/primary_consensus_observer.py and tests/test_primary_consensus_observer.py. Parent formatting commands handle formatting, so don't emit full files.
Fix real remaining failures:
1 test_subset_mapping helper _build_graph assigns positional coords; chosen target id erroneously given sourcecoords. Change _build_graph(coords3,[ids3[0],ids3[2]]) to use coords3[[0,2]] and same ID list. Remove redundant unused setup before obs3 in this test (unused coords, ids, subset_ids, sel_graph, obs2 plus duplicate _run_full_simple(observer)) and assert exact {0:[(ids3[0],ids3[2])]} not just dict.
2 test_new_video_before_graph_complete_rejected actual valid rejection says 'previous video has not completed selected_graph', regex expects incomplete. Change match to selected_graph, remove unused ids fixture line ONLY in this test.
3 start_pair replace duplicate second n=self._check_coords/e_src cap validation with checks actual coords slices times==t andt+1; keep first chainedbounds check. No invented video.times attr. This avoids waiting until end_video to catch incorrect mapping.
4 _check_coords numeric finite int OR floating dtype excluding bool/complex/object; preserve nonnegative. No casts to hide invalid values.
5 end_video frames1 must all times0; remove unused idx enumerate variable by iterating tuple directly.
6 frames_for require _is_int(record['node_id']) and _is_int(record['t']) before equality check, so bool/float IDs don't pass.
7 helper-equivalence dict(zip(ids,range(4))) must strict=True.
No changes to helper formulas/caps or graph/solver semantic choices. Existing other tests should remain unchanged.
Add exactly2 concise tests using existing PrimaryConsensusObserver, _simple_frames2_coords,_make_unique_logits,_build_graph,_raw_nodes_from_coords,_run_full_simple helpers:
- start_pair incorrect times rejected and observer permanently failed.
- full simple completed observer raw record t changed to float or bool rejected (parameterized).
No physical inference. Return final unified diff with minimal context. Snippets below are sequential extracts from named files, not a contiguous full program.
        _require(
            _is_int(t) and int(t) == video.next_t,
            f"transition sequence error: expected {video.next_t}",
        )
        bounds = [s_src, e_src, s_tgt, e_tgt]
        _require(all(_is_int(v) for v in bounds), "range bounds must be ints")
        s_src, e_src, s_tgt, e_tgt = (int(v) for v in bounds)
        n = self._check_coords(coords)
        _require(0 <= s_src <= e_src == s_tgt <= e_tgt <= n, "invalid or inconsistent range bounds")
        _require(_is_int(t) and int(t) < video.frames - 1, "t must be less than frames-1")
        n = self._check_coords(coords)
        _require(e_src <= n and e_tgt <= n, "range bounds exceed coords length")
        if video.next_t == 0:
            _require(s_src == 0, "first transition must start at source 0")
        else:
            prev = video.ranges[-1]
            _require(
                (s_src, e_src) == (prev[3], prev[4]),
                "source range must equal the previous target range",
            )
        video.ranges.append((t, s_src, e_src, s_tgt, e_tgt))
        video.local_pairs[video.next_t] = []
        if s_src == e_src or s_tgt == e_tgt:
            # Empty transition: skip ALL tensor hooks, return pair-ready immediately.
            video.next_t += 1
            video.state = _PAIR
            return video.state
        video.state = _PRIMARY
        return video.state

    @staticmethod
    def _check_coords(coords: np.ndarray) -> int:
        _require(type(coords) is np.ndarray, "coords must be an exact ndarray")
        _require(coords.ndim == 2 and coords.shape[1] == 4, "coords must have shape (n, 4)")
        _require(np.issubdtype(coords.dtype, np.integer), "grid coords must use an integer dtype")
        _require(bool((coords >= 0).all()), "grid coords must be nonnegative")
        return int(coords.shape[0])
            "end_video requires every declared transition",
        )
        n = self._check_coords(coords)
        if video.frames > 1:
            expected = video.ranges[-1][4]
        else:
            expected = n
        _require(n == expected, "final coords length must equal the last target range end")
        for idx, (t_val, s_src, e_src, s_tgt, e_tgt) in enumerate(video.ranges):
            _require(
                bool((coords[s_src:e_src, 0] == t_val).all()),
                "source block times must equal the transition index",
            _require(
                set(record) >= set(_NODE_KEYS),
                "raw node records need at least node_id, t, z, y, x",
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
            got = np.asarray(
                [record["t"], record["z"], record["y"], record["x"]]
            )
            _require(got.shape == (4,), "raw coordinate arity mismatch")
# Subset mapping
# ---------------------------------------------------------------------------

def test_subset_mapping(observer):
    """Selected graph is a subset; frames_for only returns selected nodes."""
    _run_full_simple(observer)
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    # Only select first source and first target
    subset_ids = [ids[0], ids[2]]
    sel_graph = _build_graph(coords, subset_ids)
    # Re-do selected_graph with subset
    obs2 = PrimaryConsensusObserver()
    _run_full_simple(obs2, "sub")
    # Override selected by creating new observer with subset
    obs3 = PrimaryConsensusObserver()
    coords3 = _simple_frames2_coords()
    ids3 = _ids_simple()
    obs3.start_video("s3", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs3.start_pair(0, 0, 2, 2, 4, coords3)
    fwd, rev = _make_unique_logits(2, 2)
    obs3.primary(fwd, None, None)
    obs3.reverse(rev)
    obs3.secondary(None, None, None)
    obs3.mixed(None, None)
    obs3.end_video(coords3, None)
    obs3.pre_graph(coords3, None, ids3, _build_graph(coords3, ids3))
    obs3.selected_graph(_build_graph(coords3, [ids3[0], ids3[2]]))
    raw = _raw_nodes_from_coords(coords3, ids3, [0, 2])
    result = obs3.frames_for("s3", raw)
    assert isinstance(result, dict)

def test_new_video_before_graph_complete_rejected():
    obs = PrimaryConsensusObserver()
    coords = _simple_frames2_coords()
    ids = _ids_simple()
    obs.start_video("v1", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    obs.start_pair(0, 0, 2, 2, 4, coords)
    fwd, rev = _make_unique_logits(2, 2)
    obs.primary(fwd, None, None)
    obs.reverse(rev)
    obs.secondary(None, None, None)
    obs.mixed(None, None)
    obs.end_video(coords, None)
    # Don't call pre_graph/selected_graph; try starting new video
    with pytest.raises(ValueError, match="incomplete"):
        obs.start_video("v2", 2, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")

    graph = _build_graph(coords, ids)
    obs.pre_graph(coords, None, ids, graph)
    obs.selected_graph(_build_graph(coords, ids))
    raw = _raw_nodes_from_coords(coords, ids, [0, 1, 2, 3])
    result = obs.frames_for("h", raw)
    assert 0 in result
    assert result[0] == map_consensus_to_raw(expected, [0, 1], [2, 3], dict(zip(ids, range(4))), list(raw))


