"""Validation helpers for the remote/local output file namespace.

This module is a pure, isolated helper. It performs no IO, touches no globals,
and depends only on the standard library. Callers run `validate_namespace`
before any transport work begins so that a colliding namespace can never reach
the network layer.

Design notes
------------
The namespace is built from three disjoint categories of *files*:

1. remote final paths (``remote_paths``), which already include selected paths;
2. reserved local files: ``INVENTORY.json``, ``SNAPSHOT_ERROR.json`` and the log;
3. temporary files formed by appending ``.partial`` to each selected path.

Selected finals are part of category 1 and are therefore never treated as a
fourth, separate category. The log is a separate local file; it is not inserted
into the remote set.

Collisions are rejected both exactly and by proper ancestry (a file that is an
ancestor directory of another file). Shared directories are fine. Detection is
linear in the total input size: every file contributes its actual slash
delimited proper prefixes to a single occupancy map, and two files collide iff
one appears as a prefix key of the other. No quadratic all-pairs comparison and
no adjacent lexicographic comparison is used.
"""

from __future__ import annotations

DEFAULT_RESERVED_LOCAL_FILES = ("INVENTORY.json", "SNAPSHOT_ERROR.json")

PARTIAL_SUFFIX = ".partial"

_GENERIC_MESSAGE = "invalid output namespace"


def _fail() -> None:
    """Raise the fixed generic error without echoing input or chaining causes."""
    raise ValueError(_GENERIC_MESSAGE) from None


def _is_string_sequence(value: object) -> bool:
    """Accept only a real list or tuple whose elements are all ``str``.

    Scalars, generators, sets, mappings and bytes are rejected by type. Strings
    are sequences but are explicitly excluded because they are scalars here.
    """
    if not isinstance(value, (list, tuple)):
        return False
    return all(isinstance(item, str) for item in value)


def _check_unique(items: object) -> bool:
    """Return True when ``items`` has no duplicate entries."""
    seen: set[object] = set()
    for item in items:  # type: ignore[union-attr]
        if item in seen:
            return False
        seen.add(item)
    return True


def _is_canonical_relative_path(path: str) -> bool:
    """Validate a lexically canonical relative POSIX file path.

    Rules: nonempty; no backslash; no NUL; not absolute; no trailing slash; no
    empty component; no ``.`` or ``..`` component. No case folding and no
    Unicode normalization is invented -- comparisons stay byte-for-byte.
    """
    if not path:
        return False
    if "\\" in path or "\x00" in path:
        return False
    if path.startswith("/") or path.endswith("/"):
        return False
    for component in path.split("/"):
        if component == "" or component == "." or component == "..":
            return False
    return True


def _proper_prefixes(path: str) -> list[str]:
    """Return the slash-delimited proper ancestor prefixes of ``path``.

    For ``a/b/c`` this yields ``["a", "a/b"]``. Only real directory components
    are enumerated, so character offsets are never confused with depth.
    """
    prefixes: list[str] = []
    index = path.find("/")
    while index != -1:
        prefixes.append(path[:index])
        index = path.find("/", index + 1)
    return prefixes


def validate_namespace(
    remote_paths: object,
    selected_paths: object,
    log_name: object,
) -> None:
    """Validate the complete output namespace or raise ``ValueError``.

    Args:
        remote_paths: Finite list/tuple of unique canonical POSIX file paths
            owned remotely. Selected finals must already be members.
        selected_paths: Non-empty finite list/tuple of unique canonical POSIX
            file paths, a subset of ``remote_paths``.
        log_name: Canonical POSIX path of the separate local log file.

    Raises:
        ValueError: A fixed generic message is raised for every invalid input.
            Neither the inputs nor the underlying cause are echoed.
    """
    if not isinstance(log_name, str):
        _fail()
    if not _is_string_sequence(remote_paths) or not _is_string_sequence(selected_paths):
        _fail()
    if not _check_unique(remote_paths) or not _check_unique(selected_paths):
        _fail()
    if not selected_paths:
        _fail()
    if not _is_canonical_relative_path(log_name):
        _fail()

    for path in remote_paths:  # type: ignore[union-attr]
        if not _is_canonical_relative_path(path):
            _fail()
    for path in selected_paths:  # type: ignore[union-attr]
        if not _is_canonical_relative_path(path):
            _fail()

    remote_set = set(remote_paths)  # type: ignore[arg-type]
    selected_set = set(selected_paths)  # type: ignore[arg-type]
    if not selected_set.issubset(remote_set):
        _fail()

    reserved = set(DEFAULT_RESERVED_LOCAL_FILES)
    if log_name in reserved:
        _fail()
    reserved.add(log_name)

    temp_paths = [path + PARTIAL_SUFFIX for path in selected_paths]  # type: ignore[union-attr]

    # Category overlap checks (exact membership only; ancestry is handled once,
    # globally, by the occupancy scan below).
    for path in temp_paths:
        if path in remote_set or path in reserved:
            _fail()
    if not _check_unique(temp_paths):
        _fail()
    for name in reserved:
        if name in remote_set:
            _fail()

    # Global exact + proper-ancestor collision detection over every file.
    occupants: dict[str, int] = {}

    def register(path: str) -> None:
        owner = occupants.get(path)
        if owner is not None:
            _fail()
        occupants[path] = 1
        for prefix in _proper_prefixes(path):
            if occupants.get(prefix) == 1:
                _fail()
            occupants[prefix] = 2

    for path in remote_paths:  # type: ignore[union-attr]
        register(path)
    for name in sorted(reserved):
        register(name)
    for path in temp_paths:
        register(path)

    # A file may also sit under a directory claimed by another file's ancestry.
    for path in occupants:
        if occupants[path] == 1:
            continue
        for prefix in _proper_prefixes(path):
            if occupants.get(prefix) == 1:
                _fail()
