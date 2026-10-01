"""Instrumented association epochs; persistence and candidate gates are separate.

Qwen-authored forward/epoch design, integrated against the official batch and
sparse-label contracts. This module alone cannot authorize a training candidate.
"""

import math
import re

import torch


def _validate_weights(det_loss_weight, det_neg_weight, pool_kernel_um):
    for value in (det_loss_weight, det_neg_weight, pool_kernel_um):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("Loss weights and pool size must be finite nonnegative numbers")
    if pool_kernel_um == 0:
        raise ValueError("Pool size must be positive")


def _validate_optimizer(optimizer, model):
    expected = {id(p) for p in model.parameters() if p.requires_grad}
    actual = [id(p) for group in optimizer.param_groups for p in group["params"]]
    if not expected or len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Optimizer must contain exactly all trainable parameters without duplicates")


def _validate_batch(batch):
    required = {"imgs", "coords", "masks", "targets", "image_shape", "voxel_size", "downsample"}
    if not isinstance(batch, dict) or not required.issubset(batch):
        raise ValueError("Missing batch fields")
    if not all(isinstance(batch[key], torch.Tensor) for key in required):
        raise ValueError("Batch fields must be tensors")
    imgs, coords = batch["imgs"], batch["coords"]
    if imgs.ndim != 5 or imgs.shape[:2] != (1, 2) or any(size <= 0 for size in imgs.shape[2:]):
        raise ValueError("Only batch1/window2 3D images are supported")
    if coords.ndim != 4 or coords.shape[:2] != (1, 2) or coords.shape[-1] != 3:
        raise ValueError("Invalid coordinate shape")
    n = coords.shape[2]
    if batch["masks"].shape != (1, 2, n) or batch["masks"].dtype != torch.bool:
        raise ValueError("Invalid mask shape or dtype")
    if batch["targets"].shape != (1, 1, n, n):
        raise ValueError("Invalid target shape")
    for key, size in (("image_shape", 4), ("voxel_size", 3), ("downsample", 3)):
        if batch[key].shape != (1, size):
            raise ValueError(f"Invalid {key} shape")
        if not bool(torch.isfinite(batch[key]).all()) or not bool((batch[key] > 0).all()):
            raise ValueError(f"Invalid {key} values")
    for key in ("imgs", "coords", "targets"):
        if not bool(torch.isfinite(batch[key]).all()):
            raise ValueError(f"Nonfinite {key}")
    if not bool(((batch["targets"] == 0) | (batch["targets"] == 1)).all()):
        raise ValueError("Targets must be binary")


def _run_forward(api, model, batch, device, det_neg_weight, pool_kernel_um):
    imgs = batch["imgs"].to(device, dtype=torch.float32)
    coords, masks, targets = (batch[key].to(device) for key in ("coords", "masks", "targets"))
    image_shape = tuple(batch["image_shape"][0].tolist())
    voxel_size = tuple(batch["voxel_size"][0].tolist())
    ds_scale = batch["downsample"][0].to(device)
    unet_out, det_logits = model.encode(imgs)
    det_loss = sum(api.compute_detection_loss(det_logits[i], coords[:, i], masks[:, i], det_neg_weight)
                   for i in range(2)) / 2
    frame_det, node_matched, node_gt = [], 0, 0
    for i in range(2):
        det_c, det_p, det_m, matches = api.detect_and_match(
            det_logits[i], coords[:, i], masks[:, i], image_shape,
            voxel_size=voxel_size, pool_kernel_um=pool_kernel_um, frame_index=i, window_size=2,
        )
        features = model._index_features(unet_out[:, i], det_c, det_m)
        frame_det.append((det_c, det_p, det_m, matches, features))
        node_gt += int(masks[0, i].sum().item())
        node_matched += int((matches[0] >= 0).sum().item())
    source, target = frame_det
    pair_target = api.build_matched_edge_targets(source[3], target[3], targets[:, 0],
                                                source[0].shape[1], target[0].shape[1])
    edge_logits = model.predict_edges(
        source[4], target[4], source[0] * ds_scale, target[0] * ds_scale,
        source[1], target[1], source[2], target[2],
    )
    ns, nt = int(source[2][0].sum().item()), int(target[2][0].sum().item())
    counts = _count_metrics(edge_logits[0, :ns, :nt].detach(), pair_target[0, :ns, :nt])
    edge_loss = api.compute_batch_loss(edge_logits, pair_target, source[2], target[2])
    return edge_loss, det_loss, counts, node_matched, node_gt


def _count_metrics(logits, target):
    if logits.ndim != 2 or target.ndim != 2 or logits.shape != target.shape:
        raise ValueError("Metric logits and targets must be equally shaped 2D tensors")
    if not bool(torch.isfinite(logits).all()):
        raise ValueError("Nonfinite edge logits")
    if not bool(((target == 0) | (target == 1)).all()):
        raise ValueError("Metric targets must be binary")
    # Annotation mask only: predictions must not activate unannotated negatives.
    mask = (target.sum(dim=1) > 0).unsqueeze(1) | (target.sum(dim=0) > 0).unsqueeze(0)
    predicted, positive = torch.softmax(logits, dim=0) > 0.5, target == 1
    return {"tp": int((predicted & positive & mask).sum().item()),
            "fp": int((predicted & ~positive & mask).sum().item()),
            "fn": int((~predicted & positive & mask).sum().item()),
            "tn": int((~predicted & ~positive & mask).sum().item())}


def _aggregate(records, det_loss_weight=1.0):
    if not records:
        raise ValueError("Empty epoch")
    losses = {}
    for key in ("edge_loss", "det_loss"):
        numerator = math.fsum(record[key] for record in records)
        if not math.isfinite(numerator) or numerator < 0:
            raise ValueError("Invalid accumulated loss")
        losses[key] = {"value": numerator / len(records), "numerator": numerator,
                       "denominator": len(records), "reduction": "sum_over_windows"}
    # The audit total is reconstructed from component sums in host precision.
    # Preserve the separately rounded actual backward objective as evidence,
    # instead of loosening the verifier's algebraic consistency tolerance.
    numerator = losses["edge_loss"]["numerator"] + det_loss_weight * losses["det_loss"]["numerator"]
    if not math.isfinite(numerator) or numerator < 0:
        raise ValueError("Invalid total loss aggregation")
    losses["total_loss"] = {"value": numerator / len(records), "numerator": numerator,
                            "denominator": len(records), "reduction": "sum_over_windows"}
    objective_sum = math.fsum(record["total_loss"] for record in records)
    if not math.isfinite(objective_sum) or objective_sum < 0:
        raise ValueError("Invalid backward objective aggregation")
    objective = {"value": objective_sum / len(records), "numerator": objective_sum,
                 "denominator": len(records), "reduction": "sum_over_windows"}
    counts = {key: sum(record["counts"][key] for record in records) for key in ("tp", "fp", "fn", "tn")}
    counts.update({key: sum(record[key] for record in records) for key in ("node_matched", "node_gt")})
    tp, fp, fn, tn = (counts[key] for key in ("tp", "fp", "fn", "tn"))
    metrics = {"precision": tp / (tp + fp) if tp + fp else None,
               "recall": tp / (tp + fn) if tp + fn else None,
               "accuracy": (tp + tn) / (tp + fp + fn + tn) if tp + fp + fn + tn else None,
               "node_recall": counts["node_matched"] / counts["node_gt"] if counts["node_gt"] else None}
    return {"losses": losses, "objective_total_loss": objective, "examples": len(records), "batches": len(records),
            "counts": counts, "task_metrics": metrics}


def run_epoch(api, model, batches, device, *, optimizer=None, det_loss_weight=1.0,
              det_neg_weight=0.01, pool_kernel_um=5.0, detector_guard=None):
    """Run one complete batch1/window2 epoch, retaining reproducible aggregates.

    batches yields (video_id, example_id, official_batch). No graph/GT files are
    opened here. A failed epoch must not be published by the calling run writer.
    """
    _validate_weights(det_loss_weight, det_neg_weight, pool_kernel_um)
    training = optimizer is not None
    if training:
        _validate_optimizer(optimizer, model)
    if detector_guard is not None:
        detector_guard()
    model.train(training)
    records, grad_norms, example_ids, seen = [], [], [], set()
    with torch.enable_grad() if training else torch.no_grad():
        for video_id, example_id, batch in batches:
            if not isinstance(video_id, str) or re.fullmatch(r"(44b6|6bba)_[A-Za-z0-9]+", video_id) is None:
                raise ValueError("Invalid video ID or lineage")
            if not isinstance(example_id, str) or not example_id or example_id in seen:
                raise ValueError("Empty or duplicate example ID")
            _validate_batch(batch)
            seen.add(example_id)
            example_ids.append(example_id)
            edge, det, counts, node_matched, node_gt = _run_forward(
                api, model, batch, device, det_neg_weight, pool_kernel_um,
            )
            total = edge + det_loss_weight * det
            for loss in (edge, det, total):
                if loss.numel() != 1 or not bool(torch.isfinite(loss)) or float(loss.detach()) < 0:
                    raise ValueError("Nonfinite or negative loss before backward")
            if training:
                optimizer.zero_grad()
                total.backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
                grad_norms.append(float(norm.item()))
                optimizer.step()
                if detector_guard is not None:
                    detector_guard()
            records.append({"video_id": video_id, "example_id": example_id,
                            "edge_loss": float(edge.item()), "det_loss": float(det.item()),
                            "total_loss": float(total.item()), "counts": counts,
                            "node_matched": node_matched, "node_gt": node_gt})
    report = _aggregate(records, det_loss_weight)
    by_video, by_lineage = {}, {}
    for record in records:
        by_video.setdefault(record["video_id"], []).append(record)
        by_lineage.setdefault(record["video_id"].split("_", 1)[0], []).append(record)
    report.update({
        "optimizer_steps": len(grad_norms), "example_ids": example_ids,
        "by_video": {key: _aggregate(items, det_loss_weight) for key, items in by_video.items()},
        "by_lineage": {key: _aggregate(items, det_loss_weight) for key, items in by_lineage.items()},
        "grad_norm_pre_clip": {"max": max(grad_norms), "mean": math.fsum(grad_norms) / len(grad_norms),
                               "last": grad_norms[-1], "checked_steps": len(grad_norms),
                               "clip_threshold": 1.0} if grad_norms else None,
    })
    return report
