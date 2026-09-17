"""Read-only graph and manifest checks, not proof that unread matrix files exist."""

import hashlib
import re

import numpy as np

from biohub.association_capture import COORDINATES, FEATURES, MATRICES, _require
from biohub.association_packet_readout import detector_lookup
from biohub.association_parity import array_signatures, semantic_graph_signature


def pair_manifest_summary(manifest, datasets):
    _require(
        manifest["schema_version"] == "biohub.e23.association_capture.v1"
        and manifest["status"] == "PAIR_CAPTURE_COMPLETE"
        and manifest["capture_only"] is True
        and manifest["submission_authorized"] is False,
        "invalid capture manifest",
    )
    expected_counts = {n: r["frame_counts"] for n, r in datasets.items()}
    _require(bool(datasets) and manifest["frame_counts"] == expected_counts, "frame-count plan mismatch")
    for counts in expected_counts.values():
        _require(
            len(counts) == 100 and all(type(n) is int and 0 <= n <= 2048 for n in counts),
            "invalid reference detector count",
        )
    expected_pairs = {(n, t) for n in datasets for t in range(99)}
    seen, dense, size, empty_count = set(), 0, 0, 0
    for r in manifest["records"]:
        name, t = r["dataset"], r["t_source"]
        _require(type(t) is int and (name, t) in expected_pairs and (name, t) not in seen, "duplicate/unplanned pair")
        seen.add((name, t))
        ns, nt = expected_counts[name][t : t + 2]
        empty = not ns or not nt
        _require(
            all(type(r[k]) is int for k in ("n_source", "n_target", "dense_pairs", "t_target", "window_size"))
            and (r["n_source"], r["n_target"], r["dense_pairs"]) == (ns, nt, ns * nt)
            and ns * nt <= 1_000_000,
            "invalid pair size",
        )
        _require(
            r["schema_version"] == "biohub.e23.association_pair.v1"
            and r["t_target"] == t + 1
            and r["window_size"] == 2
            and r["matrix_axes"] == ["source", "target"]
            and r["probability_normalisation_axis"] == "source"
            and r["downsample_zyx"] == [1, 4, 4]
            and r["scale_zyx_um"] == [1.625, 0.40625, 0.40625]
            and r["submission_authorized"] is False,
            "invalid pair axes/units/schema",
        )
        _require(r["status"] == ("SKIPPED_EMPTY" if empty else "OBSERVED"), "invalid empty-pair status")
        _require(
            r["path"] == f"{name}/pair_{t:04d}.npz"
            and type(r["bytes"]) is int
            and r["bytes"] > 0
            and re.fullmatch(r"[0-9a-f]{64}", r["sha256"]) is not None,
            "invalid packet file binding",
        )
        keys = COORDINATES if empty else COORDINATES + FEATURES + MATRICES
        _require(set(r["arrays"]) == set(keys), "packet declared array keys mismatch")
        for k, a in r["arrays"].items():
            n = ns if "source" in k else nt
            shape = (
                [ns, nt]
                if k in MATRICES
                else [n]
                if k.endswith("indices")
                else [n, 4]
                if k.endswith("grid")
                else [n, 32]
            )
            dtype = "<i8" if k.endswith("indices") else "<i2" if k.endswith("grid") else "<f4"
            _require(
                a["shape"] == shape and a["dtype"] == dtype and re.fullmatch(r"[0-9a-f]{64}", a["sha256"]) is not None,
                "invalid declared array contract",
            )
        dense += ns * nt
        size += r["bytes"]
        empty_count += bool(empty)
    _require(seen == expected_pairs, "incomplete manifest coverage")
    _require(dense == manifest["dense_pairs"] and size == manifest["packet_bytes"], "pair manifest totals mismatch")
    _require(
        type(manifest["writer_seconds"]) in (int, float)
        and np.isfinite(manifest["writer_seconds"])
        and 0 <= manifest["writer_seconds"] <= 1200,
        "invalid writer time",
    )
    return {
        "packet_count": len(seen),
        "dense_pairs": dense,
        "packet_bytes": size,
        "empty_pairs": empty_count,
        "matrix_packets_read_locally": 0,
        "all_packet_files_verified_locally": False,
    }


def _canonical_graph(arrays):
    keys = {"node_node_id", "node_t", "node_z", "node_y", "node_x", "edge_edge_id", "edge_source_id", "edge_target_id"}
    _require(keys <= set(arrays), "missing graph column")
    n, e = len(arrays["node_node_id"]), len(arrays["edge_edge_id"])
    _require(e == 0 or {"edge_edge_prob", "edge_edge_dist"} <= set(arrays), "missing edge values")
    columns = {k: v for k, v in arrays.items() if k.startswith(("node_", "edge_"))}
    for k, a in columns.items():
        _require(
            a.ndim == 1 and len(a) == (n if k.startswith("node_") else e) and np.isfinite(a).all(),
            "invalid graph column shape/value",
        )
        if k.endswith("_id") or k == "node_t":
            _require(np.issubdtype(a.dtype, np.integer), "noninteger graph ID/time")
    _require(
        len(set(arrays["node_node_id"].tolist())) == n and len(set(arrays["edge_edge_id"].tolist())) == e,
        "duplicate graph ID",
    )
    orders = {
        "node": np.argsort(arrays["node_node_id"], kind="stable"),
        "edge": np.lexsort((arrays["edge_edge_id"], arrays["edge_target_id"], arrays["edge_source_id"])),
    }
    return {k: a[orders[k.split("_")[0]]] for k, a in columns.items()}


def _edge_values(arrays):
    pairs = list(zip(arrays["edge_source_id"].tolist(), arrays["edge_target_id"].tolist(), strict=True))
    _require(len(set(pairs)) == len(pairs), "duplicate candidate endpoints")
    if not pairs:
        return {}
    return dict(
        zip(pairs, zip(arrays["edge_edge_prob"].tolist(), arrays["edge_edge_dist"].tolist(), strict=True), strict=True)
    )


def audit_video(expected, returned, pre_common, post_common, pre_observer, post_observer):
    """Check five actual NPZ array dictionaries against a frozen E23 video reference."""
    _require(set(returned) == {"coords", "edges"}, "unexpected returned arrays")
    coords = returned["coords"]
    lookup = detector_lookup(pre_observer, coords)
    _require(hashlib.sha256(coords.tobytes()).hexdigest() == expected["coordinate_sha256"], "E23 detector drift")
    _require(
        [int(np.count_nonzero(coords[:, 0] == t)) for t in range(100)] == expected["frame_counts"],
        "E23 detector count drift",
    )
    pre, post = _canonical_graph(pre_common), _canonical_graph(post_common)
    for common, observed in ((pre, pre_observer), (post, post_observer)):
        _require(
            array_signatures(common) == array_signatures(_canonical_graph(observed)), "common/observer graph mismatch"
        )
    candidates = _edge_values(pre)
    returned_edges = returned["edges"]
    _require(
        returned_edges.ndim == 2
        and returned_edges.shape[1] == 4
        and returned_edges.dtype == np.dtype("float64")
        and np.isfinite(returned_edges).all(),
        "invalid returned candidate array",
    )
    indices = returned_edges[:, :2]
    _require(
        np.all((indices >= 0) & (indices < len(coords))) and np.array_equal(indices, indices.astype(np.int64)),
        "invalid returned edge detector index",
    )
    inverse = {v: k for k, v in lookup.items()}
    expected_edges = {(inverse[int(s)], inverse[int(t)]): (float(p), float(d)) for s, t, p, d in returned_edges}
    _require(
        len(expected_edges) == len(returned_edges) and expected_edges == candidates,
        "returned/pre candidate mapping mismatch",
    )
    _require(
        all(
            coords[lookup[t], 0] == coords[lookup[s], 0] + 1 and 0.48 < p <= 1 and d >= 0
            for (s, t), (p, d) in candidates.items()
        ),
        "invalid candidate time/probability/distance",
    )
    _require(semantic_graph_signature(post) == expected["raw_graph_signature"], "E23 selected graph drift")
    for node, position in zip(
        post["node_node_id"], np.column_stack([post[f"node_{k}"] for k in ("t", "z", "y", "x")]), strict=True
    ):
        _require(node in lookup and tuple(position) == tuple(coords[lookup[node]]), "ILP changed node identity/coords")
    selected = _edge_values(post)
    _require(all(candidates.get(pair) == value for pair, value in selected.items()), "ILP changed candidate edge")
    post_nodes = set(post["node_node_id"].tolist())
    _require(all(s in post_nodes and t in post_nodes for s, t in selected), "dangling selected edge")
    return {
        "detectors": len(coords),
        "candidate_edges": len(candidates),
        "selected_nodes": len(post_nodes),
        "selected_edges": len(selected),
        "actual_graphs_verified": True,
        "matrix_packets_read_locally": 0,
    }
