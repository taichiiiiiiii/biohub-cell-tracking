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
