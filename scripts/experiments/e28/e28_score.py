"""E28 official-scoring adapter: verify one generated (unscored) child run."""

import json
from pathlib import Path

from scripts.experiments.e27 import e27_association_prior_screen as g
from scripts.experiments.e27.e27_prior_score_v2 import read_generation_receipts


def verify_generation(output: Path, arm: str, expected_sources: dict,
                      expected_appearance_plan: dict, check_budget) -> dict:
    """Verify one generated (unscored) E28 child run and its supervisor."""
    from biohub import e26_screen as e

    if not callable(check_budget):
        raise ValueError("check_budget must be callable")
    check_budget()
    if type(arm) is not str or arm not in ("e28_none", "e28_appearance"):
        raise ValueError(arm)
    output = Path(output)
    docs = read_generation_receipts(output)
    r, c, s = docs["result"], docs["control"], docs["supervisor"]

    child_status = ("E28_APPEARANCE_NONE_PARITY_PASS_NOT_CANDIDATE"
                    if arm == "e28_none" else "E28_APPEARANCE_COST_V1_GENERATED_UNSCORED")
    parent_status = ("E28_APPEARANCE_NONE_SUPERVISED_PASS_NOT_CANDIDATE"
                     if arm == "e28_none" else "E28_APPEARANCE_COST_V1_SUPERVISED_UNSCORED")
    for doc, want in ((r, child_status), (s, parent_status)):
        if doc.get("status") != want:
            raise ValueError(f"status {doc.get('status')} != {want}")

    if c.get("schema") != "E28_GENERATION_CONTROL_V1":
        raise ValueError("control schema mismatch")
    for doc in (c, r, s):
        if doc.get("candidate_id") != "E28_APPEARANCE_COST_V1":
            raise ValueError(
                f"candidate_id mismatch: {doc.get('candidate_id')} != E28_APPEARANCE_COST_V1")

    for doc in (c, r, s):
        if doc["arm"] != arm or doc["submission_allowed"] is not False:
            raise ValueError("arm/submission_allowed mismatch")
    if r.get("gt_read") is not False or s.get("gt_read") is not False:
        raise ValueError("gt_read must be false")
    for doc in (c, r):
        if doc["run_id"] != output.name:
            raise ValueError("run_id must equal output dir name")
    if c["output"] != str(output):
        raise ValueError("child output mismatch")
    if s["output"] != str(output) or s["audit_dir"] != str(output.with_name(output.name + "_supervisor")):
        raise ValueError("supervisor paths mismatch")
    if s["returncode"] != 0 or type(s["returncode"]) is not int or s["reap_error"] is not None \
            or s["killpg_signals"] != []:
        raise ValueError("supervisor termination unclean")

    if c["datasets"] != list(g.STEMS) or r["counts"]["datasets"] != list(g.STEMS):
        raise ValueError("datasets mismatch")
    if s["counts"] != r["counts"]:
        raise ValueError("supervisor/result counts differ")

    if c["source_bindings"] != expected_sources or r["source_bindings"] != expected_sources:
        raise ValueError("source_bindings mismatch")
    g._verify_source_closure(expected_sources)

    if type(expected_appearance_plan) is not dict:
        raise ValueError("expected_appearance_plan must be a dict")
    check_budget()
    plan = g.prepare_appearance_plan()
    if plan != expected_appearance_plan:
        raise ValueError("expected_appearance_plan differs from prepare_appearance_plan()")
    check_budget()
    if c["appearance_plan"] != expected_appearance_plan:
        raise ValueError("control appearance_plan mismatch")

    for doc in (c, r, s):
        if doc["association_priors"] is not None:
            raise ValueError("association_priors must be None")

    artifacts = r["artifact_bindings"]
    if type(artifacts) is not dict:
        raise ValueError("artifact_bindings not a dict")
    actual = {str(p.relative_to(output)) for p in output.rglob("*")
              if p.is_file() and p != output / "RESULT.json"}
    if actual != set(artifacts):
        raise ValueError("artifact set mismatch")
    for required in ("CONTROL.json", "submission.csv", "raw_statistics.json", "output_bounds.json"):
        if required not in artifacts:
            raise ValueError(f"missing artifact {required}")
    for rel, binding in artifacts.items():
        cand = Path(rel)
        if cand.is_absolute() or ".." in cand.parts:
            raise ValueError(f"unsafe artifact path {rel}")
        if not (output / rel).resolve().is_relative_to(output.resolve()):
            raise ValueError(f"artifact escapes output {rel}")
        check_budget()
        if g._binding_for_path(output / rel, label=rel) != binding:
            raise ValueError(f"artifact hash drift {rel}")

    receipt_path = output / "FEATURE_RECEIPTS.json"
    if arm == "e28_none":
        if receipt_path.exists():
            raise ValueError("e28_none must not write FEATURE_RECEIPTS.json")
        if r["feature_receipts_binding"] is not None or s["feature_receipts_binding"] is not None:
            raise ValueError("e28_none feature_receipts_binding must be None")
    else:
        if "FEATURE_RECEIPTS.json" not in artifacts:
            raise ValueError("missing artifact FEATURE_RECEIPTS.json")
        binding = g._binding_for_path(receipt_path, label="FEATURE_RECEIPTS.json")
        if r["feature_receipts_binding"] != binding:
            raise ValueError("result feature_receipts_binding mismatch")
        if s["feature_receipts_binding"] != binding:
            raise ValueError("supervisor feature_receipts_binding mismatch")
        check_budget()
        receipts = json.loads(receipt_path.read_text())
        if type(receipts) is not list:
            raise ValueError("FEATURE_RECEIPTS.json must be a JSON list")
        g.verify_appearance_receipts(expected_appearance_plan, receipts, check_budget)
        check_budget()

    csv_binding = g._binding_for_path(output / "submission.csv", label="csv")
    if r["csv_binding"] != csv_binding:
        raise ValueError("csv_binding mismatch")
    if arm == "e28_none":
        if csv_binding["bytes"] != g._REFERENCE_BYTES or csv_binding["sha256"] != g._REFERENCE_SHA256:
            raise ValueError("CSV must match reference bytes/sha256")

    rows = c["generation_input_binding"]["eval36"]["videos"]
    seen = [row["dataset"] for row in rows if row["dataset"] in g.STEMS]
    if sorted(seen) != sorted(g.STEMS):
        raise ValueError("selected datasets missing or duplicated")
    shapes = {row["dataset"]: tuple(row["metadata"]["shape_tzyx"]) for row in rows
              if row["dataset"] in g.STEMS}

    check_budget()
    report = e.validate_generated_csv(output / "submission.csv", datasets=g.STEMS, shapes=shapes)
    if report != r["counts"]:
        raise ValueError("csv report differs from result counts")
    check_budget()

    bounds = json.loads((output / "output_bounds.json").read_text())
    check_budget()
    e._validate_screen_bounds(bounds, output / "submission.csv", shapes)
    check_budget()

    raw = json.loads((output / "raw_statistics.json").read_text())
    check_budget()
    g.validate_known12_statistics(raw, arm="baseline", csv_report=report)
    check_budget()

    after = read_generation_receipts(output)
    if after != docs:
        raise ValueError("receipts changed during verification")
    for rel, binding in r["artifact_bindings"].items():
        check_budget()
        if g._binding_for_path(output / rel, label=rel) != binding:
            raise ValueError(f"artifact hash drift after validation {rel}")
    g._verify_source_closure(expected_sources)
    check_budget()

    return {**docs, "output": str(output), "csv_report": report,
            "shapes": {stem: list(shape) for stem, shape in shapes.items()}}


def score_eval12_core(checked_plan, candidate, output, check_budget):
    """Score eval12 baseline/candidate arms from verified inputs; no seals."""
    if not callable(check_budget):
        raise ValueError("check_budget must be callable")
    check_budget()
    from biohub import e26_screen as e
    plan = checked_plan["plan"]
    base = checked_plan["baseline"]
    if plan["candidate_id"] != "E28_APPEARANCE_COST_V1":
        raise ValueError(f"unexpected candidate_id: {plan['candidate_id']!r}")
    for key in ("config", "dependency_binding", "generation_input_binding",
                "metadata_bindings", "reader_bindings", "source_bindings",
                "appearance_plan"):
        if base["control"][key] != candidate["control"][key]:
            raise ValueError(f"CONTROL binding mismatch: {key}")
    checks = ((candidate["control"]["arm"], "e28_appearance"),
              (base["control"]["arm"], "e28_none"),
              (candidate["control"]["source_bindings"], plan["generation_sources"]),
              (base["control"]["source_bindings"], plan["generation_sources"]),
              (candidate["control"]["association_priors"], None),
              (base["control"]["association_priors"], None),
              (candidate["control"]["appearance_plan"], plan["appearance_plan"]),
              (base["control"]["appearance_plan"], plan["appearance_plan"]),
              (candidate["control"]["candidate_id"], "E28_APPEARANCE_COST_V1"),
              (base["control"]["candidate_id"], "E28_APPEARANCE_COST_V1"),
              (candidate["control"]["schema"], "E28_GENERATION_CONTROL_V1"),
              (base["control"]["schema"], "E28_GENERATION_CONTROL_V1"),
              (candidate["control"]["output"], plan["candidate_output"]),
              (base["control"]["output"], plan["baseline_output"]))
    for got, want in checks:
        if got != want:
            raise ValueError(f"gate mismatch: {got!r} != {want!r}")
    from biohub.evaluate import score_submission
    arms, counts, saved = {}, {}, {}
    for arm, record in (("baseline", checked_plan["baseline"]), ("candidate", candidate)):
        check_budget()
        preflight = e._check_stage_gt("eval12", checked_plan["gt_inputs"])
        check_budget()
        csv = Path(record["result"]["csv_binding"]["path"])
        summary, rows = score_submission(csv, g.ROOT / "data/train", max_distance=7.0, verbose=False)
        check_budget()
        counts[arm] = {row["dataset"]: row for row in record["csv_report"]["per_dataset"]}
        arms[arm] = e._score_arm_record(rows, "eval12", counts[arm])
        normalized = e._normalized_official_summary(summary, arms[arm]["rows"])
        if e._json_bytes(normalized) != e._json_bytes(arms[arm]["groups"]["eval12"]["summary"]):
            raise ValueError(f"official summary drift in arm {arm}")
        saved[arm] = e.write_json_exclusive(
            output / (arm + ".json"),
            {"arm": arm, "candidate_id": plan["candidate_id"], "official": arms[arm],
             "gt_preflight": preflight, "csv_binding": record["result"]["csv_binding"]})
        check_budget()
    paired = e._paired_score_record("eval12", arms, counts)
    old_gate = paired["gate"]
    if old_gate["candidate_id"] != e.CANDIDATE_ID:
        raise ValueError("paired gate candidate_id mismatch")
    paired["gate"] = {**old_gate, "candidate_id": plan["candidate_id"],
                      "rule_implementation_candidate_id": e.CANDIDATE_ID}
    return {"stage": "eval12", "candidate_id": plan["candidate_id"], "arms": arms,
            "paired": paired, "arm_artifacts": saved, "timing": check_budget(),
            "submission_authorized": False}


def verify_plan(plan_path: Path, expected_sha: str, *,
                before_generation: bool = False, check_budget=None) -> dict:
    from biohub import e26_screen as e

    if not callable(check_budget):
        raise RuntimeError("check_budget must be callable")
    check_budget()

    plan_path = Path(plan_path)
    if (not plan_path.is_absolute() or plan_path.resolve() != plan_path or
            plan_path.name != "PLAN.json" or
            plan_path.parent.parent != g.ROOT / "outputs" / "local"):
        raise RuntimeError(f"plan path must be canonical: {plan_path}")
    plan_ref = g._binding_for_path(plan_path, label="plan")
    if plan_ref["sha256"] != expected_sha:
        raise RuntimeError("plan sha256 mismatch")
    check_budget()
    plan = json.loads(plan_path.read_text())
    if type(plan) is not dict:
        raise RuntimeError("plan is not an object")
    if set(plan) != {"schema", "candidate_id", "datasets", "baseline_output", "candidate_output",
                     "baseline_bindings", "generation_sources", "appearance_plan",
                     "score_sources", "legacy_public", "legacy_private", "submission_allowed"}:
        raise RuntimeError("plan keys mismatch")
    if plan["schema"] != "E28_EVAL12_PLAN_V1" or plan["candidate_id"] != "E28_APPEARANCE_COST_V1":
        raise RuntimeError("plan schema/candidate mismatch")
    if plan["datasets"] != list(g.STEMS) or plan["submission_allowed"] is not False:
        raise RuntimeError("plan datasets/submission_allowed mismatch")
    check_budget()

    g._verify_source_closure(plan["generation_sources"])
    check_budget()

    expected_rels = {str(p.relative_to(g.ROOT)) for p in g._source_closure_paths()} | {
        "scripts/experiments/e28/e28_score.py",
        "scripts/experiments/e27/e27_prior_score_v2.py",
        "scripts/experiments/e27/e27_score_environment_v2.py",
        "analysis/e28_appearance_cost_design.md",
        ".venv/lib/python3.12/site-packages/threadpoolctl.py",
        ".venv/lib/python3.12/site-packages/polars/__init__.py",
        ".venv/lib/python3.12/site-packages/blosc2/__init__.py",
        ".venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib"}
    official = g.ROOT / "official" / "src" / "tracking_cellmot"
    for p in sorted(official.rglob("*.py")):
        expected_rels.add(str(p.relative_to(g.ROOT)))
    score_sources = plan["score_sources"]
    if not isinstance(score_sources, dict) or set(score_sources) != expected_rels:
        raise RuntimeError("score_sources keyset mismatch")
    for rel in sorted(expected_rels):
        ref = score_sources[rel]
        if type(ref) is not dict or set(ref) != {"path", "bytes", "sha256"}:
            raise RuntimeError(f"score source ref malformed: {rel}")
        if g._binding_for_path(g.ROOT / rel, label=rel) != ref:
            raise RuntimeError(f"score source drift: {rel}")
        check_budget()
    e._git_identity()
    check_budget()

    baseline_path = Path(plan["baseline_output"])
    if not baseline_path.is_absolute() or baseline_path.resolve() != baseline_path:
        raise RuntimeError("baseline_output must be a canonical absolute path")
    baseline = verify_generation(baseline_path, "e28_none",
                                 plan["generation_sources"], plan["appearance_plan"],
                                 check_budget)
    if baseline["bindings"] != plan["baseline_bindings"]:
        raise RuntimeError("baseline bindings mismatch")
    check_budget()

    cand = Path(plan["candidate_output"])
    if (cand.parent != g.ROOT / "outputs" / "local" or cand.resolve() != cand or
            cand == baseline_path or cand == plan_path.parent):
        raise RuntimeError("candidate_output path invalid")
    if before_generation:
        if cand.exists() or cand.with_name(cand.name + "_supervisor").exists():
            raise RuntimeError("candidate output already exists")

    ap = plan["appearance_plan"]
    expected_ap = g.prepare_appearance_plan()
    if type(ap) is not dict or type(expected_ap) is not dict:
        raise RuntimeError("appearance_plan schema mismatch")
    if ap != expected_ap:
        raise RuntimeError("appearance_plan mismatch vs prepare_appearance_plan")
    check_budget()

    legacy_base = g.ROOT / "outputs/local/e26_screen_preregistrations/e26_motion_off_screen_v2_20260908073709Z"
    LEGACY_SHA = {"PREREGISTRATION.json": "5abd92bd3ccd6533769a66e71e44f61b4b0a7b88d5d8228c0dbd195a43d1aa02",
                  "GT_BINDING.json": "f2842591cfa6750a443aae0d6d2ffd44616b1c0d7ad3bb93cb0f6a83a662b3b1"}
    legacy = {}
    for key, name in (("legacy_public", "PREREGISTRATION.json"), ("legacy_private", "GT_BINDING.json")):
        ref = plan[key]
        lp = legacy_base / name
        if type(ref) is not dict or ref != g._binding_for_path(lp, label=name):
            raise RuntimeError(f"legacy binding drift before read: {name}")
        if ref["sha256"] != LEGACY_SHA[name]:
            raise RuntimeError(f"legacy sha constant mismatch: {name}")
        legacy[name] = json.loads(lp.read_bytes())
        if g._binding_for_path(lp, label=name) != ref:
            raise RuntimeError(f"legacy binding drift after read: {name}")
        check_budget()
    public, private = legacy["PREREGISTRATION.json"], legacy["GT_BINDING.json"]

    c = baseline["control"]
    if c["generation_input_binding"] != public["generation_input_binding"]:
        raise RuntimeError("generation_input_binding mismatch vs public")
    if c["dependency_binding"] != public["dependency_binding"]:
        raise RuntimeError("dependency_binding mismatch vs public")
    e.verify_dependency_binding(c["dependency_binding"])
    check_budget()

    gib = c["generation_input_binding"]
    e.verify_inventory(gib["checkpoint"])
    check_budget()
    e.verify_inventory(gib["manifest"])
    check_budget()
    e.verify_inventory(gib["eval36"]["raw_inventory"])
    check_budget()

    def _known12(records, label):
        by_stem = {s: [] for s in g.STEMS}
        for row in records:
            ds = row.get("dataset")
            if ds not in by_stem:
                continue
            by_stem[ds].append(row)
        out = {}
        for stem in g.STEMS:
            rows = by_stem[stem]
            if len(rows) != 1:
                raise RuntimeError(f"{label} needs exactly one known video for {stem}")
            out[stem] = rows[0]
        return out

    priv12 = _known12(private["videos"], "private")
    pub12 = _known12(gib["eval36"]["videos"], "registration")
    for stem in g.STEMS:
        gtrow, imrow = priv12[stem], pub12[stem]
        e.verify_inventory(gtrow["gt_inventory"])
        check_budget()
        e.verify_inventory(imrow["image_inventory"])
        check_budget()
        bound_meta = e.bind_image_metadata(imrow["image_inventory"])
        if not (bound_meta == imrow["metadata"] == gtrow["image_metadata"]):
            raise RuntimeError(f"image metadata binding mismatch: {stem}")
        gp = Path(gtrow["gt_inventory"]["selected_path"])
        ip = Path(imrow["image_inventory"]["selected_path"])
        if gp != g.ROOT / "data" / "train" / (stem + ".geff"):
            raise RuntimeError(f"GT path mismatch: {stem}")
        if ip != g.ROOT / "data" / "train" / (stem + ".zarr"):
            raise RuntimeError(f"image path mismatch: {stem}")
        check_budget()

    for rel, ref in c["metadata_bindings"].items():
        if g._binding_for_path(Path(ref["path"]), label=rel) != ref:
            raise RuntimeError(f"metadata binding drift: {rel}")
        check_budget()
    for rel, ref in c["reader_bindings"].items():
        rp = g.COLLECTION_ROOT / rel
        if rp.resolve() != rp:
            raise RuntimeError(f"reader path is not canonical: {rel}")
        if g.COLLECTION_ROOT not in rp.parents and rp != g.COLLECTION_ROOT:
            raise RuntimeError(f"reader path escapes collection root: {rel}")
        cur = g._binding_for_path(rp, label=rel)
        if cur["bytes"] != ref["bytes"] or cur["sha256"] != ref["sha256"]:
            raise RuntimeError(f"reader binding drift: {rel}")
        check_budget()

    for rel in sorted(expected_rels):
        if g._binding_for_path(g.ROOT / rel, label=rel) != score_sources[rel]:
            raise RuntimeError(f"score source post-drift: {rel}")
        check_budget()
    for key, name in (("legacy_public", "PREREGISTRATION.json"), ("legacy_private", "GT_BINDING.json")):
        if g._binding_for_path(legacy_base / name, label=name) != plan[key]:
            raise RuntimeError(f"legacy post-drift: {name}")
        check_budget()
    if g._binding_for_path(plan_path, label="plan") != plan_ref:
        raise RuntimeError("plan binding changed during verification")
    check_budget()

    return {"plan": plan, "plan_binding": plan_ref, "baseline": baseline,
            "gt_inputs": {"private": {"videos": [priv12[s] for s in g.STEMS]},
                          "public_registration": {"generation_input_binding": gib}}}


def run_registered_generation(plan_path, expected_sha):
    """Force final PLAN verification before/after the frozen e28_appearance runner."""
    import time

    from biohub import e26_screen as e

    start = time.monotonic()

    def check_budget():
        return e.check_runtime_budget(
            start, wall_limit_seconds=1800, ram_limit_bytes=8 * 1024**3
        )

    cb = check_budget
    cb()

    plan_path = Path(plan_path)
    checked = verify_plan(
        plan_path, expected_sha, before_generation=True, check_budget=cb
    )
    if checked["plan_binding"]["sha256"] != expected_sha:
        raise RuntimeError("PLAN binding does not match expected sha256")
    p = checked["plan"]

    pregen_path = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    doc = {
        "schema": "E28_PREGEN_PLAN_VERIFIED_V1",
        "plan_binding": checked["plan_binding"],
        "candidate_output": p["candidate_output"],
        "mode": "e28_appearance",
        "utc": g._utc_stamp(),
        "submission_authorized": False,
    }
    cb()
    ref = e.write_json_exclusive(pregen_path, doc)
    cb()

    after = verify_plan(
        plan_path, expected_sha, before_generation=True, check_budget=cb
    )
    if e._json_bytes(after) != e._json_bytes(checked):
        raise RuntimeError("PLAN changed around pre-generation receipt")
    cb()
    rebind = g._binding_for_path(pregen_path, label="pregen")
    if rebind != ref:
        raise RuntimeError("pre-generation receipt identity changed")
    cb()
    if e._json_bytes(json.loads(pregen_path.read_text(encoding="utf-8"))) != e._json_bytes(doc):
        raise RuntimeError("pre-generation receipt content changed")
    cb()

    cb()
    g.supervise_baseline(Path(p["candidate_output"]), mode="e28_appearance")
    cb()

    post = verify_plan(
        plan_path, expected_sha, before_generation=False, check_budget=cb
    )
    if e._json_bytes(post) != e._json_bytes(checked):
        raise RuntimeError("PLAN changed during generation")
    if e._json_bytes(post["baseline"]["bindings"]) != e._json_bytes(checked["baseline"]["bindings"]):
        raise RuntimeError("baseline bindings changed during generation")
    candidate = verify_generation(
        Path(p["candidate_output"]),
        "e28_appearance",
        p["generation_sources"],
        p["appearance_plan"],
        cb,
    )
    if g._binding_for_path(pregen_path, label="pregen") != ref:
        raise RuntimeError("pre-generation receipt rebound after generation")

    cb()
    return {
        "schema": "E28_REGISTERED_GENERATION_V1",
        "status": "GENERATED_NOT_SCORED",
        "plan_binding": checked["plan_binding"],
        "pregen_binding": ref,
        "generation_bindings": candidate["bindings"],
        "submission_authorized": False,
    }


def main(argv=None):
    import argparse
    import sys

    from scripts.experiments.e27 import e27_prior_score_v2 as shared

    parser = argparse.ArgumentParser(prog="e28_score")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("score-child", "score"):
        sp = sub.add_parser(name)
        sp.add_argument("--plan", type=Path, required=True)
        sp.add_argument("--plan-sha", type=str, required=True)
        sp.add_argument("--pregen-sha", type=str, required=True)
        sp.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "score-child":
            result = shared.run_score_child(
                args.plan,
                args.plan_sha,
                args.pregen_sha,
                args.output,
                experiment="e28",
            )
        elif args.command == "score":
            result = shared.supervise_score(
                args.plan,
                args.plan_sha,
                args.pregen_sha,
                args.output,
                experiment="e28",
            )
        else:
            raise RuntimeError("unreachable command")
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "submission_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": result["status"],
                "submission_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
