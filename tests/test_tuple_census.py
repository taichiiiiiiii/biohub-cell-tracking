from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "tuple_census.py"
SPEC = importlib.util.spec_from_file_location("tuple_census_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
census = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = census
SPEC.loader.exec_module(census)


def _node(node_id: int, t: int, z: float, y: float, x: float) -> dict[str, object]:
    return {"node_id": node_id, "t": t, "z": z, "y": y, "x": x, "solution": True}


def _edge(source: int, target: int) -> dict[str, object]:
    return {"source_id": source, "target_id": target, "solution": True}


def _unit_config() -> object:
    return census.CensusConfig(scale_zyx_um=(1.0, 1.0, 1.0))


def test_parent_radius_is_inclusive_and_nextafter_outside_rejects() -> None:
    exact = [
        _node(1, 0, 0.0, 0.0, 0.0),
        _node(2, 1, 0.0, 0.0, 1.0),
        _node(3, 1, 0.0, 8.0, 0.0),
    ]
    result = census.census_rows("synthetic", exact, [_edge(1, 2)], _unit_config())
    assert result.one_child_parents == 1
    assert result.active_one_child_parents == 1
    assert result.candidate_tuples == 1

    outside = [dict(row) for row in exact]
    outside[2]["y"] = math.nextafter(8.0, math.inf)
    result = census.census_rows("synthetic", outside, [_edge(1, 2)], _unit_config())
    assert result.one_child_parents == 1
    assert result.active_one_child_parents == 0
    assert result.candidate_tuples == 0


def test_sister_radius_is_inclusive_and_nextafter_outside_rejects() -> None:
    exact = [
        _node(1, 0, 0.0, 0.0, 0.0),
        _node(2, 1, 0.0, -4.0, 0.0),
        _node(3, 1, 0.0, 7.0, 0.0),
    ]
    result = census.census_rows("synthetic", exact, [_edge(1, 2)], _unit_config())
    assert result.candidate_tuples == 1

    outside = [dict(row) for row in exact]
    outside[2]["y"] = -4.0 + math.nextafter(11.0, math.inf)
    result = census.census_rows("synthetic", outside, [_edge(1, 2)], _unit_config())
    assert result.candidate_tuples == 0


def test_row_order_and_candidate_order_do_not_change_counts() -> None:
    nodes = [
        _node(1, 0, 0.0, 0.0, 0.0),
        _node(2, 1, 0.0, 0.0, 1.0),
        _node(3, 1, 0.0, 2.0, 0.0),
        _node(4, 1, 0.0, 3.0, 0.0),
        _node(5, 0, 0.0, 20.0, 0.0),
        _node(6, 1, 0.0, 20.0, 1.0),
    ]
    edges = [_edge(1, 2), _edge(5, 6)]
    expected = census.census_rows("synthetic", nodes, edges, _unit_config())
    actual = census.census_rows("synthetic", list(reversed(nodes)), list(reversed(edges)), _unit_config())
    assert actual == expected
    assert actual.one_child_parents == 2
    assert actual.candidate_tuples == 2
    assert actual.max_candidates_per_parent == 2


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        ([_node(1, 0, 0, 0, 0), _node(1, 1, 0, 0, 0)], [], "duplicate node_id"),
        ([_node(1, 0, 0, 0, 0)], [_edge(1, 2)], "dangling edge"),
        ([_node(1, 0, 0, 0, 0), _node(2, 2, 0, 0, 0)], [_edge(1, 2)], "nonconsecutive edge"),
        (
            [_node(1, 0, 0, 0, 0), {**_node(2, 1, 0, 0, 0), "solution": False}],
            [_edge(1, 2)],
            "solution must be true",
        ),
    ],
)
def test_graph_contract_fails_closed(nodes, edges, message: str) -> None:
    with pytest.raises(census.CensusError, match=message):
        census.census_rows("synthetic", nodes, edges, _unit_config())


def _make_expected_root(repo: Path) -> Path:
    root = repo / census.FROZEN_RELATIVE_ROOT
    root.mkdir(parents=True)
    return root


def test_input_root_rejects_gt_image_public_dummy_and_arbitrary_paths(tmp_path: Path) -> None:
    expected = _make_expected_root(tmp_path)
    assert census.validate_frozen_input_root(tmp_path, expected) == expected
    prohibited = (
        tmp_path / "data" / "train",
        tmp_path / "data" / "test",
        tmp_path / "outputs" / "kaggle" / "e22_bidir030_public4_raw",
        tmp_path / "somewhere_else",
    )
    for path in prohibited:
        path.mkdir(parents=True)
        with pytest.raises(census.CensusError, match="prohibited input root"):
            census.validate_frozen_input_root(tmp_path, path)


def test_input_root_rejects_symlink_component(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked_repo = tmp_path / "linked_repo"
    linked_repo.symlink_to(real, target_is_directory=True)
    expected = linked_repo / census.FROZEN_RELATIVE_ROOT
    expected.mkdir(parents=True)
    with pytest.raises(census.CensusError, match="symlink or non-directory path component"):
        census.validate_frozen_input_root(linked_repo, expected)


def test_input_root_rejects_symlink_ancestor_above_repo_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    redirect = tmp_path / "redirect"
    redirect.symlink_to(real, target_is_directory=True)
    repo = redirect / "repo"
    expected = repo / census.FROZEN_RELATIVE_ROOT
    expected.mkdir(parents=True)

    with pytest.raises(census.CensusError, match="symlink or non-directory path component"):
        census.validate_frozen_input_root(repo, expected)


def test_output_path_rejects_protected_and_unscoped_repository_trees(tmp_path: Path) -> None:
    allowed = tmp_path / "outputs" / "local" / "tuple_census" / "receipt.json"
    assert census.validate_output_path(tmp_path, allowed) == allowed
    prohibited = (
        tmp_path / census.FROZEN_RELATIVE_ROOT / "receipt.json",
        tmp_path / "outputs" / "kaggle" / "receipt.json",
        tmp_path / "data" / "receipt.json",
        tmp_path / "official" / "receipt.json",
        tmp_path / ".git" / "receipt.json",
        tmp_path / "analysis" / "receipt.json",
    )
    for path in prohibited:
        with pytest.raises(census.CensusError, match="output path|repository-local output"):
            census.validate_output_path(tmp_path, path)


@pytest.mark.parametrize(
    "protected_relative",
    [
        census.FROZEN_RELATIVE_ROOT,
        Path("outputs/kaggle"),
        Path("data"),
        Path("official"),
        Path(".git"),
    ],
    ids=["frozen-input", "kaggle-output", "data", "official", "git"],
)
@pytest.mark.parametrize("redirect_inside_repo", [False, True], ids=["outside-repo", "inside-repo"])
def test_output_publication_rejects_symlinked_parent_redirect_to_protected_tree(
    tmp_path: Path,
    protected_relative: Path,
    redirect_inside_repo: bool,
) -> None:
    protected = tmp_path / protected_relative
    protected.mkdir(parents=True, exist_ok=True)
    sentinel = protected / "sentinel"
    sentinel.write_text("unchanged")
    if redirect_inside_repo:
        redirect = tmp_path / "outputs" / "local" / "tuple_census" / "redirect"
        redirect.parent.mkdir(parents=True)
    else:
        redirect = tmp_path.parent / f"{tmp_path.name}-outside-redirect"
    redirect.symlink_to(protected, target_is_directory=True)
    output = redirect / "receipt.json"
    validated = census.validate_output_path(tmp_path, output)

    with pytest.raises(census.CensusError, match="symlink or non-directory path component"):
        census._open_output_parent(validated.parent)

    assert sentinel.read_text() == "unchanged"
    assert sorted(path.name for path in protected.iterdir()) == ["sentinel"]


def test_canonical_stdout_cli_bytes_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(census, "run_census", lambda _repo: {"z": 1, "a": [2, 3]})
    assert census.main(["--repo-root", str(tmp_path)]) == 0
    captured = capfd.readouterr()
    payload = captured.out.encode()
    assert payload == b'{"a":[2,3],"z":1}\n'
    assert len(payload) == 18
    assert hashlib.sha256(payload).hexdigest() == (
        "9c24cd7614ce91d1a480097ac7530c8092a2a7b4b37c90f5364c4d29d15de0a6"
    )
    assert captured.err == ""


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin fail-closed contract")
def test_darwin_output_fails_before_path_mutation_or_publication_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "not-created" / "receipt.json"
    calls = {"open": 0, "unlink": 0, "publish": 0, "census": 0}

    def forbidden_open(*_args, **_kwargs):
        calls["open"] += 1
        raise AssertionError("Darwin --output must not open an output path")

    def forbidden_unlink(*_args, **_kwargs):
        calls["unlink"] += 1
        raise AssertionError("Darwin --output must not unlink an output path")

    def forbidden_publish(*_args, **_kwargs):
        calls["publish"] += 1
        raise AssertionError("Darwin --output must not publish")

    def forbidden_census(_repo):
        calls["census"] += 1
        raise AssertionError("Darwin --output must fail during CLI preflight")

    monkeypatch.setattr(census.os, "open", forbidden_open)
    monkeypatch.setattr(census.os, "unlink", forbidden_unlink)
    monkeypatch.setattr(census, "_publish_fd_noreplace", forbidden_publish)
    monkeypatch.setattr(census, "run_census", forbidden_census)
    assert census.main(["--repo-root", str(tmp_path), "--output", str(output)]) == 2
    with pytest.raises(census.CensusError, match="file publication is disabled on darwin"):
        census._write_output(b"must remain stdout-only\n", output)

    assert calls == {"open": 0, "unlink": 0, "publish": 0, "census": 0}
    assert not output.parent.exists()
    assert "file publication is disabled on darwin" in capsys.readouterr().err


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux anonymous publication contract")
def test_output_publication_is_no_clobber_after_validation(tmp_path: Path) -> None:
    output = tmp_path.parent / f"{tmp_path.name}-outside-output" / "receipt.json"
    validated = census.validate_output_path(tmp_path, output)
    output.parent.mkdir()
    output.write_bytes(b"appeared after validation\n")

    with pytest.raises(census.CensusError, match="refusing to overwrite output"):
        census._write_output(b"replacement\n", validated)

    assert output.read_bytes() == b"appeared after validation\n"
    assert not list(output.parent.glob("*.partial"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux anonymous publication contract")
def test_fd_bound_publication_has_no_source_name_and_final_appears_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path.parent / f"{tmp_path.name}-fd-output" / "receipt.json"
    validated = census.validate_output_path(tmp_path, output)
    payload = b"canonical payload\n"
    original_publish = census._publish_fd_noreplace
    paused = False

    def inspect_then_publish(*args) -> None:
        nonlocal paused
        parent_descriptor, source_descriptor, output_name, expected_size, expected_sha256 = args
        assert os.fstat(source_descriptor).st_size == len(payload)
        assert not output.exists()
        assert list(output.parent.iterdir()) == []
        paused = True
        original_publish(
            parent_descriptor,
            source_descriptor,
            output_name,
            expected_size,
            expected_sha256,
        )

    monkeypatch.setattr(census, "_publish_fd_noreplace", inspect_then_publish)
    census._write_output(payload, validated)

    assert paused
    assert output.read_bytes() == payload
    assert sorted(path.name for path in output.parent.iterdir()) == ["receipt.json"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux anonymous publication contract")
def test_first_staging_fstat_failure_closes_fds_and_leaves_no_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path.parent / f"{tmp_path.name}-fstat-failure" / "receipt.json"
    validated = census.validate_output_path(tmp_path, output)
    original_publish = census._publish_fd_noreplace
    original_fstat = census.os.fstat
    descriptors: dict[str, int] = {}
    fail_next_fstat = False

    def capture_then_publish(parent_descriptor: int, source_descriptor: int, *args) -> None:
        nonlocal fail_next_fstat
        descriptors.update(parent=parent_descriptor, source=source_descriptor)
        fail_next_fstat = True
        original_publish(parent_descriptor, source_descriptor, *args)

    def fail_first_staging_fstat(descriptor: int):
        nonlocal fail_next_fstat
        if fail_next_fstat:
            fail_next_fstat = False
            raise OSError("injected first staging fstat failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(census, "_publish_fd_noreplace", capture_then_publish)
    monkeypatch.setattr(census.os, "fstat", fail_first_staging_fstat)
    with pytest.raises(census.CensusError, match="cannot inspect anonymous staging descriptor"):
        census._write_output(b"canonical payload\n", validated)

    for descriptor in descriptors.values():
        with pytest.raises(OSError):
            original_fstat(descriptor)
    assert not output.exists()
    assert list(output.parent.iterdir()) == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux anonymous publication contract")
def test_unsupported_fd_publication_fails_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path.parent / f"{tmp_path.name}-unsupported-output" / "receipt.json"
    validated = census.validate_output_path(tmp_path, output)

    def unsupported(*_args) -> None:
        raise census.CensusError("injected FD publication unsupported")

    monkeypatch.setattr(census, "_publish_fd_noreplace", unsupported)
    with pytest.raises(census.CensusError, match="injected FD publication unsupported"):
        census._write_output(b"canonical payload\n", validated)

    assert not output.exists()
    assert list(output.parent.iterdir()) == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux anonymous publication contract")
def test_cleanup_error_does_not_mask_root_failure_or_leak_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path.parent / f"{tmp_path.name}-cleanup-output" / "receipt.json"
    validated = census.validate_output_path(tmp_path, output)
    descriptors: dict[str, int] = {}
    original_close = census.os.close

    def root_failure(parent_descriptor: int, source_descriptor: int, *_args) -> None:
        descriptors.update(parent=parent_descriptor, source=source_descriptor)
        raise census.CensusError("injected root publication failure")

    def close_then_error(descriptor: int) -> None:
        original_close(descriptor)
        if descriptor == descriptors.get("source"):
            raise OSError("injected source close failure")

    monkeypatch.setattr(census, "_publish_fd_noreplace", root_failure)
    monkeypatch.setattr(census.os, "close", close_then_error)
    with pytest.raises(census.CensusError, match="injected root publication failure"):
        census._write_output(b"canonical payload\n", validated)

    for descriptor in descriptors.values():
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert not output.exists()
    assert list(output.parent.iterdir()) == []


def test_direct_membership_requires_exact_ordered_set_and_directories(tmp_path: Path) -> None:
    expected = ("44b6_a", "6bba_b")
    for dataset in reversed(expected):
        (tmp_path / f"{dataset}.geff").mkdir()
    assert tuple(path.stem for path in census.validate_direct_membership(tmp_path, expected)) == expected

    (tmp_path / "extra.geff").mkdir()
    with pytest.raises(census.CensusError, match="membership mismatch"):
        census.validate_direct_membership(tmp_path, expected)
    (tmp_path / "extra.geff").rmdir()
    (tmp_path / "6bba_b.geff").rmdir()
    (tmp_path / "6bba_b.geff").write_text("not a directory")
    with pytest.raises(census.CensusError, match="not a directory"):
        census.validate_direct_membership(tmp_path, expected)


def test_direct_membership_rejects_symlink_geff(tmp_path: Path) -> None:
    (tmp_path / "44b6_a.geff").symlink_to(tmp_path / "missing-target", target_is_directory=True)
    with pytest.raises(census.CensusError, match="symlink GEFF root"):
        census.validate_direct_membership(tmp_path, ("44b6_a",))


def test_tree_scan_rejects_symlink_and_nonregular_descendants(tmp_path: Path) -> None:
    root = tmp_path / "root"
    geff = root / "44b6_a.geff"
    geff.mkdir(parents=True)
    backing = tmp_path / "backing"
    backing.write_text("payload")
    link = geff / "link"
    link.symlink_to(backing)
    with pytest.raises(census.CensusError, match="symlink inside GEFF tree"):
        census.scan_tree(root, (geff,))
    link.unlink()

    fifo = geff / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(census.CensusError, match="non-regular GEFF tree entry"):
        census.scan_tree(root, (geff,))


def test_tree_scan_identity_includes_unexpected_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "root"
    geff = root / "44b6_a.geff"
    geff.mkdir(parents=True)
    (geff / "payload").write_text("fixed")
    before = census.scan_tree(root, (geff,))

    (geff / "unexpected-empty").mkdir()
    after = census.scan_tree(root, (geff,))

    assert after.files == before.files
    assert after.bytes == before.bytes
    assert after.canonical_sha256sum_tree_sha256 == before.canonical_sha256sum_tree_sha256
    assert after.directories == before.directories + 1
    assert after.canonical_directory_tree_sha256 != before.canonical_directory_tree_sha256


def test_canonical_report_is_stable_and_rejects_nonfinite() -> None:
    payload = census._canonical_bytes({"z": 1, "a": [2, 3]})
    assert payload == b'{"a":[2,3],"z":1}\n'
    assert json.loads(payload) == {"a": [2, 3], "z": 1}
    with pytest.raises(census.CensusError, match="canonical JSON encoding failed"):
        census._canonical_bytes({"bad": math.nan})


def test_script_has_no_network_kaggle_or_official_metric_import() -> None:
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"kaggle", "requests", "urllib", "subprocess", "tracking_cellmot"})


def test_frozen_inventory_mismatch_fails_closed() -> None:
    wrong = census.TreeInventory(
        roots=36,
        directories=census.EXPECTED_DIRECTORIES,
        files=1_188,
        bytes=10_090_214,
        canonical_sha256sum_tree_sha256=census.EXPECTED_TREE_SHA256,
        canonical_directory_tree_sha256=census.EXPECTED_DIRECTORY_TREE_SHA256,
    )
    with pytest.raises(census.CensusError, match="inventory mismatch"):
        census.validate_frozen_inventory(wrong)

    unexpected_empty_directory = census.TreeInventory(
        roots=36,
        directories=census.EXPECTED_DIRECTORIES + 1,
        files=1_188,
        bytes=10_090_215,
        canonical_sha256sum_tree_sha256=census.EXPECTED_TREE_SHA256,
        canonical_directory_tree_sha256="0" * 64,
    )
    with pytest.raises(census.CensusError, match="inventory mismatch"):
        census.validate_frozen_inventory(unexpected_empty_directory)


def test_linear_percentile_matches_frozen_definition() -> None:
    assert census._linear_percentile([0, 10, 20, 30], 0.95) == pytest.approx(28.5)


def test_frozen_membership_has_balanced_lineages_and_no_public_dummy() -> None:
    assert len(census.EXPECTED_DATASETS) == len(set(census.EXPECTED_DATASETS)) == 36
    assert sum(dataset.startswith("44b6_") for dataset in census.EXPECTED_DATASETS) == 18
    assert sum(dataset.startswith("6bba_") for dataset in census.EXPECTED_DATASETS) == 18
    assert {
        "44b6_0113de3b",
        "44b6_0b24845f",
        "6bba_05b6850b",
        "6bba_05db0fb1",
    }.isdisjoint(census.EXPECTED_DATASETS)
