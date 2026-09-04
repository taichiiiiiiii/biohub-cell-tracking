from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import biohub.st_r3_prerequisites as sut
from scripts.st_r3_prerequisite import _parser

HEADER = "id,dataset,row_type,node_id,t,z,y,x,source_id,target_id\n"
SUBMISSION = (
    HEADER + "0,fixture,node,10,0,1,2,3,,\n" + "1,fixture,node,11,1,1,2,4,,\n" + "2,fixture,edge,,,,,,10,11\n"
).encode()


def _run(cwd: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _records(path: Path) -> list[dict[str, object]]:
    records = []
    files = (item for item in path.rglob("*") if item.is_file())
    for item in sorted(files, key=lambda item: item.relative_to(path).as_posix().encode()):
        raw = item.read_bytes()
        records.append(
            {
                "path": item.relative_to(path).as_posix(),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return records


def _tree_pin(repo: Path, relative: str, roots: tuple[str, ...]) -> sut.TreePin:
    records = _records(repo / relative)
    root_digests = tuple(sut._tree_digest(_records(repo / relative / root)) for root in roots)
    return sut.TreePin(
        relative,
        roots,
        len(records),
        sum(int(item["bytes"]) for item in records),
        sut._tree_digest(records),
        root_digests,
    )


def _file_pin(repo: Path, relative: str) -> sut.FilePin:
    raw = (repo / relative).read_bytes()
    return sut.FilePin(relative, hashlib.sha256(raw).hexdigest(), len(raw))


def _stats(kind: str, *, candidate: bool, steal: int = 0) -> bytes:
    if kind == "e23":
        fields = [
            "dataset",
            "raw_nodes",
            "nodes",
            "predict_minutes_total",
            "experiment_tag",
            "safe_division_candidates",
            "safe_division_geometric_candidates",
            "safe_divisions_added",
            "safe_division_skipped_cap",
            "safe_division_mutual_nn_rejected",
            "safe_division_divergence_rejected",
            "deepcenter_gap_bypassed_observed_node",
        ]
        values = ["fixture", "2", "2", "1.0", "ref", "0", "9", "0", "0", "8", "7", "0"]
        if candidate:
            fields.extend(
                [
                    "centroid_refine_examined",
                    "centroid_refine_moved",
                    "centroid_refine_no_signal",
                    "centroid_refine_rejected_shift",
                    "steal_twin_fixture",
                ]
            )
            values.extend(["2", "2", "0", "0", str(steal)])
    else:
        fields = [
            "dataset",
            "raw_nodes",
            "predict_minutes_total",
            "experiment_tag",
            "deepcenter_gap_bypassed_synthetic_node",
        ]
        values = ["fixture", "2", "1.0", "ref", "5"]
        if candidate:
            fields.extend(
                [
                    "centroid_refine_examined",
                    "centroid_refine_moved",
                    "centroid_refine_no_signal",
                    "centroid_refine_rejected_shift",
                    "deepcenter_gap_bypassed_observed_node",
                    "safe_division_geometric_candidates",
                    "safe_division_mutual_nn_rejected",
                    "safe_division_divergence_rejected",
                    "steal_twin_fixture",
                ]
            )
            values.extend(["0", "0", "0", "0", "0", "0", "0", "0", str(steal)])
    return (",".join(fields) + "\n" + ",".join(values) + "\n").encode()


@dataclasses.dataclass
class Case:
    repo: Path
    profile: sut.Profile
    run: Path

    @property
    def receipt(self) -> Path:
        return self.run / self.profile.receipt_name


def _case(tmp_path: Path, kind: str = "e23", *, execute_run: bool = True, runner_exit: int = 0) -> Case:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _run(repo, "git", "init", "-q")
    _run(repo, "git", "config", "user.email", "fixture@example.invalid")
    _run(repo, "git", "config", "user.name", "Fixture")
    _write(repo / ".gitignore", b"runs/\n")
    _write(repo / "source.py", b"SOURCE = 'fixed'\n")
    (repo / "source-link").symlink_to("source.py")
    _write(repo / "tools/env", b'#!/bin/sh\nexec /usr/bin/env "$@"\n')
    fake_uv = b"""#!/bin/sh
mode=''
out=''
stats=''
score=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    scripts/postproc_geffs.py) mode='postproc' ;;
    scripts/local_eval.py) mode='score' ;;
    --out) shift; out="$1" ;;
    --run-stats) shift; stats="$1" ;;
    --json) shift; score="$1" ;;
  esac
  shift
done
if [ "$mode" = postproc ]; then
  if [ -f refs/force_fail ]; then echo 'controlled failure'; exit 9; fi
  /bin/cp refs/submission.csv "$out"
  /bin/cp refs/candidate_stats.csv "$stats"
  echo 'completed safely'
  exit 0
fi
if [ "$mode" = score ]; then
  /bin/cp refs/score.json "$score"
  echo 'score completed safely'
  exit 0
fi
exit 97
"""
    _write(repo / "tools/uv", fake_uv)
    (repo / "tools/env").chmod(0o755)
    (repo / "tools/uv").chmod(0o755)

    official = repo / "official"
    official.mkdir()
    _run(official, "git", "init", "-q")
    _run(official, "git", "config", "user.email", "fixture@example.invalid")
    _run(official, "git", "config", "user.name", "Fixture")
    _write(official / "metric.py", b"VALUE = 1\n")
    _write(official / "unlisted.py", b"UNLISTED = True\n")
    _run(official, "git", "add", "metric.py", "unlisted.py")
    _run(official, "git", "commit", "-qm", "official")
    official_oid = _run(official, "git", "rev-parse", "HEAD")

    _write(repo / "data/raw/fixture.geff/zarr.json", b"raw\n")
    _write(repo / "data/images/fixture.zarr/zarr.json", b"image\n")
    _write(repo / "data/gt/fixture.geff/zarr.json", b"gt\n")
    _write(repo / "refs/submission.csv", SUBMISSION)
    reference_stats = _stats(kind, candidate=False)
    _write(repo / "refs/run_stats.csv", reference_stats)
    _write(repo / "refs/candidate_stats.csv", _stats(kind, candidate=True))
    _write(repo / "refs/score.json", b'{"score":1}\n')
    _write(repo / "refs/fixed.bin", b"fixed reference\n")
    if runner_exit:
        _write(repo / "refs/force_fail", str(runner_exit).encode())
    if kind == "e23":
        import torch

        checkpoint = {"epoch": 2, "model_state": {f"weight_{index}": torch.tensor(index) for index in range(50)}}
        torch.save(checkpoint, repo / "refs/checkpoint.pt")
        checkpoint_pin = _file_pin(repo, "refs/checkpoint.pt")
        manifest = {
            "model": {
                "best_checkpoint": {
                    "path": "checkpoint.pt",
                    "bytes": checkpoint_pin.bytes,
                    "sha256": checkpoint_pin.sha256,
                }
            }
        }
        _write(repo / "refs/manifest.json", sut.canonical_json(manifest))

    raw = _tree_pin(repo, "data/raw", ("fixture.geff",))
    images = _tree_pin(repo, "data/images", ("fixture.zarr",)) if kind == "e23" else None
    gt = _tree_pin(repo, "data/gt/fixture.geff", ())
    base = sut.Profile(
        kind=kind,
        receipt_schema=sut.E23_SCHEMA if kind == "e23" else sut.BASE1_SCHEMA,
        receipt_name="E23_PARITY_RECEIPT.json" if kind == "e23" else "BASE1_NON_REGRESSION_RECEIPT.json",
        run_parent=f"runs/{kind}",
        datasets=("fixture",),
        raw=raw,
        images=images,
        gt_roots=(gt,) if kind == "e23" else (),
        references=(_file_pin(repo, "refs/fixed.bin"),) if kind == "e23" else (),
        reference_submission=_file_pin(repo, "refs/submission.csv"),
        reference_stats=_file_pin(repo, "refs/run_stats.csv"),
        reference_score=_file_pin(repo, "refs/score.json") if kind == "e23" else None,
        submission_sha256=hashlib.sha256(SUBMISSION).hexdigest(),
        submission_rows=3,
        graph_sha256=None,
        exact_graph_sha256=None,
        graph_counts=(("fixture", 3, 2, 1, 0),),
        deepcenter_manifest=_file_pin(repo, "refs/manifest.json") if kind == "e23" else None,
        deepcenter_checkpoint=_file_pin(repo, "refs/checkpoint.pt") if kind == "e23" else None,
        source_paths=("source.py",),
        official_paths=("official/metric.py",),
        official_oid=official_oid,
        steal_fields=("steal_twin_fixture",),
        launcher_env_path="tools/env",
        uv_path="tools/uv",
        test_only=True,
    )
    graph = sut._graph_evidence(SUBMISSION, base)
    profile = dataclasses.replace(
        base,
        graph_sha256=str(graph["legacy_parity_sha256"]),
        exact_graph_sha256=str(graph["exact_typed_sha256"]),
    )

    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "fixture")
    (repo / profile.run_parent).mkdir(parents=True)
    run = repo / profile.run_parent / "20260904T010203Z_abcdef0"
    sut._prepare(kind, run, repo, profile=profile, _test_only=True)
    expected_prepared = {"RUN_SPEC.json", "EMPTY_IMAGE_VIEW"} if kind == "base1" else {"RUN_SPEC.json"}
    assert {item.name for item in run.iterdir()} == expected_prepared
    if execute_run:
        result = sut._execute(kind, run, repo, profile=profile, _test_only=True)
        assert result["status"] == ("FAIL" if runner_exit else "PASS")
    return Case(repo, profile, run)


@pytest.mark.parametrize("kind", ["e23", "base1"])
def test_prepare_seal_verify_happy_path(tmp_path: Path, kind: str) -> None:
    case = _case(tmp_path, kind)
    result = sut._seal(kind, case.run, case.repo, profile=case.profile, _test_only=True)
    opaque = sut._validate_test_receipt(case.receipt, kind, case.repo, case.profile)

    assert result["status"] == "PASS"
    assert case.receipt.stat().st_mode & 0o777 == 0o444
    assert opaque == {
        "path": case.receipt.relative_to(case.repo).as_posix(),
        "bytes": case.receipt.stat().st_size,
        "sha256": hashlib.sha256(case.receipt.read_bytes()).hexdigest(),
        "verdict": "PASS",
        "schema_version": case.profile.receipt_schema,
    }
    assert "inputs" not in opaque and "datasets" not in opaque


def test_execution_receipt_records_exact_direct_children(tmp_path: Path) -> None:
    case = _case(tmp_path)
    execution = json.loads((case.run / sut.EXECUTION_NAME).read_bytes())
    spec = json.loads((case.run / "RUN_SPEC.json").read_bytes())
    assert execution["status"] == "PASS"
    assert execution["failure"] is None
    assert execution["source"]["official"]["gitlink_oid"] == execution["source"]["official"]["checked_out_head"]
    assert execution["source"]["deepcenter"]["semantic"] == {
        "epoch": 2,
        "model_state_entries": 50,
        "weights_only": True,
    }
    assert [record["phase"] for record in execution["commands"]] == ["postproc", "score"]
    for record, key in zip(execution["commands"], ("postproc_argv", "score_argv"), strict=True):
        assert record["argv"] == spec["command"][key]
        assert record["environment"] == spec["command"]["environment"]
        assert record["cwd"] == "."
        assert record["pid"] > 0 and record["exit_code"] == 0
        assert record["process_group"] == record["pid"]
        assert record["termination_signal"] is None and record["interruption"] is None


def test_copied_outputs_without_execution_receipt_cannot_seal(tmp_path: Path) -> None:
    case = _case(tmp_path, execute_run=False)
    spec = json.loads((case.run / "RUN_SPEC.json").read_bytes())
    _write(
        case.run / "START_MARKER.txt",
        f"code_sha={spec['source']['commit']}\nstarted_utc={spec['created_utc']}\n".encode(),
    )
    _write(case.run / "postproc.log", b"completed safely\n")
    _write(case.run / "submission.csv", (case.repo / "refs/submission.csv").read_bytes())
    _write(case.run / "run_stats.csv", (case.repo / "refs/candidate_stats.csv").read_bytes())
    _write(case.run / "official_score.json", (case.repo / "refs/score.json").read_bytes())
    with pytest.raises(sut.PrerequisiteError):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)


def test_nonzero_execution_retains_fail_receipt_and_never_seals(tmp_path: Path) -> None:
    case = _case(tmp_path, runner_exit=9)
    execution = json.loads((case.run / sut.EXECUTION_NAME).read_bytes())
    assert execution["status"] == "FAIL"
    assert execution["failure"] == {"phase": "postproc", "reason": "NONZERO_EXIT"}
    assert execution["commands"][0]["exit_code"] == 9
    assert set(execution["artifacts"]) == {"START_MARKER.txt", "postproc.log"}
    with pytest.raises(sut.PrerequisiteError):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)


def test_process_group_absence_ambiguity_never_commits_execution_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, execute_run=False)
    real_wait = subprocess.Popen.wait
    injected = False

    def interrupt_once(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        nonlocal injected
        if timeout is None and not injected and process.args[0] == case.profile.launcher_env_path:
            injected = True
            raise KeyboardInterrupt
        return real_wait(process, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupt_once)
    monkeypatch.setattr(sut, "_group_exists", lambda _group: True)
    monkeypatch.setattr(sut, "_TERM_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(sut, "_KILL_GRACE_SECONDS", 0.01)
    with pytest.raises(sut.PublicationAmbiguityError, match="process-group"):
        sut._execute("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    assert not (case.run / sut.EXECUTION_NAME).exists()


def test_interrupted_execution_records_command_and_cannot_seal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path, execute_run=False)
    real_wait = subprocess.Popen.wait
    injected = False

    def interrupt_once(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        nonlocal injected
        if timeout is None and not injected and process.args[0] == case.profile.launcher_env_path:
            injected = True
            raise KeyboardInterrupt
        return real_wait(process, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupt_once)
    result = sut._execute("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    assert result["status"] == "FAIL"
    execution = json.loads((case.run / sut.EXECUTION_NAME).read_bytes())
    assert execution["failure"] == {
        "phase": "postproc",
        "reason": "INTERRUPTED",
        "exception": "KeyboardInterrupt",
    }
    command = execution["commands"][0]
    assert command["pid"] == command["process_group"]
    assert command["interruption"]["exception"] == "KeyboardInterrupt"
    assert command["interruption"]["sigterm_sent"] is True
    assert command["exit_code"] is None
    assert command["termination_signal"] == 15
    with pytest.raises(sut.PrerequisiteError):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)


def test_interrupt_kills_descendant_process_group_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes = tmp_path / "descendant-writes.txt"
    descendant = (
        "import pathlib,signal,sys,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "p=pathlib.Path(sys.argv[1]);"
        "[(p.open('ab').write(b'x'),time.sleep(.02)) for _ in range(500)]"
    )
    parent = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{descendant!r},sys.argv[1]],close_fds=True);"
        "time.sleep(30)"
    )
    log = tmp_path / "child.log"
    log_fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    real_wait = subprocess.Popen.wait
    injected = False

    def interrupt_after_spawn(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        nonlocal injected
        if timeout is None and not injected:
            injected = True
            time.sleep(0.3)
            raise KeyboardInterrupt
        return real_wait(process, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupt_after_spawn)
    try:
        with pytest.raises(sut._ChildInterrupted) as caught:
            sut._run_child([sys.executable, "-c", parent, str(writes)], tmp_path, log_fd, "test", {})
    finally:
        os.close(log_fd)
    record = caught.value.record
    assert record["interruption"]["sigterm_sent"] is True
    assert record["interruption"]["sigkill_sent"] is True
    assert record["interruption"]["group_remaining_after_shutdown"] is False
    assert record["interruption"]["cleanup_errors"] == []
    before = writes.stat().st_size
    time.sleep(0.2)
    assert writes.stat().st_size == before


def test_forged_execution_receipt_fails_independent_seal(tmp_path: Path) -> None:
    case = _case(tmp_path)
    path = case.run / sut.EXECUTION_NAME
    value = json.loads(path.read_bytes())
    value["commands"][0]["argv"].append("--forged")
    path.chmod(0o644)
    path.write_bytes(sut.canonical_json(value))
    with pytest.raises(sut.PrerequisiteError, match="execution"):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)


@pytest.mark.parametrize("action", ["prepare", "execute", "seal"])
def test_publication_has_no_fallible_return_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    case = _case(tmp_path, execute_run=action == "seal")
    real_publish = sut._publish
    real_hashlib = sut.hashlib
    committed = False

    def publish_then_arm(directory: Path, name: str, raw: bytes) -> None:
        nonlocal committed
        real_publish(directory, name, raw)
        committed = True

    def reject_postcommit_hash(*args: object, **kwargs: object) -> object:
        if committed:
            raise AssertionError("fallible hash after commit")
        return real_hashlib.sha256(*args, **kwargs)

    class GuardedHashlib:
        sha1 = staticmethod(real_hashlib.sha1)
        sha256 = staticmethod(reject_postcommit_hash)

    monkeypatch.setattr(sut, "_publish", publish_then_arm)
    monkeypatch.setattr(sut, "hashlib", GuardedHashlib)
    if action == "prepare":
        profile = dataclasses.replace(case.profile, run_parent="fresh/postcommit")
        run = case.repo / profile.run_parent / "20260904T111213Z_1234567"
        result = sut._prepare("e23", run, case.repo, profile=profile, _test_only=True)
        published = run / "RUN_SPEC.json"
    elif action == "execute":
        result = sut._execute("e23", case.run, case.repo, profile=case.profile, _test_only=True)
        published = case.run / sut.EXECUTION_NAME
    else:
        result = sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)
        published = case.receipt
    assert committed is True and published.is_file()
    assert result["sha256"]


def test_receipt_forgery_and_closed_schema_fail(tmp_path: Path) -> None:
    case = _case(tmp_path)
    sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    value = json.loads(case.receipt.read_bytes())
    value["checks"] = {"graph": True, "telemetry": True}
    case.receipt.chmod(0o644)
    case.receipt.write_bytes(sut.canonical_json(value))
    with pytest.raises(sut.PrerequisiteError, match="recompute"):
        sut._validate_test_receipt(case.receipt, "e23", case.repo, case.profile)


def test_hash_updated_artifact_forgery_fails_recomputation(tmp_path: Path) -> None:
    case = _case(tmp_path)
    sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    value = json.loads(case.receipt.read_bytes())
    forged = (case.run / "run_stats.csv").read_bytes().replace(b"fixture,2,", b"fixture,3,")
    (case.run / "run_stats.csv").write_bytes(forged)
    value["outputs"]["run_stats"] = {
        "path": "run_stats.csv",
        "bytes": len(forged),
        "sha256": hashlib.sha256(forged).hexdigest(),
    }
    case.receipt.chmod(0o644)
    case.receipt.write_bytes(sut.canonical_json(value))
    with pytest.raises(sut.PrerequisiteError):
        sut._validate_test_receipt(case.receipt, "e23", case.repo, case.profile)

    value["unexpected"] = True
    case.receipt.write_bytes(sut.canonical_json(value))
    with pytest.raises(sut.PrerequisiteError, match="closed receipt"):
        sut._validate_test_receipt(case.receipt, "e23", case.repo, case.profile)


@pytest.mark.parametrize("raw", [b'{"x":NaN}\n', b'{"x":1e999}\n', b'{"x":1,"x":2}\n'])
def test_strict_json_rejects_nonfinite_and_duplicate(raw: bytes) -> None:
    with pytest.raises(sut.PrerequisiteError):
        sut.strict_json(raw)


def test_graph_rejects_schema_duplicate_dangling_and_nonfinite(tmp_path: Path) -> None:
    case = _case(tmp_path)
    bad_values = [
        SUBMISSION.replace(b"id,dataset", b"wrong,dataset"),
        SUBMISSION.replace(b"11,1,1,2,4", b"10,1,1,2,4"),
        SUBMISSION.replace(b",10,11\n", b",10,99\n"),
        SUBMISSION.replace(b",1,2,3,,", b",NaN,2,3,,"),
    ]
    for raw in bad_values:
        with pytest.raises(sut.PrerequisiteError):
            sut._graph_evidence(raw, case.profile)


def test_exact_graph_preserves_ids_while_legacy_parity_normalizes_them(tmp_path: Path) -> None:
    case = _case(tmp_path)
    unpinned = dataclasses.replace(case.profile, graph_sha256=None, exact_graph_sha256=None)
    original = sut._graph_evidence(SUBMISSION, unpinned)
    renumbered = SUBMISSION.replace(b"node,10,", b"node,20,").replace(b",10,11\n", b",20,11\n")
    changed = sut._graph_evidence(renumbered, unpinned)
    assert changed["legacy_parity_sha256"] == original["legacy_parity_sha256"]
    assert changed["exact_typed_sha256"] != original["exact_typed_sha256"]
    with pytest.raises(sut.PrerequisiteError, match="invalid integer"):
        sut._graph_evidence(SUBMISSION.replace(b"node,10,", b"node,10.0,"), unpinned)


def test_telemetry_requires_equality_truth_and_zero_fields(tmp_path: Path) -> None:
    case = _case(tmp_path)
    reference = (case.repo / "refs/run_stats.csv").read_bytes()
    with pytest.raises(sut.PrerequisiteError, match="nonzero disabled"):
        sut._stats_evidence(_stats("e23", candidate=True, steal=1), reference, case.profile)
    with pytest.raises(sut.PrerequisiteError, match="common telemetry drift"):
        sut._stats_evidence(
            _stats("e23", candidate=True).replace(b"fixture,2,", b"fixture,3,"), reference, case.profile
        )


def test_e23_frozen_reference_shape_lacks_new_centroid_but_candidate_requires_it(tmp_path: Path) -> None:
    case = _case(tmp_path)
    reference = (case.repo / "refs/run_stats.csv").read_bytes()
    candidate = (case.repo / "refs/candidate_stats.csv").read_bytes()
    assert b"centroid_refine_examined" not in reference.splitlines()[0]
    evidence = sut._stats_evidence(candidate, reference, case.profile)
    assert evidence["rows"] == 1
    missing = candidate.replace(b",centroid_refine_examined", b",removed_centroid_field")
    with pytest.raises(sut.PrerequisiteError, match="required fields missing"):
        sut._stats_evidence(missing, reference, case.profile)


@pytest.mark.parametrize(
    "log",
    [b"Traceback (most recent call last)\n", b"api_key=do-not-record\n", b"missing DeepCenter checkpoint\n"],
)
def test_log_rejects_warning_and_secret(log: bytes) -> None:
    with pytest.raises(sut.PrerequisiteError):
        sut._check_log(log, "e23")


def test_seal_rejects_ref_source_and_artifact_drift(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case.repo / "refs/submission.csv").write_bytes(SUBMISSION + b"\n")
    with pytest.raises(sut.PrerequisiteError):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)

    case = _case(tmp_path / "second")
    (case.run / "extra.txt").write_text("unexpected")
    with pytest.raises(sut.PrerequisiteError, match="membership"):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)


def test_linked_worktree_style_gitfile_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    os.rename(case.repo / ".git", case.repo / ".git-real")
    (case.repo / ".git").write_text("gitdir: .git-real\n")
    with pytest.raises(sut.PrerequisiteError, match="real .git directory"):
        sut._source_snapshot(case.repo, case.profile)


def test_symlink_and_hardlink_artifacts_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    target = case.run / "target"
    target.write_text("x")
    (case.run / "submission.csv").unlink()
    (case.run / "submission.csv").symlink_to(target.name)
    with pytest.raises(sut.PrerequisiteError):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)


def test_input_tree_symlink_and_nonportable_member_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    raw_file = case.repo / "data/raw/fixture.geff/zarr.json"
    raw_file.unlink()
    raw_file.symlink_to(case.repo / "refs/fixed.bin")
    with pytest.raises(sut.PrerequisiteError, match="symlink"):
        sut._tree_evidence(case.repo, case.profile.raw)

    case = _case(tmp_path / "portable")
    bad = case.repo / "data/raw/fixture.geff/bad\\name"
    bad.write_text("bad")
    fd = os.open(case.repo / "data/raw/fixture.geff", os.O_RDONLY)
    try:
        with pytest.raises(sut.PrerequisiteError, match="non-portable"):
            sut._walk(fd)
    finally:
        os.close(fd)


def test_casefold_collisions_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(sut.PrerequisiteError, match="casefold"):
        sut._reject_casefold_collisions(("Frame", "frame"), "fixture")
    tree = tmp_path / "case-sensitive"
    tree.mkdir()
    (tree / "Frame").write_text("one")
    (tree / "frame").write_text("two")
    if len(os.listdir(tree)) == 2:
        fd = os.open(tree, os.O_RDONLY)
        try:
            with pytest.raises(sut.PrerequisiteError, match="casefold"):
                sut._walk(fd)
        finally:
            os.close(fd)

    case = _case(tmp_path / "hard")
    (case.run / "submission.csv").unlink()
    os.link(case.repo / "refs/submission.csv", case.run / "submission.csv")
    with pytest.raises(sut.PrerequisiteError):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)


def test_no_clobber_receipt(tmp_path: Path) -> None:
    case = _case(tmp_path)
    sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    before = case.receipt.read_bytes()
    with pytest.raises(FileExistsError):
        sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    assert case.receipt.read_bytes() == before
    assert not list(case.run.glob(".*.tmp"))


def test_prepare_never_reuses_run_and_rolls_back_pre_spec_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path)
    with pytest.raises(FileExistsError):
        sut._prepare("e23", case.run, case.repo, profile=case.profile, _test_only=True)

    fresh = case.run.parent / "20260904T010203Z_1234567"
    monkeypatch.setattr(sut, "_source_snapshot", lambda *_: (_ for _ in ()).throw(sut.PrerequisiteError("boom")))
    with pytest.raises(sut.PrerequisiteError, match="boom"):
        sut._prepare("e23", fresh, case.repo, profile=case.profile, _test_only=True)
    assert not fresh.exists()


def test_prepare_creates_only_fixed_missing_parent_and_run_spec(tmp_path: Path) -> None:
    case = _case(tmp_path)
    profile = dataclasses.replace(case.profile, run_parent="fresh/parents/e23")
    fresh = case.repo / profile.run_parent / "20260904T030405Z_1234567"
    result = sut._prepare("e23", fresh, case.repo, profile=profile, _test_only=True)
    raw = (fresh / "RUN_SPEC.json").read_bytes()
    assert result == {
        "status": "PREPARED",
        "run_spec": "RUN_SPEC.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert [item.name for item in fresh.iterdir()] == ["RUN_SPEC.json"]


def test_base1_prepare_owns_real_empty_image_view_and_rolls_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path, "base1", execute_run=False)
    empty = case.run / "EMPTY_IMAGE_VIEW"
    assert empty.is_dir() and not empty.is_symlink() and not list(empty.iterdir())
    spec = json.loads((case.run / "RUN_SPEC.json").read_bytes())
    assert "EMPTY_IMAGE_VIEW/" in spec["artifacts"]

    profile = dataclasses.replace(case.profile, run_parent="fresh/base1")
    fresh = case.repo / profile.run_parent / "20260904T040506Z_1234567"
    monkeypatch.setattr(sut, "_source_snapshot", lambda *_: (_ for _ in ()).throw(sut.PrerequisiteError("boom")))
    with pytest.raises(sut.PrerequisiteError, match="boom"):
        sut._prepare("base1", fresh, case.repo, profile=profile, _test_only=True)
    assert not fresh.exists()


def test_prepare_parent_fsync_failure_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    fresh = case.run.parent / "20260904T020304Z_1234567"
    real_fsync = os.fsync
    calls = 0

    def fail_creation(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EIO, "injected parent fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_creation)
    with pytest.raises(OSError, match="injected parent fsync"):
        sut._prepare("e23", fresh, case.repo, profile=case.profile, _test_only=True)
    assert not fresh.exists()
    assert calls == 2


def test_command_is_sanitized_direct_exec_and_ambient_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path)
    monkeypatch.setenv("BIOHUB_DEEPCENTER_CHECKPOINT", "attacker")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "attacker")
    command = sut._command(case.profile, case.repo, case.run)
    argv = command["postproc_argv"]
    environment = command["environment"]

    assert argv[:2] == [case.profile.launcher_env_path, "-i"]
    assert argv[2 : 2 + len(environment)] == [f"{key}={value}" for key, value in sorted(environment.items())]
    assert argv[2 + len(environment)] == case.profile.uv_path
    assert "--offline" in argv and "--no-sync" in argv and "--frozen" in argv
    assert not any("BIOHUB" in key or "SECRET" in key or "TOKEN" in key for key in environment)
    assert command["execution"]["postproc_combined_output"] == {
        "create": "exclusive",
        "path": "postproc.log",
    }


def test_source_git_checks_ignore_ambient_git_redirection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(tmp_path)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "attacker.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "attacker-tree"))
    snapshot = sut._source_snapshot(case.repo, case.profile)
    assert snapshot["commit"] == json.loads((case.run / "RUN_SPEC.json").read_bytes())["source"]["commit"]


def test_untracked_source_and_official_files_are_rejected(tmp_path: Path) -> None:
    case = _case(tmp_path)
    (case.repo / "sitecustomize.py").write_text("raise RuntimeError('injected')\n")
    with pytest.raises(sut.PrerequisiteError, match="completely clean"):
        sut._source_snapshot(case.repo, case.profile)

    (case.repo / "sitecustomize.py").unlink()
    (case.repo / "official/sitecustomize.py").write_text("raise RuntimeError('injected')\n")
    with pytest.raises(sut.PrerequisiteError):
        sut._source_snapshot(case.repo, case.profile)


def test_source_and_official_index_flags_are_rejected(tmp_path: Path) -> None:
    source = _case(tmp_path / "source")
    _run(source.repo, "git", "update-index", "--assume-unchanged", "source.py")
    with pytest.raises(sut.PrerequisiteError, match="index flags"):
        sut._source_snapshot(source.repo, source.profile)

    official = _case(tmp_path / "official")
    _run(official.repo / "official", "git", "update-index", "--skip-worktree", "metric.py")
    with pytest.raises(sut.PrerequisiteError, match="index flags"):
        sut._source_snapshot(official.repo, official.profile)


def test_unlisted_tracked_source_and_official_index_flags_are_rejected(tmp_path: Path) -> None:
    source = _case(tmp_path / "source")
    assert "refs/fixed.bin" not in source.profile.source_paths
    _run(source.repo, "git", "update-index", "--skip-worktree", "refs/fixed.bin")
    _write(source.repo / "refs/fixed.bin", b"hidden source modification\n")
    assert _run(source.repo, "git", "status", "--porcelain", "--untracked-files=all") == ""
    with pytest.raises(sut.PrerequisiteError, match="index flags"):
        sut._source_snapshot(source.repo, source.profile)

    official = _case(tmp_path / "official")
    assert "official/unlisted.py" not in official.profile.official_paths
    _run(official.repo / "official", "git", "update-index", "--assume-unchanged", "unlisted.py")
    _write(official.repo / "official/unlisted.py", b"hidden official modification\n")
    assert _run(official.repo / "official", "git", "status", "--porcelain", "--untracked-files=all") == ""
    with pytest.raises(sut.PrerequisiteError, match="index flags"):
        sut._source_snapshot(official.repo, official.profile)


def test_source_snapshot_binds_descriptor_stable_head_blobs(tmp_path: Path) -> None:
    case = _case(tmp_path)
    snapshot = sut._source_snapshot(case.repo, case.profile)
    source = snapshot["files"][0]
    official = snapshot["official"]["files"][0]
    assert source["path"] == "source.py"
    assert source["head_mode"] == "100644" and source["index_flags"] == "0"
    assert source["head_blob_oid"] == _run(case.repo, "git", "rev-parse", "HEAD:source.py")
    assert official["path"] == "official/metric.py"
    assert official["head_blob_oid"] == _run(case.repo / "official", "git", "rev-parse", "HEAD:metric.py")


def _fd_count() -> int:
    return len(os.listdir("/dev/fd"))


@pytest.mark.parametrize("fault", ["stat", "fstat"])
def test_open_relative_dir_closes_new_fd_on_identity_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    root_fd = os.open(tmp_path, os.O_RDONLY)
    before = _fd_count()
    if fault == "stat":
        real_stat = os.stat

        def fail_stat(path: os.PathLike[str] | str | int, *args: object, **kwargs: object) -> os.stat_result:
            if path == "child":
                raise OSError(errno.EIO, "injected stat")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", fail_stat)
    else:
        monkeypatch.setattr(os, "fstat", lambda _fd: (_ for _ in ()).throw(OSError(errno.EIO, "injected fstat")))
    try:
        with pytest.raises(OSError, match=f"injected {fault}"):
            sut._open_relative_dir(root_fd, ("child",), "child")
        assert _fd_count() == before
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("fault", ["stat", "fstat"])
def test_ensure_repo_directory_closes_new_fd_on_identity_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    (tmp_path / "child").mkdir()
    before = _fd_count()
    if fault == "stat":
        real_stat = os.stat

        def fail_stat(path: os.PathLike[str] | str | int, *args: object, **kwargs: object) -> os.stat_result:
            if path == "child":
                raise OSError(errno.EIO, "injected stat")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", fail_stat)
    else:
        real_fstat = os.fstat
        calls = 0

        def fail_child_fstat(fd: int) -> os.stat_result:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(errno.EIO, "injected fstat")
            return real_fstat(fd)

        monkeypatch.setattr(os, "fstat", fail_child_fstat)
    with pytest.raises(OSError, match=f"injected {fault}"):
        sut._ensure_repo_directory(tmp_path, "child")
    assert _fd_count() == before


def test_runtime_and_expected_source_drift_fail(tmp_path: Path) -> None:
    case = _case(tmp_path)
    sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    with pytest.raises(sut.PrerequisiteError, match="expected source"):
        sut._validate_test_receipt(case.receipt, "e23", case.repo, case.profile, expected_source={})

    (case.repo / "tools/uv").chmod(0o700)
    with pytest.raises(sut.PrerequisiteError):
        sut._validate_test_receipt(case.receipt, "e23", case.repo, case.profile)


@pytest.mark.parametrize("epoch,state_count", [(1, 50), (2, 49)])
def test_deepcenter_semantic_epoch_and_state_count_are_exact(tmp_path: Path, epoch: int, state_count: int) -> None:
    import torch

    case = _case(tmp_path)
    checkpoint_path = case.repo / "refs/checkpoint.pt"
    torch.save(
        {"epoch": epoch, "model_state": {f"weight_{index}": torch.tensor(index) for index in range(state_count)}},
        checkpoint_path,
    )
    checkpoint = _file_pin(case.repo, "refs/checkpoint.pt")
    manifest_value = {
        "model": {
            "best_checkpoint": {
                "path": "checkpoint.pt",
                "bytes": checkpoint.bytes,
                "sha256": checkpoint.sha256,
            }
        }
    }
    _write(case.repo / "refs/manifest.json", sut.canonical_json(manifest_value))
    profile = dataclasses.replace(
        case.profile,
        deepcenter_manifest=_file_pin(case.repo, "refs/manifest.json"),
        deepcenter_checkpoint=checkpoint,
    )
    with pytest.raises(sut.PrerequisiteError, match="semantic identity"):
        sut._deepcenter_evidence(case.repo, profile)


def test_deepcenter_manifest_path_bytes_and_sha_are_exact(tmp_path: Path) -> None:
    case = _case(tmp_path)
    checkpoint = case.profile.deepcenter_checkpoint
    assert checkpoint is not None
    for claim in (
        {"path": "other.pt", "bytes": checkpoint.bytes, "sha256": checkpoint.sha256},
        {"path": "checkpoint.pt", "bytes": int(checkpoint.bytes or 0) + 1, "sha256": checkpoint.sha256},
        {"path": "checkpoint.pt", "bytes": checkpoint.bytes, "sha256": "0" * 64},
    ):
        _write(case.repo / "refs/manifest.json", sut.canonical_json({"model": {"best_checkpoint": claim}}))
        profile = dataclasses.replace(
            case.profile,
            deepcenter_manifest=_file_pin(case.repo, "refs/manifest.json"),
        )
        with pytest.raises(sut.PrerequisiteError, match="DeepCenter manifest"):
            sut._deepcenter_evidence(case.repo, profile)


def test_publish_final_dir_fsync_failure_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "out"
    directory.mkdir()
    real_fsync = os.fsync
    calls = 0

    def fail_final(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EIO, "injected final fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_final)
    with pytest.raises(OSError, match="injected final fsync"):
        sut._publish(directory, "READY.json", b"{}\n")
    assert not (directory / "READY.json").exists()
    assert not list(directory.iterdir())
    assert calls == 3


def test_publish_file_fsync_failure_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "out"
    directory.mkdir()
    real_fsync = os.fsync
    calls = 0

    def fail_file(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EIO, "injected file fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_file)
    with pytest.raises(OSError, match="injected file fsync"):
        sut._publish(directory, "READY.json", b"{}\n")
    assert not (directory / "READY.json").exists()
    assert not list(directory.iterdir())
    assert calls == 2


def test_publish_rollback_fsync_failure_is_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "out"
    directory.mkdir()
    real_fsync = os.fsync
    calls = 0

    def fail_dirs(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError(errno.EIO, "injected directory fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_dirs)
    with pytest.raises(sut.PublicationAmbiguityError, match="rollback fsync"):
        sut._publish(directory, "READY.json", b"{}\n")
    assert not (directory / "READY.json").exists()


def test_stable_read_detects_path_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "read"
    directory.mkdir()
    target = directory / "value.bin"
    target.write_bytes(b"original")
    parent_fd = os.open(directory, os.O_RDONLY)
    real_read = os.read
    swapped = False

    def swapping_read(fd: int, size: int) -> bytes:
        nonlocal swapped
        value = real_read(fd, size)
        if value and not swapped:
            swapped = True
            target.unlink()
            target.write_bytes(b"replaced")
        return value

    monkeypatch.setattr(os, "read", swapping_read)
    try:
        with pytest.raises(sut.PrerequisiteError, match="changed while reading"):
            sut._read_at(parent_fd, "value.bin", "value.bin")
    finally:
        os.close(parent_fd)


def test_stable_read_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    try:
        started = time.monotonic()
        with pytest.raises(sut.PrerequisiteError, match="unsafe file"):
            sut._read_at(parent_fd, "pipe", "pipe")
        assert time.monotonic() - started < 1
    finally:
        os.close(parent_fd)


def test_receipt_path_and_run_name_must_be_canonical(tmp_path: Path) -> None:
    case = _case(tmp_path)
    sut._seal("e23", case.run, case.repo, profile=case.profile, _test_only=True)
    aliased = case.run / "subdir" / ".." / case.profile.receipt_name
    with pytest.raises(sut.PrerequisiteError, match="canonical|direct child"):
        sut._validate_test_receipt(aliased, "e23", case.repo, case.profile)
    with pytest.raises(sut.PrerequisiteError, match="direct child"):
        sut._prepare(
            "e23",
            case.run.parent / "not portable!",
            case.repo,
            profile=case.profile,
            _test_only=True,
        )


@pytest.mark.parametrize(
    "name",
    [
        "attempt-001",
        "20260904T000000Z",
        "20260904T000000Z_ABCDEF0",
        "20260904T000000Z_123456",
        "20261340T000000Z_1234567",
        "junk/../20260904T000000Z_1234567",
    ],
)
def test_run_name_requires_exact_timestamp_and_nonce(tmp_path: Path, name: str) -> None:
    case = _case(tmp_path)
    with pytest.raises(sut.PrerequisiteError, match="direct child"):
        sut._validate_run_path(case.repo, case.run.parent / name, case.profile)


def test_production_cli_has_no_path_hash_or_profile_override() -> None:
    parser = _parser()
    with pytest.raises(sut.PrerequisiteError, match="unrecognized arguments"):
        parser.parse_args(
            [
                "prepare",
                "--kind",
                "e23",
                "--run-dir",
                "outputs/local/st_r3_prerequisites/e23/20260904T000000Z_1234567",
                "--profile",
                "forged",
            ]
        )


def test_production_profiles_are_closed_and_fully_ordered(tmp_path: Path) -> None:
    assert sut.PROFILES == {"e23": sut.E23_PROFILE, "base1": sut.BASE1_PROFILE}
    assert sut.E23_PROFILE.datasets == (
        "44b6_0113de3b",
        "44b6_0b24845f",
        "6bba_05b6850b",
        "6bba_05db0fb1",
    )
    assert sut.BASE1_PROFILE.datasets == (
        "44b6_12dfb391",
        "44b6_267148e4",
        "44b6_2a2eff9f",
        "44b6_341df25f",
    )
    assert sut.E23_PROFILE.official_oid == sut.OFFICIAL_OID
    assert sut.E23_PROFILE.raw == sut.TreePin(
        "outputs/kaggle/e22_bidir030_public4_raw/tracking_repo/predictions/unknown/unet_transformer/split_0",
        tuple(f"{item}.geff" for item in sut.PUBLIC_FOUR),
        132,
        1_583_021,
        "5fc5fb5e51d127612421970ed66f0ba4229f020940ed458dfdf0fa316f2e8bc1",
        (
            "a4151aad5042a93e3fce9a7f42a2c5b994e83137d2686049c60540e8f9d56fdb",
            "dfb6885f043250ec106658dcba2bd3d1da14fd02cc75a0bbbbcdc229cd817528",
            "881a827867dc142236db6b5558a331fdc2f26d07ca15c2e978e5ef8c01c6412f",
            "ceb3bd1512cc1482b3349c3d52c4db1a79333209f8f978028daa38183ccfc515",
        ),
    )
    assert sut.E23_PROFILE.images is not None
    assert (sut.E23_PROFILE.images.files, sut.E23_PROFILE.images.bytes, sut.E23_PROFILE.images.sha256) == (
        408,
        1_906_332_008,
        "0b9e6e060437104fb261b388f45eae494abcca59155b4bc9fc4fac24bedd9bbd",
    )
    assert sut.E23_PROFILE.graph_counts == (
        ("44b6_0113de3b", 50_253, 25_485, 24_768, 57),
        ("44b6_0b24845f", 38_558, 19_905, 18_653, 77),
        ("6bba_05b6850b", 12_085, 6_142, 5_943, 11),
        ("6bba_05db0fb1", 139_230, 70_675, 68_555, 118),
    )
    assert sut.E23_PROFILE.graph_sha256 == "7c71134d70413986f3e557c91b59db019260d27a93e438ba3770fd5c464338fd"
    assert sut.E23_PROFILE.exact_graph_sha256 == ("b6ea4e3a4967f42f4120b3abdc9a04eaf67c3f1a3a0a06739e8d009ee0355add")
    assert (
        sut.BASE1_PROFILE.raw.files,
        sut.BASE1_PROFILE.raw.bytes,
        sut.BASE1_PROFILE.raw.sha256,
        sut.BASE1_PROFILE.submission_sha256,
    ) == (
        132,
        1_448_288,
        "7148a3adabe187768a8ef8eb27009b6a27f96f6a079b8f274cd00587b9cadb42",
        "56b8fab98992bc5c6ed1dcaba32ad7116ebbf6c185a5fcc31ed39cc56fb992ab",
    )
    assert sut.BASE1_PROFILE.exact_graph_sha256 == ("802ea240bd70cfd8fc7192a4f1bcfd1c98982d6eedb7642311a8d8e6460fb9e3")
    repo = tmp_path / "repo"
    e23_run = repo / sut.E23_PROFILE.run_parent / "20260904T000000Z_1234567"
    base_run = repo / sut.BASE1_PROFILE.run_parent / "20260904T000000Z_1234567"
    e23_command = sut._command(sut.E23_PROFILE, repo, e23_run)
    base_command = sut._command(sut.BASE1_PROFILE, repo, base_run)
    assert e23_command["postproc_argv"][:2] == ["/usr/bin/env", "-i"]
    assert e23_command["postproc_argv"][-4:] == [
        "--out",
        "outputs/local/st_r3_prerequisites/e23/20260904T000000Z_1234567/submission.csv",
        "--run-stats",
        "outputs/local/st_r3_prerequisites/e23/20260904T000000Z_1234567/run_stats.csv",
    ]
    assert e23_command["score_argv"][-4:] == [
        "--gt-dir",
        "data/train",
        "--json",
        "outputs/local/st_r3_prerequisites/e23/20260904T000000Z_1234567/official_score.json",
    ]
    assert base_command["score_argv"] == []
    assert (
        "outputs/local/st_r3_prerequisites/base1/20260904T000000Z_1234567/EMPTY_IMAGE_VIEW"
        in base_command["postproc_argv"]
    )
    assert not sut.E23_PROFILE.test_only and not sut.BASE1_PROFILE.test_only
