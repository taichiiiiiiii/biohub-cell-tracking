Issue16: Author ONLY a minimal new module src/biohub/primary_consensus_observer.py and tests/test_primary_consensus_observer.py as complete file contents, fenced and labelled. No tools, no filesystem access, no execution. All current source needed is inline below. Do not change scientific rules or existing helpers. Parent applies output. Subscription Flash, no fallback or agents.

Goal: streaming E31 primary-only consensus capture at the existing E23 observer hooks, with no dense-logit disk capture or train reference plan. Class PrimaryConsensusObserver() implementing exact hook signatures in instrument_source below: start_video(name,frames,window_size,downsample,scale,activation,*,threshold=.48,max_parents=None,max_children=None); start_pair(t,s_src,e_src,s_tgt,e_tgt,coords); primary(logits,source,target); reverse(transposed_logits); secondary(logits,source,target); mixed(raw,probabilities); end_video(coords,edges); pre_graph(coords,edges,node_ids,graph); selected_graph(graph). features/raw/secondary are ignored intentionally and must not be converted/copied. primary/reverse tensors implement detach().cpu().numpy() of shape(1,ns,nt), exact float32 finite; use existing primary_reciprocal_consensus_pairs, no reimplementation or casting.

Contract:
- use explicit ValueError checks (not asserts), strict stage lifecycle incl duplicate video IDs, duplicate/out-of-order transitions, incomplete reverse, empty transitions accepted then return to pair stage without calling logits hooks. window_size=2; downsample=(1,4,4), scale=(1.625,.40625,.40625), activation=softmax, threshold=.48, max_parents/max_children None; no hardcoded dataset IDs, total videos or frame count (frames positive integer).
- start_pair offset source/target ranges are absolute detector indices in sequential coords array (t,z,y,x), downsampled grid. All transitions t=0..frames-2 expected; validate contiguous ranges across transitions, coords finite, times t/t+1, no negative/reversed/out of range offsets. Copy no input except primary 2D tensor and per-video sparse pair indices; can preserve small frame counts/offsets and final coords for mapping. No feature matrices. Fail closed after any exception rather than returning an empty fallback.
- reverse computes same existing primary_reciprocal_consensus_pairs on all detector rows BEFORE solver filtering, adds absolute detector index pairs for each t; releases forward matrix. secondary/mixed validate stage but ignore their arrays; complete nonempty pair only on mixed.
- end_video receives final coords in ORIGINAL voxel coords, not downsampled. Check lengths/times consistent with ranges, finite, copy it and change stage. No alteration of graph or arrays, no inference/GT/IO imports; numpy only plus helper imports.
- pre_graph receives node_ids mapping positional detector index to graph node ID, which are arbitrary nonnegative unique integers, not array positions. Validate mapping uniqueness/count and graph.node_attrs(attr_keys=["node_id","t","z","y","x"]) coordinate equivalence, supporting .iter_rows(named=True) (polars-style); no dependency on polars directly. Record dict graphID->detector index.
- selected_graph validates selected node IDs subset and coords identical to pre_graph. No mutations. Ends lifecycle, makes completed dataset available.
- frames_for(dataset,raw_nodes) matches run_postproc_core consensus_loader signature. raw_nodes is dict[int,dict] with node_id,t,z,y,x; check exact identities+coords against final detector mapping. Use map_consensus_to_raw (below) on stored per-t local pairs and index ranges; return dict only for times with both raw t and t+1, even if empty pair list. Frames with no raw adjacent nodes omitted (existing loader behavior). Reject unknown/incomplete dataset, unknown or mismatched node IDs. Read-only repeatable loader.
- terminal storage per video sparse pairs + coords + mapping only; no dense features/logits and no dependence on pre-known train-only counts.
- tests use tiny fake tensor with detach/cpu/numpy and fake graph table iter_rows, NumPy. No torch/polars requirement. Cover orientation/transpose with non-square matrices; arbitrary permuted graph IDs and selected subset; ties excluded; logits not mutated; malformed shapes/dtype/nonfinite; duplicate stage/missing reverse; empty source/target transitions; multiple videos; raw coord mismatch; incomplete/unknown dataset; no feature conversion. Compare expected helper+map results directly where useful.
Keep code small, no generic framework. Return complete code without claims of tests run. This is a bounded first integration piece, not full notebook; do not invent notebook/runner APIs.

CURRENT SOURCE:
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

