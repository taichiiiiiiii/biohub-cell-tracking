"""Prior-score receipt reader for issue 9 (bounded extraction checkpoint)."""

import json
from pathlib import Path

from scripts.experiments.e27 import e27_association_prior_screen as g
from scripts.experiments.e27.e27_score_environment_v2 import verify_import_environment


def read_generation_receipts(output: Path) -> dict:
    """Bind and read the three generation receipts plus their parent logs."""
    output = Path(output)
    if not output.is_absolute():
        raise RuntimeError(f"output must be absolute: {output}")
    if output.parent != g.ROOT / "outputs" / "local":
        raise RuntimeError(f"output outside expected root: {output}")
    if output.resolve() != output:
        raise RuntimeError(f"output not resolved: {output}")
    if not output.is_dir():
        raise RuntimeError(f"output is not a directory: {output}")
    if output.is_symlink():
        raise RuntimeError(f"output symlink rejected: {output}")

    audit = output.with_name(output.name + "_supervisor")
    if not audit.is_dir():
        raise RuntimeError(f"audit is not a directory: {audit}")
    if audit.is_symlink():
        raise RuntimeError(f"audit symlink rejected: {audit}")
    if audit.resolve() != audit:
        raise RuntimeError(f"audit not resolved: {audit}")

    for path in list(output.rglob("*")) + list(audit.rglob("*")):
        if path.name == "ERROR.json" or path.name.endswith(".failed.json"):
            raise RuntimeError(f"failure artifact present: {path}")
    total = g._output_tree_bytes(output) + g._output_tree_bytes(audit)
    if total > g._OUTPUT_LIMIT_BYTES:
        raise RuntimeError(f"tree bytes {total} exceed limit")

    paths = {
        "supervisor": audit / "SUPERVISOR_RESULT.json",
        "result": output / "RESULT.json",
        "control": output / "CONTROL.json",
    }
    refs = {k: g._binding_for_path(p, label=k) for k, p in paths.items()}
    docs = {}
    for key, path in paths.items():
        doc = json.loads(path.read_text(encoding="utf-8"))
        if type(doc) is not dict:
            raise RuntimeError(f"{key} is not a dict")
        docs[key] = doc

    supervisor, result = docs["supervisor"], docs["result"]
    if supervisor["result_binding"] != refs["result"]:
        raise RuntimeError("supervisor result_binding mismatch")
    if result["control_binding"] != refs["control"]:
        raise RuntimeError("result control_binding mismatch")

    logs = supervisor["log_bindings"]
    if type(logs) is not dict or set(logs) != {"stdout.log", "stderr.log"}:
        raise RuntimeError("log_bindings keyset invalid")
    for name, expected in logs.items():
        if g._binding_for_path(audit / name, label=name) != expected:
            raise RuntimeError(f"log binding mismatch: {name}")

    for key, path in paths.items():
        if g._binding_for_path(path, label=key) != refs[key]:
            raise RuntimeError(f"binding changed after read: {key}")

    return {**docs, "bindings": refs}


def verify_generation(output: Path, arm: str, expected_sources: dict, expected_prior: dict) -> dict:
    """Verify one generated (unscored) E27 child run and its supervisor."""
    from biohub import e26_screen as e

    if type(arm) is not str or arm not in ("selected_only", "recorded_prior"):
        raise ValueError(arm)
    output = Path(output)
    docs = read_generation_receipts(output)
    r, c, s = docs["result"], docs["control"], docs["supervisor"]

    child_status = ("E27_SELECTED_ONLY_PARITY_PASS_NOT_CANDIDATE" if arm == "selected_only"
                    else "E27_RECORDED_PRIOR_GENERATED_UNSCORED")
    parent_status = ("E27_SELECTED_ONLY_SUPERVISED_PASS_NOT_CANDIDATE" if arm == "selected_only"
                     else "E27_RECORDED_PRIOR_SUPERVISED_UNSCORED")
    for doc, want in ((r, child_status), (s, parent_status)):
        if doc.get("status") != want:
            raise ValueError(f"status {doc.get('status')} != {want}")

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

    receipt = expected_prior
    if type(receipt) is not dict:
        raise ValueError("expected_prior receipt must be a dict")
    if receipt.get("mode") != arm:
        raise ValueError("receipt mode mismatch")
    if receipt.get("datasets") != list(g.STEMS):
        raise ValueError("receipt datasets mismatch")
    sha = receipt.get("sha256")
    if type(sha) is not str or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("receipt sha256 malformed")
    for field in ("entries_by_dataset", "eligible_unselected_by_dataset"):
        counts = receipt.get(field)
        if type(counts) is not dict or set(counts) != set(g.STEMS):
            raise ValueError(f"receipt {field} keys malformed")
        for stem in g.STEMS:
            value = counts[stem]
            if type(value) is not int or value < 0:
                raise ValueError(f"receipt {field}[{stem}] malformed")
    for stem in g.STEMS:
        if receipt["eligible_unselected_by_dataset"][stem] > receipt["entries_by_dataset"][stem]:
            raise ValueError(f"novel exceeds entries for {stem}")
    novel = [
        receipt["eligible_unselected_by_dataset"][stem]
        for stem in g.STEMS
    ]
    if arm == "selected_only" and sum(novel) != 0:
        raise ValueError("selected_only receipt must have no eligible unselected entries")
    if arm == "recorded_prior" and sum(novel) <= 0:
        raise ValueError("recorded_prior receipt requires eligible unselected entries")
    for doc in (c, r, s):
        if doc["association_priors"] != expected_prior:
            raise ValueError("association_priors mismatch")

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
        if g._binding_for_path(output / rel, label=rel) != binding:
            raise ValueError(f"artifact hash drift {rel}")
    csv_binding = g._binding_for_path(output / "submission.csv", label="csv")
    if r["csv_binding"] != csv_binding:
        raise ValueError("csv_binding mismatch")
    if arm == "selected_only":
        if csv_binding["bytes"] != g._REFERENCE_BYTES or csv_binding["sha256"] != g._REFERENCE_SHA256:
            raise ValueError("selected_only CSV must match reference")

    rows = c["generation_input_binding"]["eval36"]["videos"]
    seen = [row["dataset"] for row in rows if row["dataset"] in g.STEMS]
    if sorted(seen) != sorted(g.STEMS):
        raise ValueError("selected datasets missing or duplicated")
    shapes = {row["dataset"]: tuple(row["metadata"]["shape_tzyx"]) for row in rows
              if row["dataset"] in g.STEMS}

    report = e.validate_generated_csv(output / "submission.csv", datasets=g.STEMS, shapes=shapes)
    if report != r["counts"]:
        raise ValueError("csv report differs from result counts")

    bounds = json.loads((output / "output_bounds.json").read_text())
    e._validate_screen_bounds(bounds, output / "submission.csv", shapes)

    raw = json.loads((output / "raw_statistics.json").read_text())
    g.validate_known12_statistics(raw, arm="baseline", csv_report=report)

    after = read_generation_receipts(output)
    if after != docs:
        raise ValueError("receipts changed during verification")
    for rel, binding in r["artifact_bindings"].items():
        if g._binding_for_path(output / rel, label=rel) != binding:
            raise ValueError(f"artifact hash drift after validation {rel}")
    g._verify_source_closure(expected_sources)

    return {**docs, "csv_report": report, "shapes": {stem: list(shape) for stem, shape in shapes.items()}}


def verify_plan(plan_path: Path, expected_sha: str, *, before_generation: bool = False) -> dict:
    from biohub import e26_screen as e

    plan_path = Path(plan_path)
    if (not plan_path.is_absolute() or plan_path.resolve() != plan_path or
            plan_path.name != "PLAN.json" or
            plan_path.parent.parent != g.ROOT / "outputs" / "local"):
        raise RuntimeError(f"plan path must be canonical: {plan_path}")
    plan_ref = g._binding_for_path(plan_path, label="plan")
    if plan_ref["sha256"] != expected_sha:
        raise RuntimeError("plan sha256 mismatch")
    plan = json.loads(plan_path.read_text())
    if type(plan) is not dict:
        raise RuntimeError("plan is not an object")
    if set(plan) != {"schema", "candidate_id", "datasets", "baseline_output", "candidate_output",
                     "baseline_bindings", "generation_sources", "baseline_prior", "candidate_prior",
                     "score_sources", "legacy_public", "legacy_private", "submission_allowed"}:
        raise RuntimeError("plan keys mismatch")
    if plan["schema"] != "E27_EVAL12_PLAN_V2" or plan["candidate_id"] != "E27_RECORDED_PRIOR_V1":
        raise RuntimeError("plan schema/candidate mismatch")
    if plan["datasets"] != list(g.STEMS) or plan["submission_allowed"] is not False:
        raise RuntimeError("plan datasets/submission_allowed mismatch")

    g._verify_source_closure(plan["generation_sources"])

    expected_rels = {str(p.relative_to(g.ROOT)) for p in g._source_closure_paths()} | {
        "scripts/experiments/e27/e27_prior_score_v2.py",
        "analysis/e27_prior_scoring_design.md",
        "analysis/e27_prior_scoring_v2_design.md",
        "scripts/experiments/e27/e27_score_environment_v2.py",
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
    e._git_identity()

    baseline_path = Path(plan["baseline_output"])
    if not baseline_path.is_absolute() or baseline_path.resolve() != baseline_path:
        raise RuntimeError("baseline_output must be a canonical absolute path")
    baseline = verify_generation(baseline_path, "selected_only",
                                 plan["generation_sources"], plan["baseline_prior"])
    if baseline["bindings"] != plan["baseline_bindings"]:
        raise RuntimeError("baseline bindings mismatch")

    cand = Path(plan["candidate_output"])
    if (cand.parent != g.ROOT / "outputs" / "local" or cand.resolve() != cand or
            cand == baseline_path or cand == plan_path.parent):
        raise RuntimeError("candidate_output path invalid")
    if before_generation:
        if cand.exists() or cand.with_name(cand.name + "_supervisor").exists():
            raise RuntimeError("candidate output already exists")

    cp = plan["candidate_prior"]
    if (type(cp) is not dict or set(cp) != {"mode", "datasets", "entries_by_dataset",
                                            "eligible_unselected_by_dataset", "sha256"}):
        raise RuntimeError("candidate_prior schema mismatch")
    if cp["mode"] != "recorded_prior" or cp["datasets"] != list(g.STEMS):
        raise RuntimeError("candidate_prior mode/datasets mismatch")
    entries = cp["entries_by_dataset"]
    eligible = cp["eligible_unselected_by_dataset"]
    if (type(entries) is not dict or type(eligible) is not dict or
            set(entries) != set(g.STEMS) or set(eligible) != set(g.STEMS)):
        raise RuntimeError("candidate_prior dataset keysets mismatch")
    total_eligible = 0
    for stem in g.STEMS:
        ent, eli = entries[stem], eligible[stem]
        if type(ent) is not int or type(eli) is not int or ent < 0 or eli < 0:
            raise RuntimeError(f"candidate_prior counts invalid: {stem}")
        if eli > ent:
            raise RuntimeError(f"candidate_prior eligible exceeds entries: {stem}")
        total_eligible += eli
    if total_eligible <= 0:
        raise RuntimeError("candidate_prior has no eligible frames")
    sha = cp["sha256"]
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise RuntimeError("candidate_prior sha256 invalid")

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
    public, private = legacy["PREREGISTRATION.json"], legacy["GT_BINDING.json"]

    c = baseline["control"]
    if c["generation_input_binding"] != public["generation_input_binding"]:
        raise RuntimeError("generation_input_binding mismatch vs public")
    if c["dependency_binding"] != public["dependency_binding"]:
        raise RuntimeError("dependency_binding mismatch vs public")
    e.verify_dependency_binding(c["dependency_binding"])

    gib = c["generation_input_binding"]
    e.verify_inventory(gib["checkpoint"])
    e.verify_inventory(gib["manifest"])
    e.verify_inventory(gib["eval36"]["raw_inventory"])

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
        e.verify_inventory(imrow["image_inventory"])
        bound_meta = e.bind_image_metadata(imrow["image_inventory"])
        if not (bound_meta == imrow["metadata"] == gtrow["image_metadata"]):
            raise RuntimeError(f"image metadata binding mismatch: {stem}")
        gp = Path(gtrow["gt_inventory"]["selected_path"])
        ip = Path(imrow["image_inventory"]["selected_path"])
        if gp != g.ROOT / "data" / "train" / (stem + ".geff"):
            raise RuntimeError(f"GT path mismatch: {stem}")
        if ip != g.ROOT / "data" / "train" / (stem + ".zarr"):
            raise RuntimeError(f"image path mismatch: {stem}")

    for rel, ref in c["metadata_bindings"].items():
        if g._binding_for_path(Path(ref["path"]), label=rel) != ref:
            raise RuntimeError(f"metadata binding drift: {rel}")
    for rel, ref in c["reader_bindings"].items():
        rp = g.COLLECTION_ROOT / rel
        if rp.resolve() != rp:
            raise RuntimeError(f"reader path is not canonical: {rel}")
        if g.COLLECTION_ROOT not in rp.parents and rp != g.COLLECTION_ROOT:
            raise RuntimeError(f"reader path escapes collection root: {rel}")
        cur = g._binding_for_path(rp, label=rel)
        if cur["bytes"] != ref["bytes"] or cur["sha256"] != ref["sha256"]:
            raise RuntimeError(f"reader binding drift: {rel}")

    for rel in sorted(expected_rels):
        if g._binding_for_path(g.ROOT / rel, label=rel) != score_sources[rel]:
            raise RuntimeError(f"score source post-drift: {rel}")
    for key, name in (("legacy_public", "PREREGISTRATION.json"), ("legacy_private", "GT_BINDING.json")):
        if g._binding_for_path(legacy_base / name, label=name) != plan[key]:
            raise RuntimeError(f"legacy post-drift: {name}")
    if g._binding_for_path(plan_path, label="plan") != plan_ref:
        raise RuntimeError("plan binding changed during verification")

    return {"plan": plan, "plan_binding": plan_ref, "baseline": baseline,
            "gt_inputs": {"private": {"videos": [priv12[s] for s in g.STEMS]},
                          "public_registration": {"generation_input_binding": gib}}}


def score_eval12_core(checked_plan, candidate, output, check_budget):
    """Score eval12 baseline/candidate arms from verified inputs; no seals."""
    from biohub import e26_screen as e
    plan = checked_plan["plan"]
    base = checked_plan["baseline"]
    if plan["candidate_id"] != "E27_RECORDED_PRIOR_V1":
        raise ValueError(f"unexpected candidate_id: {plan['candidate_id']!r}")
    for key in ("config", "dependency_binding", "generation_input_binding",
                "metadata_bindings", "reader_bindings", "source_bindings"):
        if base["control"][key] != candidate["control"][key]:
            raise ValueError(f"CONTROL binding mismatch: {key}")
    checks = ((candidate["control"]["arm"], "recorded_prior"),
              (base["control"]["arm"], "selected_only"),
              (candidate["control"]["source_bindings"], plan["generation_sources"]),
              (base["control"]["source_bindings"], plan["generation_sources"]),
              (candidate["control"]["association_priors"], plan["candidate_prior"]),
              (base["control"]["association_priors"], plan["baseline_prior"]),
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


def verify_score_core(plan_path, expected_sha, checked_plan, candidate, output,
                      core, check_budget, *, experiment="e27"):
    """Post-score verifier for an e27 prior-score core.

    NOT a scorer and NOT a final seal: it never calls official score_submission
    or _check_stage_gt (no repeated scoring/GT semantics).  It re-verifies the
    plan and the recorded candidate generation, rejects source/material/input
    drift by byte comparison against the caller-supplied objects, then rebuilds
    each arm's official record from the on-disk artifact rows and the
    per-dataset prediction-CSV counts read from that arm's own record, and
    strictly compares the rebuilt arms and the identity-adapted paired record
    against `core`.

    Trust model: `core` is the original in-memory object retained by the outer
    caller that produced it; it is not treated as a signed external input.  The
    arm artifacts are hash-bound to `core["arm_artifacts"]` at write time by
    the scorer, so only their structure/keys are validated here beyond the
    binding equality.

    Raises ValueError/RuntimeError on any mismatch; no fallback.
    """
    from biohub import e26_screen as e

    def _fail(msg):
        raise ValueError("verify_score_core: " + msg)

    if type(experiment) is not str or experiment not in ("e27", "e28"):
        raise ValueError("unsupported experiment")
    expected_candidate_id = ("E27_RECORDED_PRIOR_V1" if experiment == "e27"
                             else "E28_APPEARANCE_COST_V1")
    appearance = None
    if experiment == "e28":
        from scripts.experiments.e28 import e28_score as appearance

    if not isinstance(core, dict):
        _fail("core must be a dict")
    want_keys = {"stage", "candidate_id", "arms", "paired", "arm_artifacts",
                 "timing", "submission_authorized"}
    if set(core) != want_keys:
        _fail(f"core keys {sorted(core)!r} != {sorted(want_keys)!r}")
    if core["stage"] != "eval12" or core["candidate_id"] != expected_candidate_id:
        _fail("core stage/candidate_id identity mismatch")
    if core["submission_authorized"] is not False:
        _fail("core submission_authorized must be False")

    arms = core["arms"]
    arts = core["arm_artifacts"]
    if not isinstance(arms, dict) or set(arms) != {"baseline", "candidate"}:
        _fail("core arms keys must be exactly baseline,candidate")
    if not isinstance(arts, dict) or set(arts) != {"baseline", "candidate"}:
        _fail("core arm_artifacts keys must be exactly baseline,candidate")

    # 1: fresh plan verification, reject drift versus the checked plan.
    check_budget()
    if experiment == "e28":
        fresh = appearance.verify_plan(plan_path, expected_sha,
                                       check_budget=check_budget)
    else:
        fresh = verify_plan(plan_path, expected_sha)
    if e._json_bytes(fresh) != e._json_bytes(checked_plan):
        _fail("plan drifted since scoring (source/material/input change)")
    plan = fresh["plan"]
    if plan.get("candidate_id") != core["candidate_id"]:
        _fail("plan candidate_id differs from core")

    # 2: fresh candidate-generation verification, reject drift.
    if experiment == "e28":
        newcand = appearance.verify_generation(
            Path(plan["candidate_output"]), "e28_appearance",
            plan["generation_sources"], plan["appearance_plan"], check_budget)
    else:
        newcand = verify_generation(Path(plan["candidate_output"]),
                                    "recorded_prior",
                                    plan["generation_sources"],
                                    plan["candidate_prior"])
    if e._json_bytes(newcand) != e._json_bytes(candidate):
        _fail("candidate generation drifted since scoring")

    # 4/5: per-arm artifact checks and official-record rebuild.
    rebuilt = {}
    counts = {}
    for arm in ("baseline", "candidate"):
        check_budget()
        p = Path(output) / (arm + ".json")
        ref = core["arm_artifacts"][arm]
        if ref != g._binding_for_path(p, label=arm):
            _fail(f"{arm} artifact binding changed (path/sha pin)")
        doc = json.loads(p.read_bytes())
        if set(doc) != {"arm", "candidate_id", "official", "gt_preflight",
                        "csv_binding"}:
            _fail(f"{arm} artifact keys unexpected")
        if doc["arm"] != arm or doc["candidate_id"] != core["candidate_id"]:
            _fail(f"{arm} artifact arm/candidate_id mismatch")
        record = fresh["baseline"] if arm == "baseline" else newcand
        if e._json_bytes(doc["csv_binding"]) != \
                e._json_bytes(record["result"]["csv_binding"]):
            _fail(f"{arm} csv_binding differs from its own verified record")
        pre = doc["gt_preflight"]
        if not isinstance(pre, dict) or set(pre) != {"stage", "videos"}:
            _fail(f"{arm} gt_preflight structure unexpected")
        if pre["stage"] != "eval12" or not isinstance(pre["videos"], list):
            _fail(f"{arm} gt_preflight stage/videos unexpected")
        for row in pre["videos"]:
            if set(row) != {"dataset", "estimated_number_of_nodes", "scale_zyx"}:
                _fail(f"{arm} gt_preflight video row keys unexpected")
        counts[arm] = {row["dataset"]: row
                       for row in record["csv_report"]["per_dataset"]}
        rows = doc["official"]["rows"]
        rebuilt[arm] = e._score_arm_record(rows, "eval12", counts[arm])
        if e._json_bytes(rebuilt[arm]) != e._json_bytes(doc["official"]):
            _fail(f"{arm} rebuilt official record differs from artifact")
        if e._json_bytes(rebuilt[arm]) != e._json_bytes(arms[arm]):
            _fail(f"{arm} rebuilt official record differs from core arms")

    # 6: paired record with identity-only candidate_id adaptation.
    check_budget()
    paired = e._paired_score_record("eval12", rebuilt, counts)
    if paired.get("gate", {}).get("candidate_id") != e.CANDIDATE_ID:
        _fail("paired gate candidate_id must equal e.CANDIDATE_ID")
    adapted = json.loads(e._json_bytes(paired))
    if isinstance(adapted.get("gate"), dict) and "candidate_id" in adapted["gate"]:
        old = adapted["gate"]["candidate_id"]
        adapted["gate"]["candidate_id"] = core["candidate_id"]
        adapted["gate"]["rule_implementation_candidate_id"] = old
    if e._json_bytes(adapted) != e._json_bytes(core["paired"]):
        _fail("adapted paired record differs from core paired (all diagnostics)")

    # 7: rebind arm files and re-verify plan/candidate after reconstruction.
    check_budget()
    for arm in ("baseline", "candidate"):
        p = Path(output) / (arm + ".json")
        if core["arm_artifacts"][arm] != g._binding_for_path(p, label=arm):
            _fail(f"{arm} artifact rebinding failed after read/math")
    if experiment == "e28":
        fresh2 = appearance.verify_plan(plan_path, expected_sha,
                                        check_budget=check_budget)
    else:
        fresh2 = verify_plan(plan_path, expected_sha)
    if e._json_bytes(fresh2) != e._json_bytes(checked_plan):
        _fail("plan drifted during verification")
    if experiment == "e28":
        newcand2 = appearance.verify_generation(
            Path(plan["candidate_output"]), "e28_appearance",
            plan["generation_sources"], plan["appearance_plan"], check_budget)
    else:
        newcand2 = verify_generation(Path(plan["candidate_output"]),
                                     "recorded_prior",
                                     plan["generation_sources"],
                                     plan["candidate_prior"])
    if e._json_bytes(newcand2) != e._json_bytes(candidate):
        _fail("candidate drifted during verification")
    check_budget()

    # 8: result only; nothing is written or sealed here.
    return {"verified": True, "stage": "eval12",
            "candidate_id": plan["candidate_id"],
            "status": adapted["gate"]["status"], "paired": adapted,
            "arm_artifacts": core["arm_artifacts"],
            "submission_authorized": False}


def _score_protocol(experiment: str) -> dict:
    """Return the fixed score-protocol literals for an approved experiment.

    Type is checked exactly before any comparison so that string subclasses and
    objects with overloaded equality can never select a protocol.
    """
    if type(experiment) is not str:
        raise ValueError("unsupported experiment")
    if experiment == "e27":
        return {
            "candidate_id": "E27_RECORDED_PRIOR_V1",
            "mode": "recorded_prior",
            "module": "scripts.experiments.e27.e27_prior_score_v2",
            "pregen": "E27_PREGEN_PLAN_VERIFIED_V1",
            "started": "E27_SCORE_STARTED_V2",
            "result": "E27_SCORE_RESULT_V1",
            "error": "E27_SCORE_ERROR_V1",
            "supervisor": "E27_SCORE_SUPERVISOR_V1",
            "supervisor_error": "E27_SCORE_SUPERVISOR_ERROR_V1",
        }
    if experiment == "e28":
        return {
            "candidate_id": "E28_APPEARANCE_COST_V1",
            "mode": "e28_appearance",
            "module": "scripts.experiments.e28.e28_score",
            "pregen": "E28_PREGEN_PLAN_VERIFIED_V1",
            "started": "E28_SCORE_STARTED_V1",
            "result": "E28_SCORE_RESULT_V1",
            "error": "E28_SCORE_ERROR_V1",
            "supervisor": "E28_SCORE_SUPERVISOR_V1",
            "supervisor_error": "E28_SCORE_SUPERVISOR_ERROR_V1",
        }
    raise ValueError("unsupported experiment")


def run_score_child(plan_path, expected_sha, pregen_sha, output, *, experiment="e27"):
    protocol = _score_protocol(experiment)

    import datetime
    import os
    import random
    import signal
    import time

    from biohub import e26_screen as e

    appearance = None
    if experiment == "e28":
        from scripts.experiments.e28 import e28_score as appearance

    start = time.monotonic()
    e._check_score_entry_runtime()
    if signal.getitimer(signal.ITIMER_REAL)[0] != 0.0:
        raise RuntimeError("live SIGALRM timer already armed")
    out = g._canonical_new_output_dir(Path(output))
    handler_installed = False
    timer_owned = False
    prev_handler = None

    def check_budget():
        timing = e.check_runtime_budget(start, wall_limit_seconds=1800,
                                        ram_limit_bytes=8 * 1024 ** 3)
        ob = g._output_tree_bytes(out)
        if ob > 256 * 1024 ** 2:
            raise RuntimeError(f"output budget exceeded: {ob}")
        timing["output_bytes"] = ob
        return timing

    try:
        def _on_alarm(signum, frame):
            raise TimeoutError("wall deadline reached")

        prev_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _on_alarm)
        handler_installed = True
        remaining = 1800.0 - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError("wall deadline reached")
        signal.setitimer(signal.ITIMER_REAL, remaining)
        timer_owned = True

        check_budget()
        if experiment == "e28":
            checked = appearance.verify_plan(Path(plan_path), expected_sha,
                                             check_budget=check_budget)
        else:
            checked = verify_plan(Path(plan_path), expected_sha)
        check_budget()
        plan = checked["plan"]
        if experiment == "e28":
            candidate = appearance.verify_generation(
                Path(plan["candidate_output"]), "e28_appearance",
                plan["generation_sources"], plan["appearance_plan"], check_budget)
        else:
            candidate = verify_generation(
                Path(plan["candidate_output"]), "recorded_prior",
                plan["generation_sources"], plan["candidate_prior"])
        check_budget()

        pregenpath = Path(plan_path).parent / "PREGEN_PLAN_VERIFIED.json"
        ref = g._binding_for_path(pregenpath, label="pregen")
        if ref["sha256"] != pregen_sha:
            raise RuntimeError("pregen binding mismatch")
        pregen = json.loads(pregenpath.read_text())
        if g._binding_for_path(pregenpath, label="pregen") != ref:
            raise RuntimeError("pregen changed after bind")
        if set(pregen) != {"schema", "plan_binding", "candidate_output", "mode",
                           "utc", "submission_authorized"}:
            raise RuntimeError("pregen schema keys")
        if pregen["schema"] != protocol["pregen"]:
            raise RuntimeError("pregen schema")
        if pregen["plan_binding"] != checked["plan_binding"]:
            raise RuntimeError("pregen plan binding")
        if pregen["candidate_output"] != plan["candidate_output"]:
            raise RuntimeError("pregen candidate output")
        if pregen["mode"] != protocol["mode"]:
            raise RuntimeError("pregen mode")
        if pregen["submission_authorized"] is not False:
            raise RuntimeError("pregen authorization flag")
        pregen_utc = datetime.datetime.strptime(pregen["utc"], "%Y%m%d%H%M%S%z")
        check_budget()

        sname = "STARTED.json"
        spath = Path(plan["candidate_output"]) / sname
        sref = g._binding_for_path(spath, label=sname)
        if sref != candidate["result"]["artifact_bindings"][sname]:
            raise RuntimeError("STARTED.json binding mismatch")
        started = json.loads(spath.read_text())
        if g._binding_for_path(spath, label=sname) != sref:
            raise RuntimeError("STARTED.json changed after bind")
        if set(started) != {"pid", "argv", "utc"}:
            raise RuntimeError("STARTED.json schema keys")
        started_utc = datetime.datetime.strptime(started["utc"], "%Y%m%d%H%M%S%z")
        if started_utc < pregen_utc:
            raise RuntimeError("STARTED.json precedes pregen receipt")
        check_budget()

        random.seed(0)
        import numpy as np
        np.random.seed(0)

        expected_environment = e.generation_environment()
        import_additions = verify_import_environment(
            expected_environment, dict(os.environ),
            str(g.ROOT / ".venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib"))
        e.write_json_exclusive(out / "SCORE_STARTED.json", {
            "schema": protocol["started"],
            "pid": os.getpid(),
            "plan_binding": checked["plan_binding"],
            "pregen_binding": ref,
            "environment": expected_environment,
            "import_environment_additions": import_additions,
            "seed": 0,
            "submission_authorized": False,
        })
        if experiment == "e28":
            core = appearance.score_eval12_core(checked, candidate, out, check_budget)
        else:
            core = score_eval12_core(checked, candidate, out, check_budget)
        coreref = e.write_json_exclusive(out / "SCORE_CORE.json", core)
        if experiment == "e28":
            verified = verify_score_core(Path(plan_path), expected_sha, checked,
                                         candidate, out, core, check_budget,
                                         experiment="e28")
        else:
            verified = verify_score_core(Path(plan_path), expected_sha, checked,
                                         candidate, out, core, check_budget)
        reread = json.loads((out / "SCORE_CORE.json").read_text())
        if e._json_bytes(reread) != e._json_bytes(core):
            raise RuntimeError("SCORE_CORE reparse mismatch")
        if g._binding_for_path(out / "SCORE_CORE.json",
                               label="SCORE_CORE.json") != coreref:
            raise RuntimeError("SCORE_CORE binding changed")
        if g._binding_for_path(pregenpath, label="pregen") != ref:
            raise RuntimeError("pregen changed after scoring")
        check_budget()

        result = {"schema": protocol["result"]}
        result.update(verified)
        result.update({
            "plan_binding": checked["plan_binding"], "pregen_binding": ref,
            "core_binding": coreref,
            "baseline_bindings": checked["baseline"]["bindings"],
            "candidate_bindings": candidate["bindings"],
            "timing": check_budget(), "submission_authorized": False})
        resref = e.write_json_exclusive(out / "SCORE_RESULT.json", result)
        if e._json_bytes(json.loads((out / "SCORE_RESULT.json").read_text())) \
                != e._json_bytes(result):
            raise RuntimeError("SCORE_RESULT reparse mismatch")
        if g._binding_for_path(out / "SCORE_RESULT.json",
                               label="SCORE_RESULT.json") != resref:
            raise RuntimeError("SCORE_RESULT binding changed")
        check_budget()
        return result
    except BaseException as exc:
        if timer_owned:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
            except BaseException:
                pass
            timer_owned = False
        failure = out / "SCORE_RESULT.failed.json"
        produced = out / "SCORE_RESULT.json"
        try:
            if produced.exists() and not failure.exists():
                produced.rename(failure)
        except BaseException:
            pass
        try:
            e.write_json_exclusive(out / "ERROR.json", {
                "schema": protocol["error"], "status": "ERROR",
                "error_type": type(exc).__name__,
                "submission_authorized": False})
        except BaseException:
            pass
        raise
    finally:
        if timer_owned:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
            except BaseException:
                pass
        if handler_installed:
            signal.signal(signal.SIGALRM, prev_handler)


def run_registered_generation(plan_path, expected_sha):
    """Force final PLAN verification before/after the frozen recorded_prior runner."""
    from biohub import e26_screen as e

    plan_path = Path(plan_path)
    checked = verify_plan(plan_path, expected_sha, before_generation=True)
    if checked["plan_binding"]["sha256"] != expected_sha:
        raise RuntimeError("PLAN binding does not match expected sha256")
    p = checked["plan"]

    pregen_path = plan_path.parent / "PREGEN_PLAN_VERIFIED.json"
    doc = {
        "schema": "E27_PREGEN_PLAN_VERIFIED_V1",
        "plan_binding": checked["plan_binding"],
        "candidate_output": p["candidate_output"],
        "mode": "recorded_prior",
        "utc": g._utc_stamp(),
        "submission_authorized": False,
    }
    ref = e.write_json_exclusive(pregen_path, doc)

    after = verify_plan(plan_path, expected_sha, before_generation=True)
    if e._json_bytes(after) != e._json_bytes(checked):
        raise RuntimeError("PLAN changed around pre-generation receipt")
    rebind = g._binding_for_path(pregen_path, label="pregen")
    if rebind != ref:
        raise RuntimeError("pre-generation receipt identity changed")
    if e._json_bytes(json.loads(pregen_path.read_text(encoding="utf-8"))) != e._json_bytes(doc):
        raise RuntimeError("pre-generation receipt content changed")

    g.supervise_baseline(Path(p["candidate_output"]), mode="recorded_prior")

    post = verify_plan(plan_path, expected_sha, before_generation=False)
    if e._json_bytes(post) != e._json_bytes(checked):
        raise RuntimeError("PLAN changed during generation")
    if e._json_bytes(post["baseline"]["bindings"]) != e._json_bytes(checked["baseline"]["bindings"]):
        raise RuntimeError("baseline bindings changed during generation")
    candidate = verify_generation(
        Path(p["candidate_output"]),
        "recorded_prior",
        p["generation_sources"],
        p["candidate_prior"],
    )
    if g._binding_for_path(pregen_path, label="pregen") != ref:
        raise RuntimeError("pre-generation receipt rebound after generation")

    return {
        "schema": "E27_REGISTERED_GENERATION_V1",
        "status": "GENERATED_NOT_SCORED",
        "plan_binding": checked["plan_binding"],
        "pregen_binding": ref,
        "generation_bindings": candidate["bindings"],
        "submission_authorized": False,
    }


def supervise_score(plan_path, expected_sha, pregen_sha, output, *,
                    experiment="e27"):
    """Supervise one E27/E28 scoring child and bind its complete receipt.

    Single launch only: the child is started exactly once, never retried, and
    every artifact is re-bound from disk after it is read.  No scientific
    decision is made here beyond relaying the child's verified status.
    """
    protocol = _score_protocol(experiment)

    import math
    import os
    import signal
    import subprocess
    import sys
    import time

    from biohub import e26_screen as e

    if experiment == "e28":
        from scripts.experiments.e28 import e28_score as appearance

    WALL_LIMIT_SECONDS = 1800
    OUTPUT_BYTES_LIMIT = 256 * 1024 ** 2
    PEAK_RSS_LIMIT = 8 * 1024 ** 3
    CHILD_FILES = ("SCORE_STARTED.json", "SCORE_CORE.json", "SCORE_RESULT.json",
                   "baseline.json", "candidate.json")

    start = time.monotonic()

    # ---------------------------------------------------------------- helpers
    def _reject(msg):
        raise RuntimeError(f"supervise_score: {msg}")

    def _is_number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) \
            and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))

    def _require_int(v, what):
        if type(v) is not int:
            _reject(f"{what} must be a builtin int")
        return v

    def _require_dict(d, what):
        if not isinstance(d, dict):
            _reject(f"{what} must be an object")
        return d

    def _exact_keys(obj, keys, what):
        _require_dict(obj, what)
        if set(obj) != set(keys):
            _reject(f"{what} keys {sorted(obj)!r} != required {sorted(keys)!r}")
        return obj

    def _no_error_markers(root_dir):
        root = Path(root_dir)
        if root.is_symlink():
            _reject(f"output symlink before tree walk: {root}")
        for path in sorted(root.rglob("*")):
            if path.name == "ERROR.json" or path.name.endswith(".failed.json"):
                _reject(f"failure marker present: {path.relative_to(root)}")

    def check_budget():
        elapsed = time.monotonic() - start
        if elapsed > WALL_LIMIT_SECONDS:
            _reject(f"wall budget exhausted ({elapsed:.3f}s)")
        total = g._output_tree_bytes(audit)
        if out_dir.exists():
            if out_dir.is_symlink():
                _reject(f"output symlink before tree walk: {out_dir}")
            total += g._output_tree_bytes(out_dir)
        if total > OUTPUT_BYTES_LIMIT:
            _reject(f"output bytes budget exhausted ({total})")
        return {"elapsed_seconds": elapsed, "total_output_bytes": total}

    # ------------------------------------------------------- output / audit dir
    if not isinstance(output, Path):
        output = Path(output)
    if not output.is_absolute():
        _reject("output must be an absolute path")
    out_dir = output
    outputs_root = g.ROOT / "outputs" / "local"
    if out_dir.parent != outputs_root:
        _reject("output must be a direct child of ROOT/outputs/local")
    if out_dir.resolve() != out_dir:
        _reject("output must resolve to itself")
    if out_dir.is_symlink():
        _reject("output must not be a symlink")
    if out_dir.exists():
        _reject(f"output must not exist: {out_dir}")
    # Deliberately do NOT create the child output directory here.

    proc = None
    kill_signals = []
    reap_error = None

    audit = g._canonical_new_output_dir(
        out_dir.with_name(out_dir.name + "_supervisor"))

    try:
        # ------------------------------------------------------ verification
        if experiment == "e28":
            checked = appearance.verify_plan(plan_path, expected_sha,
                                             check_budget=check_budget)
        else:
            checked = verify_plan(plan_path, expected_sha)
        p = checked["plan"]
        if experiment == "e28":
            candidate = appearance.verify_generation(
                Path(p["candidate_output"]), "e28_appearance",
                p["generation_sources"], p["appearance_plan"], check_budget)
        else:
            candidate = verify_generation(
                Path(p["candidate_output"]), "recorded_prior",
                p["generation_sources"], p["candidate_prior"])
        pregpath = Path(plan_path).parent / "PREGEN_PLAN_VERIFIED.json"
        pregref = g._binding_for_path(pregpath, label="pregen")
        if pregref["sha256"] != pregen_sha:
            _reject("pregen binding sha mismatch")

        budget = check_budget()
        remaining = WALL_LIMIT_SECONDS - budget["elapsed_seconds"]
        if remaining <= 0:
            _reject("no wall budget left for child")

        argv = [sys.executable, "-m", protocol["module"], "score-child",
                "--plan", str(plan_path), "--plan-sha", expected_sha,
                "--pregen-sha", pregen_sha, "--output", str(out_dir)]
        env = e.generation_environment()

        # --------------------------------------------------- single child launch
        out_path = audit / "stdout.log"
        err_path = audit / "stderr.log"
        fh_out = open(str(out_path), "xb")
        try:
            fh_err = open(str(err_path), "xb")
        except BaseException:
            fh_out.close()
            raise
        try:
            check_budget()
            proc = subprocess.Popen(argv, cwd=str(g.ROOT), env=env,
                                    stdin=subprocess.DEVNULL, stdout=fh_out,
                                    stderr=fh_err, start_new_session=True)
        finally:
            try:
                fh_out.close()
            finally:
                fh_err.close()

        rc = proc.wait(timeout=WALL_LIMIT_SECONDS - (time.monotonic() - start))
        if rc != 0:
            _reject(f"child exited nonzero ({rc!r})")

        check_budget()

        # ------------------------------------------------- failure markers/files
        _no_error_markers(out_dir)
        _no_error_markers(audit)
        actual = sorted(str(x.relative_to(out_dir))
                        for x in out_dir.rglob("*") if x.is_file())
        if actual != sorted(CHILD_FILES):
            _reject(f"child files {actual!r} != required five")

        refs = {}
        for name in CHILD_FILES:
            refs[name] = g._binding_for_path(out_dir / name, label=name)

        started = _require_dict(json.loads((out_dir / "SCORE_STARTED.json")
                                           .read_text(encoding="utf-8")),
                                "SCORE_STARTED")
        core = json.loads((out_dir / "SCORE_CORE.json").read_text(encoding="utf-8"))
        result = _require_dict(json.loads((out_dir / "SCORE_RESULT.json")
                                          .read_text(encoding="utf-8")),
                               "SCORE_RESULT")

        # Rebind after reads.
        for name in CHILD_FILES:
            fresh = g._binding_for_path(out_dir / name, label=name)
            if fresh != refs[name]:
                _reject(f"{name} changed after read")

        # ------------------------------------------------------- SCORE_STARTED
        _exact_keys(started, ("schema", "pid", "plan_binding", "pregen_binding",
                              "environment", "import_environment_additions",
                              "seed", "submission_authorized"),
                    "SCORE_STARTED keys")
        if started["schema"] != protocol["started"]:
            _reject("SCORE_STARTED schema mismatch")
        if _require_int(started["pid"], "SCORE_STARTED pid") != proc.pid:
            _reject("SCORE_STARTED pid mismatch")
        if e._json_bytes(started["environment"]) != e._json_bytes(env):
            _reject("SCORE_STARTED environment != child env")
        additions = _require_dict(started["import_environment_additions"],
                                  "SCORE_STARTED import additions")
        _exact_keys(additions, ("KMP_DUPLICATE_LIB_OK", "_RJEM_MALLOC_CONF",
                                "ME_DSL_JIT_LIBTCC_PATH"),
                    "SCORE_STARTED import additions keys")
        verify_import_environment(env, {**env, **additions},
                                  str(g.ROOT / ".venv/lib/python3.12/site-packages/blosc2/lib/libtcc.dylib"))
        seed = started["seed"]
        if type(seed) is not int or seed != 0:
            _reject("SCORE_STARTED seed must be exact int zero")
        if started["submission_authorized"] is not False:
            _reject("SCORE_STARTED submission_authorized must be False")
        if started["plan_binding"] != checked["plan_binding"]:
            _reject("SCORE_STARTED plan_binding mismatch")
        if started["pregen_binding"] != pregref:
            _reject("SCORE_STARTED pregen_binding mismatch")

        # ------------------------------------------------------------ core/result
        if experiment == "e28":
            verified = verify_score_core(plan_path, expected_sha, checked,
                                         candidate, out_dir, core, check_budget,
                                         experiment="e28")
        else:
            verified = verify_score_core(plan_path, expected_sha, checked,
                                         candidate, out_dir, core, check_budget)
        _require_dict(verified, "verified score core")
        if verified.get("verified") is not True:
            _reject("verified flag missing")
        if verified.get("stage") != "eval12":
            _reject("verified stage must be eval12")
        if verified.get("candidate_id") != protocol["candidate_id"]:
            _reject(f"verified candidate_id must be {protocol['candidate_id']}")
        if verified.get("submission_authorized") is not False:
            _reject("verified submission_authorized must be False")

        want_result = {
            "schema": protocol["result"],
            "plan_binding": checked["plan_binding"],
            "pregen_binding": pregref,
            "core_binding": refs["SCORE_CORE.json"],
            "baseline_bindings": checked["baseline"]["bindings"],
            "candidate_bindings": candidate["bindings"],
            "timing": result["timing"],
        }
        for k, v in verified.items():
            want_result[k] = v
        _exact_keys(result, tuple(want_result), "SCORE_RESULT keys")
        if e._json_bytes(result) != e._json_bytes(want_result):
            _reject("SCORE_RESULT strict JSON mismatch")

        timing = _exact_keys(result["timing"],
                             ("wall_seconds", "peak_rss_bytes", "ram_scope",
                              "output_bytes"), "timing keys")
        if timing["ram_scope"] != "self_process":
            _reject("timing ram_scope must be self_process")
        wall = timing["wall_seconds"]
        peak = _require_int(timing["peak_rss_bytes"], "peak_rss_bytes")
        obytes = _require_int(timing["output_bytes"], "output_bytes")
        if not _is_number(wall) or wall < 0 or wall > WALL_LIMIT_SECONDS:
            _reject("timing wall_seconds out of range")
        if peak < 0 or peak > PEAK_RSS_LIMIT:
            _reject("timing peak_rss_bytes out of range")
        if obytes < 0 or obytes > OUTPUT_BYTES_LIMIT:
            _reject("timing output_bytes out of range")

        # --------------------------------------------------------- supervisor record
        for name in CHILD_FILES:
            fresh = g._binding_for_path(out_dir / name, label=name)
            if fresh != refs[name]:
                _reject(f"{name} changed before supervisor write")
        preg_fresh = g._binding_for_path(pregpath, label="pregen")
        if preg_fresh != pregref:
            _reject("pregen changed before supervisor write")
        logrefs = {"stdout.log": g._binding_for_path(out_path, label="stdout.log"),
                   "stderr.log": g._binding_for_path(err_path, label="stderr.log")}
        check_budget()

        record = {
            "schema": protocol["supervisor"],
            "status": result["status"],
            "submission_authorized": False,
            "returncode": 0,
            "pid": proc.pid,
            "argv": argv,
            "environment": env,
            "output": str(out_dir),
            "audit_dir": str(audit),
            "plan_binding": checked["plan_binding"],
            "pregen_binding": pregref,
            "result_binding": refs["SCORE_RESULT.json"],
            "artifact_bindings": refs,
            "log_bindings": logrefs,
            "killpg_signals": [],
            "reap_error": None,
            "timing": check_budget(),
            "memory_scope": "child_self_peak_rss_not_process_group_cap",
        }
        sup_path = audit / "SUPERVISOR_RESULT.json"
        sup_ref = e.write_json_exclusive(sup_path, record)

        reparsed = _require_dict(json.loads(sup_path.read_text(encoding="utf-8")),
                                 "SUPERVISOR_RESULT reparse")
        if e._json_bytes(reparsed) != e._json_bytes(record):
            _reject("SUPERVISOR_RESULT round-trip mismatch")
        if g._binding_for_path(sup_path, label="supervisor") != sup_ref:
            _reject("SUPERVISOR_RESULT binding mismatch after write")

        for name in CHILD_FILES:
            fresh = g._binding_for_path(out_dir / name, label=name)
            if fresh != refs[name]:
                _reject(f"{name} changed after supervisor write")
        for name, ref in logrefs.items():
            if g._binding_for_path(audit / name, label=name) != ref:
                _reject(f"{name} changed after supervisor write")
        if g._binding_for_path(pregpath, label="pregen") != pregref:
            _reject("pregen changed after supervisor write")
        check_budget()
        return record

    except BaseException as exc:
        # ------------------------------------------- stop / reap the process group
        if proc is not None:
            try:
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                        kill_signals.append(int(signal.SIGTERM))
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                            kill_signals.append(int(signal.SIGKILL))
                        except ProcessLookupError:
                            pass
                        proc.wait(timeout=5)
                else:
                    proc.wait(timeout=5)
            except BaseException as cleanup_exc:
                reap_error = type(cleanup_exc).__name__

        # ---------------------------------------------- quarantine partial receipts
        try:
            src = audit / "SUPERVISOR_RESULT.json"
            dst = audit / "SUPERVISOR_RESULT.failed.json"
            if src.exists() and not dst.exists():
                os.rename(str(src), str(dst))
            if proc is not None:
                src = out_dir / "SCORE_RESULT.json"
                dst = out_dir / "SCORE_RESULT.failed.json"
                if src.exists() and not dst.exists():
                    os.rename(str(src), str(dst))
        except BaseException:
            pass

        # --------------------------------------------------------- ERROR.json
        try:
            e.write_json_exclusive(audit / "ERROR.json", {
                "schema": protocol["supervisor_error"],
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "killpg_signals": kill_signals,
                "reap_error": reap_error,
                "submission_authorized": False,
            })
        except BaseException:
            pass

        raise


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="e27_prior_score_v2")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate")
    p_gen.add_argument("--plan", type=Path, required=True)
    p_gen.add_argument("--plan-sha", required=True)

    p_child = sub.add_parser("score-child")
    p_child.add_argument("--plan", type=Path, required=True)
    p_child.add_argument("--plan-sha", required=True)
    p_child.add_argument("--pregen-sha", required=True)
    p_child.add_argument("--output", type=Path, required=True)

    p_score = sub.add_parser("score")
    p_score.add_argument("--plan", type=Path, required=True)
    p_score.add_argument("--plan-sha", required=True)
    p_score.add_argument("--pregen-sha", required=True)
    p_score.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "generate":
            result = run_registered_generation(args.plan, args.plan_sha)
        elif args.command == "score-child":
            result = run_score_child(args.plan, args.plan_sha,
                                     args.pregen_sha, args.output)
        else:
            result = supervise_score(args.plan, args.plan_sha,
                                     args.pregen_sha, args.output)
    except Exception as exc:
        print(json.dumps({"status": "ERROR",
                          "error_type": type(exc).__name__,
                          "submission_authorized": False}, sort_keys=True),
              file=sys.stderr)
        return 1

    print(json.dumps({"status": result["status"],
                      "submission_authorized": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
