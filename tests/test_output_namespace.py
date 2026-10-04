"""Unit tests for :mod:`biohub.output_namespace`.

Every negative case uses an explicit ``pytest.raises`` assertion against input
that genuinely fails validation, and checks the fixed generic message so that
nothing can echo the offending input. There is no vacuous try/except pattern.
"""

from __future__ import annotations

import pytest

from biohub.output_namespace import validate_namespace

MESSAGE = "invalid output namespace"


def expect_reject(remote, selected, log):
    with pytest.raises(ValueError) as excinfo:
        validate_namespace(remote, selected, log)
    assert str(excinfo.value) == MESSAGE
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_accept_simple_pair():
    validate_namespace(["a", "b"], ["a"], "slug.log")


def test_accept_nested_siblings_both_selected():
    validate_namespace(["d/a", "d/b"], ["d/a", "d/b"], "logs/run.log")


def test_accept_partial_named_like_remote_file():
    # remote contains "a.partial"; selecting it yields temp "a.partial.partial".
    validate_namespace(["a", "a.partial"], ["a.partial"], "slug.log")


def test_accept_empty_component_looking_names_are_rejected_separately():
    validate_namespace(["x/y", "x/z"], ["x/y"], "run.log")


def test_accept_tuple_inputs():
    validate_namespace(("a", "b"), ("a",), "slug.log")


def test_accept_large_fixture_is_linear_and_passes():
    remote = [f"batch-{i // 100:03d}/cell-{i:05d}.tif" for i in range(12000)]
    selected = [remote[i] for i in range(0, len(remote), 7)]
    validate_namespace(remote, selected, "logs/run.log")


def test_reject_file_ancestor_of_directory():
    expect_reject(["a", "a/b"], ["a"], "slug.log")


def test_reject_unselected_remote_ancestor_collision():
    # "a" is a remote file and "a/b" is another remote file, even unselected.
    expect_reject(["a", "a-b", "a/b"], ["a-b"], "slug.log")


def test_reject_deep_ancestor_collision_across_categories():
    expect_reject(["p/q/r"], ["p/q/r"], "p/q")


def test_reject_selected_temp_collides_with_remote_file():
    expect_reject(["a", "a.partial"], ["a"], "slug.log")


def test_reject_selected_temp_under_remote_directory_file():
    expect_reject(["a", "a.partial/b"], ["a"], "slug.log")


def test_reject_remote_temp_ancestor_of_selected_temp():
    expect_reject(["a", "a.partial"], ["a", "a.partial"], "slug.log")


def test_reject_reserved_log_exact_in_remote():
    expect_reject(["logs", "logs/run.log"], ["logs"], "logs/run.log")


def test_reject_remote_descendant_of_log():
    expect_reject(["logs/run.log", "logs/run.log/x"], ["logs/run.log/x"], "logs/run.log")


def test_reject_log_ancestor_of_remote():
    expect_reject(["slug.log/part"], ["slug.log/part"], "slug.log")


@pytest.mark.parametrize("reserved", ["INVENTORY.json", "SNAPSHOT_ERROR.json"])
def test_reject_each_reserved_name_as_remote(reserved):
    expect_reject([reserved], [reserved], "slug.log")


@pytest.mark.parametrize("reserved", ["INVENTORY.json", "SNAPSHOT_ERROR.json"])
def test_reject_each_reserved_name_as_log(reserved):
    expect_reject(["a"], ["a"], reserved)


@pytest.mark.parametrize("reserved", ["INVENTORY.json", "SNAPSHOT_ERROR.json"])
def test_reject_descendant_of_reserved_name(reserved):
    expect_reject([reserved + "/x"], [reserved + "/x"], "slug.log")


def test_reject_reserved_name_as_directory_file_conflict():
    expect_reject(["INVENTORY.json/leaf"], ["INVENTORY.json/leaf"], "INVENTORY.json/leaf")


def test_reject_missing_selection_not_subset():
    expect_reject(["a", "b"], ["c"], "slug.log")


def test_reject_partially_missing_selection():
    expect_reject(["a", "b"], ["a", "z"], "slug.log")


def test_reject_duplicate_remote_entries():
    expect_reject(["a", "a"], ["a"], "slug.log")


def test_reject_duplicate_selected_entries():
    expect_reject(["a", "b"], ["a", "a"], "slug.log")


def test_reject_empty_selection():
    expect_reject(["a"], [], "slug.log")


def test_reject_empty_remote_with_selection():
    expect_reject([], ["a"], "slug.log")


@pytest.mark.parametrize("bad", [None, 1, 1.5, True, b"a", {"a"}, frozenset({"a"}), "ab"])
def test_reject_nonstring_sequences(bad):
    expect_reject(bad, ["a"], "slug.log")
    expect_reject(["a"], bad, "slug.log")


def test_reject_generator_input():
    expect_reject(iter(["a"]), iter(["a"]), "slug.log")


def test_reject_dict_input():
    expect_reject({"a": 1}, ["a"], "slug.log")


def test_reject_mixed_element_types():
    expect_reject(["a", 2], ["a"], "slug.log")
    expect_reject(["a", "b"], ["a", None], "slug.log")


@pytest.mark.parametrize("bad_log", [None, 3, b"slug.log", ["slug.log"]])
def test_reject_nonstring_log(bad_log):
    expect_reject(["a"], ["a"], bad_log)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/abs",
        "a\\b",
        "a\x00b",
        "a//b",
        "./a",
        "../a",
        "a/../b",
        "a/.",
        "a/..",
        "a/",
        "/",
        ".",
        "..",
    ],
)
def test_reject_noncanonical_paths_everywhere(path):
    expect_reject([path], [path], "slug.log")
    expect_reject(["a"], ["a"], path)


def test_reject_noncanonical_selected_only():
    expect_reject(["a", "b/"], ["b/"], "slug.log")


def test_does_not_echo_input_in_message():
    secret = "super-secret-path-that-must-not-leak"
    with pytest.raises(ValueError) as excinfo:
        validate_namespace([secret, secret + "/x"], [secret], "slug.log")
    rendered = str(excinfo.value)
    assert rendered == MESSAGE
    assert secret not in rendered


def test_preserves_inputs_unchanged():
    remote = ["d/a", "d/b", "c"]
    selected = ["d/a", "c"]
    log = "logs/run.log"
    remote_snapshot = list(remote)
    selected_snapshot = list(selected)

    validate_namespace(remote, selected, log)

    assert remote == remote_snapshot
    assert selected == selected_snapshot
    assert log == "logs/run.log"


def test_preserves_inputs_unchanged_on_failure():
    remote = ["a", "a/b"]
    selected = ["a"]
    remote_snapshot = list(remote)
    selected_snapshot = list(selected)

    with pytest.raises(ValueError):
        validate_namespace(remote, selected, "slug.log")

    assert remote == remote_snapshot
    assert selected == selected_snapshot


def test_returns_none_on_success():
    assert validate_namespace(["a"], ["a"], "slug.log") is None
