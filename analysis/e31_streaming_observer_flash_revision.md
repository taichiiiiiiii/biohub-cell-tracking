Issue16 corrective implementation request, qwen3.8-flash subscription. No tools, no edits, output only complete module src/biohub/primary_consensus_observer.py and tests/test_primary_consensus_observer.py. Previous delivery REJECTED before application. We found concrete errors: nonexistent import biohub.reciprocal_consensus; _matrix rejects fake/torch tensor BEFORE detach; pre_graph incorrectly requires identity against a COPY; node_ids is a LIST of graph IDs indexed by detector row, NOT dict indexed by graph ID; frames_for inverts mapping twice and rejects legitimate solver subsets; empty transitions never complete; tests use 3-frame declaration with only one transition, 4 coords for an8 node case and expect invalid code to succeed. DO NOT REPEAT THESE ERRORS. Author a smaller correct version from contract, ~200 lines module and compact tests. No source/filesystem access required; relevant actual APIs inline.

EXACT IMPORT MODULE: biohub.consensus_edges (source below).
EXACT HOOK SIGNATURES: start_video(name,frames,window_size,downsample,scale,activation,*,threshold=.48,max_parents=None,max_children=None); start_pair(t,s_src,e_src,s_tgt,e_tgt,coords); primary(logits,source,target); reverse(transposed_logits); secondary(logits,source,target); mixed(raw,probabilities); end_video(coords,edges); pre_graph(coords,edges,node_ids,graph); selected_graph(graph).

Implementation contracts:
- explicit ValueError validation, fail-closed for exceptions through a small decorator (functools allowed) or equivalent. State: idle->pair->primary->reverse->secondary->mixed->pair; empty transition handled in start_pair WITHOUT any logits hooks and returns pair-ready. Transition sequence 0..frames-2 required. Completed videos kept independently, no comparison to last video's state. New video not permitted while another incomplete. frames positive integer, duplicate names reject.
- frozen config EXACT window_size2/downsample(1,4,4)/scale(1.625,.40625,.40625)/activation softmax/threshold .48/max_parents None/max_children None. No arbitrary threshold or caps allowed.
- start_pair receives numpy coords (n,4), grid coords; strict nonnegative integer ranges, s_src<=e_src==s_tgt<=e_tgt<=n. t0 s_src=0, later source range equals previous target range; finite coords and correct t entries. Store per-t ranges, local pair indices. No need storing interim coords/features.
- empty ranges: store empty pairs, next_t+=1, stay pair-ready immediately. Nonempty start_pair advances to primary hook state. Copy forward using logits.detach().cpu().numpy(); validate exact float32,batch1,(ns,nt),finite BEFORE .copy(), no casting or array-first tensor check. reverse same validation then existing helper, clear forward; secondary and mixed ignore all tensor values/features and only check order. No feature IO.
- end_video requires all transitions and no pending state. final coords original voxel array finite,(n,4), final n equals last range end (except frames1 allow its nodes), times consistent, copy final coordinates. Compare subsequent pre_graph coords by np.array_equal, NOT identity.
- pre_graph node_ids iterable is a positional list: e.g. node_ids=[101,7,55,900] means graph_to_detector={101:0,7:1,55:2,900:3}. Accept int/np.integer excluding bool, normalize to int. Unique nonnegative len==coords count. Validate graph.node_attrs(attr_keys=["node_id","t","z","y","x"]).iter_rows(named=True) has exactly those node IDs with equal coordinates (no lossy casting of coords). Do NOT index node_ids with graph ID. Store entire pregraph bijection.
- selected_graph may contain SUBSET of nodes. Validate subset and coordinates unchanged, save selected ID set separately from complete graph_to_detector mapping. Complete this video. No graph mutation.
- frames_for(dataset,raw_nodes): raw dict node_id->{node_id,t,z,y,x}. Validate keys==attrs node_id and coords exact against record graph_to_detector[node_id], membership in selected ID set. Subsets of selected/raw nodes are valid. No inverse for this lookup. No conversion of fractional coordinates to int that hides mismatch. Determine active transitions from raw nodes t and t+1; for each active t call map_consensus_to_raw(stored_local_pairs[t], list(range(s0,s1)),list(range(t0,t1)),record mapping,list(raw_nodes)). Helper itself discards solver-removed nodes; NEVER require all detector nodes to survive. Return exact dict containing active keys including empty pair lists. Don't recompute argmax on subset. Unknown dataset/incomplete/mismatched raw fail. No IO/network/train/GT/logit saving.

Tests must use FAKE tensor detach/cpu/numpy, FAKE graph .node_attrs().iter_rows(named=True), real numpy and pytest. Each successful simple example declares frames=2 and contains2 source+2 target nodes; node_ids LIST with non-contiguous IDs. End_video original coords must be used at pre_graph (not observer private state). Verify raw selected subset retains only one chosen pair; expected output sorted graph IDs. Nonsquare use exactly3 source+5target coordinate rows, absolute target offset=3 not5. Empty example frames3 with times[0,0,2,2]: pair0 ranges(0,2,2,2); pair1 (2,2,2,4), no tensor hooks, then end/pre/selected and {} active output. Multiple videos with DIFFERENT graph IDs and lookup of first after second. Parametrized invalid dtype/nonfinite/shape; input immutability; missing reverse/duplicate stage; raw attrs mismatch. Unknown and failures use fresh observer where needed. No tests expecting valid zero logits to throw. Include helper-equivalence test. Assert error at ACTUAL offending call. Do not misrepresent tests as executed.

ACTUAL src/biohub/consensus_edges.py then src/biohub/association_instrumentation.py:
"""Reciprocal-consensus edge helper for Biohub cell tracking."""

from __future__ import annotations

import numpy as np

_MAX_NS = 2048
_MAX_NT = 2048
_MAX_PACKET = 1_000_000


def _validate(matrix: np.ndarray, name: str) -> tuple[int, int]:
    if type(matrix) is not np.ndarray:
        raise ValueError(f"{name} must be an exact np.ndarray")
    if matrix.dtype != np.float32:
        raise ValueError(f"{name} must have dtype float32")
    if matrix.ndim != 2:
        raise ValueError(f"{name} must be 2-dimensional")
    if not np.isfinite(matrix).all():
        raise ValueError(f"{name} must be finite")
    ns, nt = matrix.shape
    if ns > _MAX_NS or nt > _MAX_NT:
        raise ValueError(f"{name} exceeds axis cap {_MAX_NS}/{_MAX_NT}")
    if ns * nt > _MAX_PACKET:
        raise ValueError(f"{name} exceeds packet size {_MAX_PACKET}")
    return ns, nt


def _unique_max_along_axis(logits: np.ndarray, axis: int) -> np.ndarray:
    """Boolean mask that is True only where logits has a unique maximum."""
    best = logits.max(axis=axis, keepdims=True)
    hits = logits == best
    counts = hits.sum(axis=axis, keepdims=True)
    return hits & (counts == 1)


def reciprocal_consensus_pairs(
    primary_forward: np.ndarray,
    primary_reverse: np.ndarray,
    secondary_forward: np.ndarray,
) -> list[tuple[int, int]]:
    """Return (source, target) pairs agreed by all three detectors.

    A pair (i, j) is kept when i is the unique argmax of both forward matrices
    in column j and j is the unique argmax of the reverse matrix in row i.
    Logits are compared within a model/direction only. Ties are excluded.
    """
    shapes = (
        _validate(primary_forward, "primary_forward"),
        _validate(primary_reverse, "primary_reverse"),
        _validate(secondary_forward, "secondary_forward"),
    )
    ns, nt = shapes[0]
    if any(shape != shapes[0] for shape in shapes[1:]):
        raise ValueError("all matrices must share identical (ns, nt) shapes")
    if ns == 0 or nt == 0:
        return []
    src_ok = _unique_max_along_axis(primary_forward, axis=0) & _unique_max_along_axis(secondary_forward, axis=0)
    tgt_ok = _unique_max_along_axis(primary_reverse, axis=1)
    mask = src_ok & tgt_ok
    rows, cols = np.nonzero(mask)
    order = np.lexsort((cols, rows))
    return [(int(i), int(j)) for i, j in zip(rows[order], cols[order], strict=True)]


def positive_reciprocal_consensus_pairs(
    primary_forward: np.ndarray,
    primary_reverse: np.ndarray,
    secondary_forward: np.ndarray,
) -> list[tuple[int, int]]:
    """Return reciprocal pairs whose three selected logits are strictly positive."""
    pairs = reciprocal_consensus_pairs(
        primary_forward, primary_reverse, secondary_forward
    )
    return [
        (i, j)
        for i, j in pairs
        if primary_forward[i, j] > 0
        and primary_reverse[i, j] > 0
        and secondary_forward[i, j] > 0
    ]


def primary_reciprocal_consensus_pairs(
    primary_forward: np.ndarray,
    primary_reverse: np.ndarray,
) -> list[tuple[int, int]]:
    """Return strict reciprocal unique-argmax pairs from the primary model only."""
    forward_shape = _validate(primary_forward, "primary_forward")
    reverse_shape = _validate(primary_reverse, "primary_reverse")
    if forward_shape != reverse_shape:
        raise ValueError("primary matrices must share identical shapes")
    ns, nt = forward_shape
    if ns == 0 or nt == 0:
        return []
    src_ok = _unique_max_along_axis(primary_forward, axis=0)
    tgt_ok = _unique_max_along_axis(primary_reverse, axis=1)
    rows, cols = np.nonzero(src_ok & tgt_ok)
    order = np.lexsort((cols, rows))
    return [(int(i), int(j)) for i, j in zip(rows[order], cols[order], strict=True)]


def map_consensus_to_raw(pairs, source_detector_indices, target_detector_indices, graph_to_detector, raw_node_ids):
    lists = (pairs, source_detector_indices, target_detector_indices, raw_node_ids)
    if any(type(x) is not list for x in lists):
        raise ValueError("list inputs must be exact lists")
    if type(graph_to_detector) is not dict:
        raise ValueError("graph_to_detector must be an exact dict")

    def is_int(v):
        return type(v) is int and v >= 0

    for g, d in graph_to_detector.items():
        if not (is_int(g) and is_int(d)):
            raise ValueError("mapping keys/values must be nonnegative ints")
    graphs = list(graph_to_detector)
    dets = list(graph_to_detector.values())
    if len(set(graphs)) != len(graphs) or len(set(dets)) != len(dets):
        raise ValueError("mapping must be one-to-one")

    for name, arr in (("source", source_detector_indices), ("target", target_detector_indices), ("raw", raw_node_ids)):
        if any(not is_int(v) for v in arr):
            raise ValueError(f"{name} entries must be nonnegative ints")
        if len(set(arr)) != len(arr):
            raise ValueError(f"{name} entries must be unique")

    if set(source_detector_indices) & set(target_detector_indices):
        raise ValueError("source/target detector sets must be disjoint")
    mapped = set(dets)
    for v in source_detector_indices + target_detector_indices:
        if v not in mapped:
            raise ValueError("detector index missing from mapping values")
    keyset = set(graphs)
    for v in raw_node_ids:
        if v not in keyset:
            raise ValueError("raw id missing from mapping keys")

    ns, nt = len(source_detector_indices), len(target_detector_indices)
    for p in pairs:
        if type(p) is not tuple or len(p) != 2 or not all(is_int(x) for x in p):
            raise ValueError("pairs must be tuples of two nonnegative ints")
    if pairs != sorted(pairs):
        raise ValueError("pairs must be sorted")
    if len(set(pairs)) != len(pairs):
        raise ValueError("pairs must be unique")
    for i, j in pairs:
        if not (0 <= i < ns and 0 <= j < nt):
            raise ValueError("pair indices out of range")
    if len({i for i, _ in pairs}) != len(pairs):
        raise ValueError("repeated source row")
    if len({j for _, j in pairs}) != len(pairs):
        raise ValueError("repeated target column")

    inverse = {d: g for g, d in graph_to_detector.items()}
    rawset = set(raw_node_ids)
    out = []
    for i, j in pairs:
        sg = inverse[source_detector_indices[i]]
        tg = inverse[target_detector_indices[j]]
        if sg in rawset and tg in rawset:
            out.append((sg, tg))
    return sorted(out)
"""Static-only, reversible observer insertion into the pinned E23 reconstruction."""

import ast
import hashlib

SOURCE_SHA256 = "8e7ac19e8b436d6777576b7ea2269464c4ed8842990b45448d40bf178f8f62de"

# Anchors are never replaced. Each addition is removable byte-for-byte.
INSERTIONS = (
    ("    edges: list[tuple[int, int, float, float]],\n", "    association_observer=None,\n"),
    ("    secondary_low_margin_max: float = 0.2,\n", "    association_observer=None,\n"),
    ("    evaluate: bool = False,\n", "    association_observer=None,\n"),
    ("    pool_k = pool_kernel_from_um(cfg.pool_kernel_um, voxel_size)\n",
     "    if association_observer is not None:\n"
     "        association_observer.start_video(\n"
     "            ds_path.stem, T, W, downsample, ds.scale, cfg.edge_activation,\n"
     "            threshold=cfg.threshold, max_parents=cfg.max_parents_per_node,\n"
     "            max_children=cfg.max_children_per_node)\n"),
    ("            s_tgt, e_tgt = coord_offset[t_tgt]\n",
     "            if association_observer is not None:\n"
     "                association_observer.start_pair(t_src, s_src, e_src, s_tgt, e_tgt, coords_so_far)\n"),
    ("            )  # (1, n_src, n_tgt)\n",
     "            if association_observer is not None:\n"
     "                association_observer.primary(edge_logits_pair, unet_feat_src, unet_feat_tgt)\n"),
    ("                reverse_logits_pair = reverse_logits_native.transpose(1, 2)\n",
     "                if association_observer is not None:\n"
     "                    association_observer.reverse(reverse_logits_pair)\n"),
    ("                    p_mask_src, p_mask_tgt,\n                )\n",
     "                if association_observer is not None:\n"
     "                    association_observer.secondary(\n"
     "                        secondary_logits_pair, secondary_feat_src, secondary_feat_tgt)\n"),
    ("                probs = torch.sigmoid(raw).cpu().numpy()\n",
     "            if association_observer is not None:\n"
     "                association_observer.mixed(raw, probs)\n"),
    ("    return coords, all_edges\n",
     "    if association_observer is not None:\n"
     "        association_observer.end_video(coords, all_edges)\n"),
    ("    return graph\n",
     "    if association_observer is not None:\n"
     "        association_observer.pre_graph(coords, edges, node_ids, graph)\n"),
    ("                secondary_low_margin_max=secondary_low_margin_max,\n",
     "                association_observer=association_observer,\n"),
    ("        graph = build_graph(coords, edges)\n",
     ""),
    ("        save_graph(graph, output_dir / f\"{name}.geff\")\n",
     "        if association_observer is not None:\n"
     "            association_observer.selected_graph(graph)\n"),
)


def instrument_source(source: str) -> tuple[str, dict]:
    """Return text and a receipt. Never imports or executes the supplied source.

    The build_graph call needs a keyword, so insert it before the closing paren
    instead of replacing the call. All original executable AST nodes survive.
    """
    digest = hashlib.sha256(source.encode()).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("E23 reconstructed source SHA mismatch")
    patched = source
    additions = []
    for index, (anchor, body) in enumerate(INSERTIONS):
        if patched.count(anchor) != 1:
            raise ValueError(f"observer anchor {index} is not unique")
        if not body:  # build_graph keyword insertion, not a replacement function
            original = "build_graph(coords, edges)"
            addition = ", association_observer=association_observer"
            patched = patched.replace(original, original[:-1] + addition + ")", 1)
            additions.append((original[:-1] + addition + ")", original))
            continue
        # End-of-function and post-solver hooks must precede return/save.
        before = anchor.lstrip().startswith(("return ", "save_graph("))
        replacement = body + anchor if before else anchor + body
        patched = patched.replace(anchor, replacement, 1)
        additions.append((replacement, anchor))
    restored = patched
    for inserted, original in reversed(additions):
        if restored.count(inserted) != 1:
            raise ValueError("observer removal is ambiguous")
        restored = restored.replace(inserted, original, 1)
    if restored != source or ast.dump(ast.parse(restored)) != ast.dump(ast.parse(source)):
        raise ValueError("original E23 program changed")
    ast.parse(patched)
    receipt = {"status": "STATIC_OBSERVER_INSERTION_ONLY", "original_sha256": digest,
               "instrumented_sha256": hashlib.sha256(patched.encode()).hexdigest(),
               "restored_bytes_equal": True, "restored_ast_equal": True,
               "insertions": len(additions), "source_executed": False,
               "inference_parity_verified": False, "submission_authorized": False}
    return patched, receipt


