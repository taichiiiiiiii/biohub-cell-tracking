"""Frozen association gates; Qwen draft corrected for four whole videos.

The exact 4^4 bootstrap describes uncertainty of loss-margin excess only.
It is a small-n retrospective diagnostic, not Private/generalization evidence.
"""
import itertools
import math
import re


def _loss(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Loss must be finite and nonnegative")
    return float(value)


def _videos(report):
    groups = report["by_video"]
    if (len(groups) != 4 or any(re.fullmatch(r"(?:44b6|6bba)_[a-zA-Z0-9]+", stem) is None for stem in groups)
            or any(sum(stem.startswith(lineage + "_") for stem in groups) != 2 for lineage in ("44b6", "6bba"))):
        raise ValueError("Exactly two videos from each lineage are required")
    return {stem: _loss(group["losses"]["total_loss"]["value"]) for stem, group in groups.items()}


def _bound(field, direction, baseline, limit):
    return {"field": field, "direction": direction, "baseline": baseline,
            "limit": limit, "observed_source": "best_epoch"}


def acceptance_spec(baseline, path="provenance/per-video.json"):
    pooled = _loss(baseline["losses"]["total_loss"]["value"])
    if pooled == 0:
        raise ValueError("Pooled baseline zero: relative primary improvement undefined")
    videos = _videos(baseline)
    if set(baseline["by_lineage"]) != {"44b6", "6bba"}:
        raise ValueError("Baseline lineage coverage mismatch")
    noninferiority, lineages = {}, {}
    for lineage, group in baseline["by_lineage"].items():
        for metric, limit in (("precision", 0.005), ("recall", 0.005), ("accuracy", 0.002)):
            value = _loss(group["task_metrics"][metric])
            if value > 1:
                raise ValueError("Baseline task metric exceeds one")
            noninferiority[f"{lineage}_{metric}"] = _bound(f"task_metrics.{lineage}.{metric}", "max", value, limit)
        loss = _loss(group["losses"]["total_loss"]["value"])
        lineages[lineage] = _bound(f"val_by_lineage.{lineage}.loss", "min", loss, loss * 0.005)
    for stem, loss in videos.items():
        noninferiority[f"video_{stem}"] = _bound(f"task_metrics.video_losses.{stem}", "min", loss, loss * 0.02)
    noninferiority["improved_videos"] = _bound("task_metrics.improved_videos", "max", 3, 0)
    return {
        "zero_best_absolute_degradation": 0.0,
        "primary": {"field": "val.losses.total_loss.value", "direction": "min", "baseline": pooled,
                    "margin": pooled * 0.01, "observed_source": "history_best"},
        "noninferiority": noninferiority, "lineage_noninferiority": lineages,
        "per_video": {"path": path, "sha256": None, "direction": "min", "baseline": 0.0, "limit": 0.0,
                      "observed_source": "artifact_values", "uncertainty_field": "uncertainty.upper",
                      "uncertainty_limit": 0.0, "min_qualifying_videos": 4},
    }


def video_metrics(report, spec):
    videos = _videos(report)
    entries = {key.removeprefix("video_"): value for key, value in spec["noninferiority"].items()
               if key.startswith("video_")}
    if set(entries) != set(videos):
        raise ValueError("Candidate video set differs from fixed baseline")
    baselines = {}
    for stem, entry in entries.items():
        baseline = _loss(entry["baseline"])
        if entry != _bound(f"task_metrics.video_losses.{stem}", "min", baseline, baseline * 0.02):
            raise ValueError("Video threshold contract changed")
        baselines[stem] = baseline
    return {"video_losses": videos,
            "improved_videos": sum(videos[stem] < baselines[stem] for stem in videos)}


def paired_readout(baseline, candidate):
    base = _videos(baseline)
    observed = _videos(candidate)
    if set(base) != set(observed):
        raise ValueError("Paired video sets differ")
    excess = {stem: observed[stem] - (base[stem] + base[stem] * 0.02) for stem in sorted(base)}
    if any(not math.isfinite(value) for value in excess.values()):
        raise ValueError("Nonfinite paired margin excess")
    means = sorted(math.fsum(draw) / 4 for draw in itertools.product(excess.values(), repeat=4))
    index = 0.95 * (len(means) - 1)
    lower = math.floor(index)
    upper = means[lower] + (index - lower) * (means[lower + 1] - means[lower])
    return {"values": excess, "uncertainty": {"upper": upper}}


def paired_readout_from_history(row, spec):
    """Derive the readout from the winning row and fixed literal video baselines."""
    baselines = {key.removeprefix("video_"): entry["baseline"]
                 for key, entry in spec["noninferiority"].items() if key.startswith("video_")}

    def report(values):
        return {"by_video": {stem: {"losses": {"total_loss": {"value": loss}}}
                             for stem, loss in values.items()}}

    candidate = report(row["task_metrics"]["video_losses"])
    measured = video_metrics(candidate, spec)  # Also verify literal bounds and count.
    if measured["improved_videos"] != row["task_metrics"]["improved_videos"]:
        raise ValueError("Improved video count differs from recorded losses")
    return paired_readout(report(baselines), candidate)
