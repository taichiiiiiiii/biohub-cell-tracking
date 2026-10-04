Issue16/17 QwenCloud qwen3.8-max IMPLEMENTATION corrective patch. No tools/IO/agents/test execution. Return ONE unified diff, NOT full files or prose; only these files: src/biohub/primary_consensus_observer.py, tests/test_primary_consensus_observer.py, tests/test_qwen_implement_launcher.py. Parent ran your delivered tests:17failed5passed, dominant actual exception reverse requires state reverse found primary. New evidence: methods return next state but never assign it. Scope is small explicit patch below. Do NOT change scientific helper or remove valid tests.

Required exact corrections:
A primary: validate logits returned by _matrix against (last range e_src-s_src,last range e_tgt-s_tgt); then video.state=_REVERSE before return.
B reverse: video.state=_SECONDARY before return, after computing pairs/free forward.
C secondary: assign self._hook_state result to video; video.state=_MIXED before return.
D start_pair: bounds 0<=s_src<=e_src==s_tgt<=e_tgt<=n; require t<frames-1 and times of ranges equalt,t+1; prior target offsets are prev[3],prev[4] NOT prev[2],prev[3]. state/other semantics unchanged.
E start_video reject any prior self._videos.values() with selected_ids is None (after end_video but before graph).
F pre_graph: graph table arbitrary order, build dict ID->row, validate duplicate-free ID set equals set(ids), then iterate enumerate(ids) and compare by_id[gid] coord against final_coords[index]. Don't require row order.
G _pending: if where=='pre_graph', select final_coords notNone and graph_to_detector isNone; else select graph_to_detector notNone and selected_ids isNone. Reject no waiting/duplicates. Existing test_duplicate_selected_graph_rejected match 'already completed' must match actual lifecycle rejection too; use message 'already completed or no video awaiting graph' for zero waiting.
H test_empty_ranges_skip_hooks has typo start_pair(2,2,2,2,4,coords) but this is transition1. Change FIRST argument only to1.
I test_helper_equivalence assertion has invalid conditional tautology; import map_consensus_to_raw and compare result[0] to map_consensus_to_raw(expected,[0,1],[2,3],dict(zip(ids,range(4))),list(raw)).
J route positive test parametrization over model in['qwen3.8-flash','qwen3.8-max']; replace hardcoded model in invoke and argv. For max read prompt using (harness.capture/'prompt.bin').read_text() (NO read_prompt helper exists), assert 'User override 2026-09-14' and 'Authoring-only tasks'. pytest already imported. Correct filepath tests/test_qwen_implement_launcher.py.
Only required changes. No full context repetition, <=180 added/removed lines. All current snippets below are from the same files in corresponding order; patch precisely. Helpers _require(condition,message), _matrix(logits,name), _NODE_KEYS=(node_id,t,z,y,x), _is_int are existing unchanged. Provide proper diff header per file. Do not change wrapper which already passes self correctly.

ACTUAL SOURCE SNIPPETS:

    def __init__(self):
        self._videos: dict[str, _Video] = {}
        self._active: _Video | None = None
        self._failed: bool = False

    # ------------------------------------------------------------- video setup

    @_fail_closed("start_video")
    def start_video(
        self,
        name: str,
        frames: int,
        window_size: int,
        downsample: tuple[int, ...],
        scale: tuple[float, ...],
        activation: str,
        *,
        threshold: float = 0.48,
        max_parents: int | None = None,
        max_children: int | None = None,
    ) -> str:
        _require(isinstance(name, str) and bool(name), "name must be a nonempty str")
        _require(_is_int(frames) and int(frames) > 0, "frames must be a positive integer")
        _require(name not in self._videos, f"duplicate video name {name!r}")
        _require(self._active is None, "previous video is still incomplete")
        _require(window_size == CONFIG["window_size"], "window_size must be 2")
        _require(tuple(downsample) == CONFIG["downsample"], "downsample must be (1, 4, 4)")
        _require(tuple(scale) == CONFIG["scale"], "scale must be (1.625, 0.40625, 0.40625)")
        _require(activation == CONFIG["activation"], "activation must be 'softmax'")
        _require(threshold == CONFIG["threshold"], "threshold must be 0.48")
        _require(max_parents is None, "max_parents must be None")
        _require(max_children is None, "max_children must be None")
        self._active = _Video(name, int(frames))
        return self._active.state

    # ------------------------------------------------------------ transitions

    @_fail_closed("start_pair")
    def start_pair(
        self,
        t: int,
        s_src: int,
        e_src: int,
        s_tgt: int,
        e_tgt: int,
        coords: np.ndarray,
    ) -> str:
        video = self._active_video("start_pair")
        _require(video.state == _PAIR, "start_pair requires pair-ready state")
        _require(
            _is_int(t) and int(t) == video.next_t,
            f"transition sequence error: expected {video.next_t}",
        )
        bounds = [s_src, e_src, s_tgt, e_tgt]
        _require(all(_is_int(v) for v in bounds), "range bounds must be ints")
        s_src, e_src, s_tgt, e_tgt = (int(v) for v in bounds)
        _require(0 <= s_src <= e_src, "invalid source range")
        _require(0 <= s_tgt <= e_tgt, "invalid target range")
        n = self._check_coords(coords)
        _require(e_src <= n and e_tgt <= n, "range bounds exceed coords length")
        if video.next_t == 0:
            _require(s_src == 0, "first transition must start at source 0")
        else:
            prev = video.ranges[-1]
            _require(
                (s_src, e_src) == (prev[2], prev[3]),
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

    # ------------------------------------------------------------ logits hooks

    @_fail_closed("primary")
    def primary(self, logits: Any, source: Any, target: Any) -> str:
        video = self._hook_state(_PRIMARY, "primary")
        video.forward = self._matrix(logits, "primary")
        return _NEXT[_PRIMARY]

    @_fail_closed("reverse")
    def reverse(self, transposed_logits: Any) -> str:
        video = self._hook_state(_REVERSE, "reverse")
        matrix = self._matrix(transposed_logits, "reverse")
        fwd = video.forward
        _require(fwd is not None, "reverse called without forward")
        _require(
            matrix.shape == fwd.shape,
            "reverse logits shape must match primary logits shape",
        )
        video.local_pairs[video.next_t] = primary_reciprocal_consensus_pairs(
            fwd, matrix
        )
        video.forward = None
        return _NEXT[_REVERSE]

    @_fail_closed("secondary")
    def secondary(self, logits: Any, source: Any, target: Any) -> str:
        self._hook_state(_SECONDARY, "secondary")
        return _NEXT[_SECONDARY]

    @_fail_closed("mixed")
    def mixed(self, raw: Any, probabilities: Any) -> str:
        video = self._hook_state(_MIXED, "mixed")
        video.next_t += 1
        self._active = None
        return video.name

    @_fail_closed("pre_graph")
    def pre_graph(
        self,
        coords: np.ndarray,
        edges: Any,
        node_ids: list[int],
        graph: Any,
    ) -> str:
        video = self._pending("pre_graph")
        n = self._check_coords(coords)
        _require(
            n == video.final_coords.shape[0],
            "pre_graph coords length must match end_video coords",
        )
        _require(
            np.array_equal(coords, video.final_coords),
            "pre_graph coords must equal the end_video coordinates",
        )
        ids = self._as_node_ids(node_ids, n)
        rows = list(
            graph.node_attrs(attr_keys=list(_NODE_KEYS)).iter_rows(named=True)
        )
        _require(len(rows) == n, "graph node count must match coords count")
        _require(
            [row["node_id"] for row in rows] == ids,
            "graph node ids must match node_ids positionally",
        )
        for index, row in enumerate(rows):
            got = np.asarray([row["t"], row["z"], row["y"], row["x"]])
            _require(got.shape == (4,), "graph coordinate arity mismatch")
            _require(
                bool((got == video.final_coords[index]).all()),
                "graph coordinates must equal the voxel coordinates",
            )
        video.graph_to_detector = {gid: idx for idx, gid in enumerate(ids)}
        return video.name

    @staticmethod
    def _as_node_ids(node_ids: Any, expected_len: int) -> list[int]:
        _require(
            not isinstance(node_ids, dict),
            "node_ids is a positional list of graph ids, not a dict",
        )
        try:
            items = list(node_ids)
        except TypeError as exc:
            raise ValueError("node_ids must be iterable") from exc
        _require(
        return video.name

    def _pending(self, where: str) -> _Video:
        _require(
            self._active is None,
            f"{where} requires end_video to close the active video",
        )
        waiting = [
            v
            for v in self._videos.values()
            if v.final_coords is not None and v.graph_to_detector is None
        ]
        if not waiting:
            waiting = [
                v
                for v in self._videos.values()
                if v.final_coords is not None and v.selected_ids is None
            ]
        _require(bool(waiting), f"{where} found no video awaiting a graph")
        return waiting[-1]

    # ----------------------------------------------------------------- lookup

    @_fail_closed("frames_for")
    def frames_for(
        self, dataset: str, raw_nodes: dict[int, dict[str, Any]]
    ) -> dict[int, list[tuple[int, int]]]:
        _require(dataset in self._videos, f"unknown dataset {dataset!r}")
        video = self._videos[dataset]
        _require(
            video.selected_ids is not None,
            f"{dataset} has not completed selected_graph",
def test_empty_ranges_skip_hooks(observer):
    """Empty middle frame: no tensor hooks called at all."""
    coords = _empty_middle_frames3_coords()
    ids = _ids_empty_middle()
    observer.start_video("e", 3, 2, (1, 4, 4), (1.625, 0.40625, 0.40625), "softmax")
    # Transition 0: source [0,2), target [2,2) -> empty target
    assert observer.start_pair(0, 0, 2, 2, 2, coords) == "pair"
    # Transition 1: source [2,2), target [2,4) -> empty source
    assert observer.start_pair(2, 2, 2, 2, 4, coords) == "pair"
    observer.end_video(coords, None)
    graph = _build_graph(coords, ids)
    observer.pre_graph(coords, None, ids, graph)
    observer.selected_graph(_build_graph(coords, ids))
            "y": int(coords[idx, 2]),
            "x": int(coords[idx, 3]),
        }
    return out


# ---------------------------------------------------------------------------
# Helper equivalence
# ---------------------------------------------------------------------------

def test_helper_equivalence_primary_only():
    """Observer uses primary_reciprocal_consensus_pairs, not reimplemented logic."""
    from biohub.consensus_edges import primary_reciprocal_consensus_pairs

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
    assert 0 in result
    assert result[0] == [(ids[0], ids[2])] if expected == [(0, 0)] else result[0]


# ---------------------------------------------------------------------------
    with pytest.raises(ValueError, match="already completed"):
        obs.selected_graph(_build_graph(coords, ids))


def test_multivideo_different_ids():
def test_canonical_authoring_preserves_dirty_input(harness: Harness) -> None:
    run("git", "-C", harness.root, "switch", "-c", "feature/author")
    original = harness.root / "tracked.txt"
    original.write_text("user WIP\n")
    result = harness.invoke("--parent-reviewed", "--cloud-only", "--cloud-model", "qwen3.8-flash",
                            target=harness.root)
    assert result.returncode == 0, result.stderr.decode()
    argv = queue_argv(harness)
    assert argv[:3] == ["--cloud-only", "--cloud-model", "qwen3.8-flash"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "project_doc_max_bytes=0" in argv
    assert 'features.shell_tool=false' in argv
    assert 'features.unified_exec=false' in argv
    assert original.read_text() == "user WIP\n"
    assert not (harness.root / ".git/biohub-implement.lock").exists()


