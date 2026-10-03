"""Tests for kaggle_output_snapshot.list_all_pages / call_external."""

import pytest

from biohub.kaggle_output_snapshot import SnapshotError, call_external, list_all_pages

SECRET = "synthetic-secret-marker-9f3a"


class Limits:
    def __init__(self, files=12000, pages=100, file_bytes=67108864):
        self.files = files
        self.pages = pages
        self.file_bytes = file_bytes


class Clock:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        return self.values[index]


class Source:
    def __init__(self, pages):
        self.pages = list(pages)
        self.tokens = []

    def page(self, token):
        self.tokens.append(token)
        return self.pages[len(self.tokens) - 1]


def page_of(paths, log=None, token=None):
    return {
        "files": [{"path": p, "url": "https://host.example/" + p} for p in paths],
        "log": log,
        "next_page_token": token,
    }


BEFORE = [
    page_of(["a.csv", "b.csv"], "run.log", "n"),
    page_of(["c.csv"], "run.log", None),
]
AFTER_SAME = [
    page_of(["a.csv", "b.csv"], "run.log", "n"),
    page_of(["c.csv"], "run.log", None),
]
AFTER_PATH = [
    page_of(["a.csv", "b.csv"], "run.log", "n"),
    page_of(["z.csv"], "run.log", None),
]
AFTER_URL = [
    {"files": [{"path": "a.csv", "url": "https://other.example/a"},
               {"path": "b.csv", "url": "https://host.example/b"}],
     "log": "run.log", "next_page_token": "n"},
    page_of(["c.csv"], "run.log", None),
]


def run(pages, limits=None, deadline=100.0, clock=None):
    src = Source(pages)
    files, log, count = list_all_pages(src, limits or Limits(), deadline,
                                       clock=clock or Clock([0.0]))
    return files, log, count, src


def test_two_before_and_two_after_via_same_helper():
    b_files, b_log, b_pages, b_src = run(BEFORE)
    s_files, s_log, s_pages, s_src = run(AFTER_SAME)
    p_files, p_log, p_pages, _ = run(AFTER_PATH)
    u_files, u_log, u_pages, _ = run(AFTER_URL)

    assert b_pages == s_pages == p_pages == u_pages == 2
    assert set(b_files) == set(s_files) == {"a.csv", "b.csv", "c.csv"}
    assert b_log == s_log == "run.log"
    # Only AFTER's second-page path changed -> unequal sets.
    assert set(b_files) != set(p_files)
    assert p_log == b_log
    # Only URL strings changed -> path sets and log still equal.
    assert set(b_files) == set(u_files)
    assert u_log == b_log
    assert all(v.startswith("https://") for v in u_files.values())
    # All four exact page tokens, asserted on the real calls.
    assert b_src.tokens == [None, "n"]
    assert s_src.tokens == [None, "n"]


def test_duplicate_within_page():
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv", "a.csv"], "run.log", None)])


def test_duplicate_across_pages():
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv"], "run.log", "n"), page_of(["a.csv"], "run.log", None)])


def test_token_cycle_rejected():
    src = Source([
        page_of(["a.csv"], "run.log", "n"),
        page_of(["b.csv"], "run.log", "n"),
    ])
    with pytest.raises(SnapshotError):
        list_all_pages(src, Limits(), 100.0, clock=Clock([0.0]))
    assert src.tokens == [None, "n"]


def test_empty_token_stops():
    src = Source([page_of(["a.csv"], "run.log", ""), page_of(["b.csv"], "run.log", None)])
    files, _, count = list_all_pages(src, Limits(), 100.0, clock=Clock([0.0]))
    assert count == 1
    assert set(files) == {"a.csv"}
    assert src.tokens == [None]


def test_never_stops_after_first_page():
    _, _, count, src = run([page_of(["a.csv"], "run.log", "n"),
                            page_of(["b.csv"], "run.log", "m"),
                            page_of(["c.csv"], "run.log", None)])
    assert count == 3
    assert src.tokens == [None, "n", "m"]


def test_page_limit():
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv"], "run.log", "n"), page_of(["b.csv"], "run.log", None)],
            Limits(pages=1))


def test_file_limit():
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv", "b.csv"], "run.log", None)], Limits(files=1))


def test_log_byte_limit():
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv"], "x" * 16, None)], Limits(file_bytes=8))


def test_missing_keys_and_bad_types():
    bad = [
        {"files": [], "log": "run.log"},
        {"files": [], "next_page_token": None},
        {"log": "run.log", "next_page_token": None},
        page_of([], "run.log", None),
    ]
    bad[3] = {"files": "nope", "log": "run.log", "next_page_token": None}
    for page in bad:
        with pytest.raises(SnapshotError):
            run([page])


def test_bad_entry_types_and_unsafe_paths():
    for page in [
        {"files": ["a.csv"], "log": "run.log", "next_page_token": None},
        {"files": [{"path": "a.csv"}], "log": "run.log", "next_page_token": None},
        page_of(["../a.csv"], "run.log", None),
        page_of(["/abs/a.csv"], "run.log", None),
        page_of(["."], "run.log", None),
        page_of(["a\\b.csv"], "run.log", None),
        page_of([""], "run.log", None),
    ]:
        with pytest.raises(SnapshotError):
            run([page])


def test_malformed_urls():
    for url in ["http://host.example/a", "https:///a", "https://user@host.example/a",
                "ftp://host.example/a", "not a url"]:
        page = {"files": [{"path": "a.csv", "url": url}],
                "log": "run.log", "next_page_token": None}
        with pytest.raises(SnapshotError):
            run([page])


def test_inconsistent_and_missing_log():
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv"], "one.log", "n"), page_of(["b.csv"], "two.log", None)])
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv"], None, None)])
    with pytest.raises(SnapshotError):
        run([page_of(["a.csv"], "", None)])


def test_empty_log_on_intermediate_pages_ok():
    files, log, count, _ = run([page_of(["a.csv"], None, "n"),
                                page_of(["b.csv"], "", "m"),
                                page_of(["c.csv"], "run.log", None)])
    assert count == 3
    assert log == "run.log"
    assert set(files) == {"a.csv", "b.csv", "c.csv"}


def test_deadline_validation():
    for bad in [float("nan"), float("inf"), True, "soon", None]:
        with pytest.raises(SnapshotError):
            run(BEFORE, deadline=bad, clock=Clock([0.0]))


def test_expired_deadline_no_calls():
    src = Source(BEFORE)
    with pytest.raises(SnapshotError):
        list_all_pages(src, Limits(), 5.0, clock=Clock([5.0]))
    assert src.tokens == []


def test_expiry_inside_callback():
    src = Source(BEFORE)
    with pytest.raises(SnapshotError):
        list_all_pages(src, Limits(), 10.0, clock=Clock([0.0, 10.0]))
    assert src.tokens == [None]


def test_invalid_clock_return():
    with pytest.raises(SnapshotError):
        run(BEFORE, clock=Clock([float("nan")]))


def test_input_immutability():
    limits = Limits(files=5, pages=5, file_bytes=50)
    pages = [dict(page_of(["a.csv"], "run.log", "n")),
             dict(page_of(["b.csv"], "run.log", None))]
    snapshot = [{k: (list(v) if isinstance(v, list) else v) for k, v in p.items()} for p in pages]
    before = (limits.files, limits.pages, limits.file_bytes)
    files, log, count = list_all_pages(Source(pages), limits, 100.0, clock=Clock([0.0]))
    assert (limits.files, limits.pages, limits.file_bytes) == before
    assert pages == snapshot
    assert count == 2
    assert set(files) == {"a.csv", "b.csv"}
    assert log == "run.log"


def test_positive_and_empty_final_page():
    files, log, count, _ = run([page_of(["a.csv"], "run.log", "n"),
                                page_of([], "run.log", None)])
    assert count == 2
    assert set(files) == {"a.csv"}
    assert log == "run.log"


def test_call_external_invokes_once():
    calls = []

    def cb(a, b=0):
        calls.append((a, b))
        return a + b

    assert call_external(cb, 1, b=2) == 3
    assert calls == [(1, 2)]


@pytest.mark.parametrize("factory", [
    lambda: (_ for _ in ()).throw(SnapshotError(SECRET)),
    lambda: (_ for _ in ()).throw(RuntimeError(SECRET)),
])
def test_call_external_sanitizes(factory):
    with pytest.raises(SnapshotError) as excinfo:
        call_external(factory)
    text = str(excinfo.value) + "".join(str(x) for x in excinfo.traceback)
    assert SECRET not in text
    assert "external source call failed" in text
    assert excinfo.value.__cause__ is None


def test_call_external_propagates_base_exception():
    def boom():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        call_external(boom)


def test_pages_limit_admitted_before_second_request():
    src = Source(BEFORE)
    clock = Clock([0.0])
    with pytest.raises(SnapshotError):
        list_all_pages(src, Limits(pages=1), 100.0, clock=clock)
    assert src.tokens == [None]
    assert clock.calls == 2

def test_expiry_detected_before_second_request():
    src = Source(BEFORE)
    clock = Clock([0.0, 0.0, 11.0])
    with pytest.raises(SnapshotError):
        list_all_pages(src, Limits(), 10.0, clock=clock)
    assert src.tokens == [None]
    assert clock.calls == 3


def test_limits_validated_without_consuming_clock():
    src = Source(BEFORE)
    clock = Clock([0.0])
    for limits in (Limits(pages=0), Limits(files=True), Limits(file_bytes=float("nan"))):
        with pytest.raises(SnapshotError):
            list_all_pages(src, limits, 100.0, clock=clock)
    assert src.tokens == []
    assert clock.calls == 0


def test_noncallable_clock_raises_fixed_error():
    src = Source(BEFORE)
    with pytest.raises(SnapshotError) as excinfo:
        list_all_pages(src, Limits(), 100.0, clock="not-a-clock")
    assert str(excinfo.value) == "clock must be callable"
    assert src.tokens == []


def test_noncallable_callback_raises_fixed_error():
    with pytest.raises(SnapshotError) as excinfo:
        call_external(SECRET)
    assert str(excinfo.value) == "callback must be callable"


def test_huge_integer_limit_does_not_leak_input():
    src = Source(BEFORE)
    clock = Clock([0.0])
    huge = 10**1000

    with pytest.raises(SnapshotError) as excinfo:
        list_all_pages(src, Limits(), huge, clock=clock)

    error = excinfo.value
    assert str(error) == 'deadline must be a finite number'
    assert error.__cause__ is None
    assert str(huge) not in str(error)
    assert src.tokens == []
    assert clock.calls == 0

def test_invalid_utf8_log_is_rejected():
    src = Source([page_of(["a.csv"], chr(0xD800), None)])
    with pytest.raises(SnapshotError) as excinfo:
        list_all_pages(src, Limits(), 100.0, clock=Clock([0.0]))
    assert str(excinfo.value) == "log byte limit exceeded"
    assert src.tokens == [None]

def test_source_failure_called_exactly_once():
    class Failing:
        def __init__(self):
            self.tokens = []

        def page(self, token):
            self.tokens.append(token)
            raise RuntimeError(SECRET)

    src = Failing()
    with pytest.raises(SnapshotError) as excinfo:
        list_all_pages(src, Limits(), 100.0, clock=Clock([0.0]))
    assert src.tokens == [None]
    assert "external source call failed" in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_keyboard_interrupt_from_source_propagates():
    class Interrupting:
        def __init__(self):
            self.tokens = []

        def page(self, token):
            self.tokens.append(token)
            raise KeyboardInterrupt

    src = Interrupting()
    with pytest.raises(KeyboardInterrupt):
        list_all_pages(src, Limits(), 100.0, clock=Clock([0.0]))
    assert src.tokens == [None]
