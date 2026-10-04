"""Independent orchestration tests for biohub.kaggle_output_snapshot."""
import hashlib
import json

import pytest

import biohub.kaggle_output_snapshot as m

BODIES = {"a.bin": b"AAA", "b.bin": b"BBBBB", "c.bin": b"CCCCCCC", "d.bin": b"D"}
FILES = ["a.bin", "b.bin", "c.bin"]
HASHES = {name: hashlib.sha256(body).hexdigest() for name, body in BODIES.items()}


def body(url):
    name = url.split("/")[-1].split("?")[0]
    return BODIES[name]


def bad_get(*args, **kwargs):
    raise AssertionError("network used")


class Source:
    kernel = "owner/slug"

    def __init__(self, after_log="ok", second_after="c.bin"):
        self.status_calls = 0
        self.tokens = []
        self.pages = 0
        self.after_log = after_log
        self.second_after = second_after

    def status(self):
        self.status_calls += 1
        return "COMPLETE"

    def page(self, token):
        self.tokens.append(token)
        self.pages += 1
        before = self.pages <= 2
        log = "ok" if before or self.after_log == "ok" else self.after_log
        if before:
            names = FILES[:2] if self.pages == 1 else FILES[2:]
        else:
            names = [self.second_after] if self.pages == 4 else FILES[:2]
        files = [{"path": n, "url": "https://example.invalid/" + n + "?v=1" if before else
                  "https://example.invalid/" + n + "?v=2"} for n in names]
        return {"files": files, "log": log,
                "next_page_token": "p2" if self.pages % 2 else None}


class FakeFuture:
    def __init__(self, fn):
        self.fn = fn

    def result(self, timeout):
        assert timeout > 0
        out = self.fn()
        self.fn = None
        return out


class FakeExecutor:
    instances = []

    def __init__(self, max_workers):
        assert max_workers > 0
        self.submits = []
        self.shutdowns = []
        FakeExecutor.instances.append(self)

    def submit(self, fn, *args, **kwargs):
        assert kwargs.get("timeout", 1) > 0
        self.submits.append(fn)
        return FakeFuture(lambda: fn(*args, **kwargs))

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdowns.append((wait, cancel_futures))


@pytest.fixture(autouse=True)
def patched(monkeypatch, tmp_path):
    FakeExecutor.instances = []
    calls = {"range": [], "download": []}

    def fake_range(url, get, *, deadline, clock):
        assert deadline > 0
        calls["range"].append(url)
        return len(body(url))

    def fake_download(url, path, size, get, *, deadline, clock):
        assert deadline > 0 and size > 0
        data = body(url)
        assert len(data) == size
        with open(path, "wb") as handle:
            handle.write(data)
        calls["download"].append(str(path))
        return hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(m, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(m, "range_size", fake_range)
    monkeypatch.setattr(m, "download", fake_download)
    yield tmp_path, calls


def run(tmp_path, source, progress=None, required=("a.bin", "b.bin")):
    return m.snapshot(source, tmp_path / "out", list(required),
                      limits=m.Limits(io_threads=2), get=bad_get,
                      progress=progress, clock=lambda: 0.0)


def test_success_two_pages_before_after(patched):
    tmp_path, calls = patched
    src = Source()
    receipt = run(tmp_path, src)
    assert src.tokens == [None, "p2", None, "p2"]
    assert src.status_calls == 3
    assert receipt["files"] == [{"path": "a.bin", "bytes": 3},
                                {"path": "b.bin", "bytes": 5},
                                {"path": "c.bin", "bytes": 7}]
    assert receipt["downloaded"] == [{"path": "a.bin", "bytes": 3, "sha256": HASHES["a.bin"]},
                                     {"path": "b.bin", "bytes": 5, "sha256": HASHES["b.bin"]}]
    assert receipt["log_path"] == "slug.log"
    assert receipt["log_sha256"] == hashlib.sha256(b"ok").hexdigest()
    assert receipt["downloaded_bytes"] == 10
    assert receipt["total_remote_bytes"] == 15
    assert receipt["pages"] == 2
    assert receipt["pages_after"] == 2
    assert receipt["submission_authorized"] is False
    for banned in ("sizes", "log", "sha256", "submitted"):
        assert banned not in receipt
    assert "example.invalid" not in json.dumps(receipt)
    assert [i.shutdowns for i in FakeExecutor.instances] == [[(False, True)]]
    assert len(calls["range"]) == 3
    assert len(calls["download"]) == 2


def test_after_second_page_changed_rejects(patched):
    tmp_path, _ = patched
    with pytest.raises(m.SnapshotError) as exc:
        run(tmp_path, Source(second_after="d.bin"))
    err = str(exc.value)
    assert err == "snapshot failed"
    doc = json.loads((tmp_path / "out" / "SNAPSHOT_ERROR.json").read_text())
    assert doc["phase"] == "status-after-list"
    assert "exception_type" not in doc
    assert not (tmp_path / "out" / "INVENTORY.json").exists()


def test_after_log_changed_rejects(patched):
    tmp_path, _ = patched
    with pytest.raises(m.SnapshotError) as exc:
        run(tmp_path, Source(after_log="bad"))
    err = str(exc.value)
    assert err == "snapshot failed"
    doc = json.loads((tmp_path / "out" / "SNAPSHOT_ERROR.json").read_text())
    assert doc["phase"] == "status-after-list"
    assert "exception_type" not in doc
    assert not (tmp_path / "out" / "INVENTORY.json").exists()


def test_progress_error_receipt(patched):
    tmp_path, _ = patched

    def progress(*args, **kwargs):
        raise m.SnapshotError("sentinel")

    with pytest.raises(m.SnapshotError) as exc:
        run(tmp_path, Source(), progress)
    err = str(exc.value)
    assert err == "snapshot failed"
    doc = json.loads((tmp_path / "out" / "SNAPSHOT_ERROR.json").read_text())
    assert doc["phase"] == "range-inventory"
    assert "sentinel" not in json.dumps(doc)
    assert "exception_type" not in doc
    assert not (tmp_path / "out" / "INVENTORY.json").exists()


def test_verify_failure_after_download(patched):
    tmp_path, _ = patched
    target = tmp_path / "out" / "a.bin"

    def progress(*args, **kwargs):
        if target.exists():
            target.write_bytes(b"BAD")

    with pytest.raises(m.SnapshotError) as exc:
        run(tmp_path, Source(), progress)
    err = str(exc.value)
    assert err == "snapshot failed"
    doc = json.loads((tmp_path / "out" / "SNAPSHOT_ERROR.json").read_text())
    assert doc["phase"] == "verify"
    assert "exception_type" not in doc
    assert not (tmp_path / "out" / "INVENTORY.json").exists()


def test_required_empty_does_nothing(patched):
    tmp_path, calls = patched
    src = Source()
    with pytest.raises(m.SnapshotError):
        run(tmp_path, src, required=[])
    assert src.status_calls == 0 and src.tokens == []
    assert calls["range"] == [] and calls["download"] == []
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("overrides,phase", [
    ({"remote_bytes": 14}, "range-inventory"),
    ({"download_bytes": 9}, "size-policy"),
    ({"file_bytes": 4}, "size-policy"),
])
def test_limits_reject_before_any_download(patched, overrides, phase):
    tmp_path, calls = patched
    src = Source()
    with pytest.raises(m.SnapshotError) as exc:
        m.snapshot(src, tmp_path / "out", ["a.bin", "b.bin"],
                   limits=m.Limits(io_threads=2, **overrides),
                   get=bad_get, clock=lambda: 0.0)
    assert str(exc.value) == "snapshot failed"
    doc = json.loads((tmp_path / "out" / "SNAPSHOT_ERROR.json").read_text())
    assert doc["phase"] == phase
    assert "exception_type" not in doc
    assert not (tmp_path / "out" / "INVENTORY.json").exists()
    assert calls["download"] == []


class CollisionSource(Source):
    def __init__(self, collision):
        super().__init__()
        self.collision = collision

    def page(self, token):
        result = super().page(token)
        if self.pages == 2:
            result["files"].append({"path": self.collision,
                                    "url": "https://example.invalid/collision"})
        return result


@pytest.mark.parametrize("collision", ["INVENTORY.json", "a.bin.partial"])
def test_collision_second_page_before_remote_inventory(patched, collision):
    tmp_path, calls = patched
    out = tmp_path / "out"

    with pytest.raises(m.SnapshotError) as exc:
        run(tmp_path, CollisionSource(collision))
    assert str(exc.value) == "snapshot failed"
    assert not out.exists()
    assert calls["range"] == [] and calls["download"] == []


def test_future_timeout_fixed_error(patched):
    tmp_path, calls = patched

    class BoomFuture(FakeFuture):
        def result(self, timeout):
            raise TimeoutError("sentinel")

    class BoomExecutor(FakeExecutor):
        def submit(self, fn, *args, **kwargs):
            self.submits.append(fn)
            return BoomFuture(lambda: fn(*args, **kwargs))

    saved = m.ThreadPoolExecutor
    m.ThreadPoolExecutor = BoomExecutor
    try:
        with pytest.raises(m.SnapshotError) as exc:
            run(tmp_path, Source())
    finally:
        m.ThreadPoolExecutor = saved
    assert str(exc.value) == "snapshot failed"
    doc = json.loads((tmp_path / "out" / "SNAPSHOT_ERROR.json").read_text())
    assert "exception_type" not in doc
    assert "sentinel" not in json.dumps(doc)
    assert not (tmp_path / "out" / "INVENTORY.json").exists()
    assert calls["download"] == []
    assert [i.shutdowns for i in FakeExecutor.instances] == [[(False, True)]]


@pytest.mark.parametrize(
    "progress",
    [
        42,
        "bad",
        False,
    ],
)
def test_invalid_progress_no_side_effects(patched, progress):
    tmp_path, calls = patched
    src = Source()
    with pytest.raises(m.SnapshotError):
        run(tmp_path, src, progress=progress)
    assert src.status_calls == 0 and src.tokens == []
    assert calls["range"] == [] and calls["download"] == []
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), True])
def test_invalid_seconds_no_side_effects(patched, seconds):
    tmp_path, calls = patched
    src = Source()
    with pytest.raises(m.SnapshotError):
        m.snapshot(src, tmp_path / "out", ["a.bin", "b.bin"],
                   limits=m.Limits(io_threads=2, seconds=seconds),
                   get=bad_get, clock=lambda: 0.0)
    assert src.status_calls == 0 and src.tokens == []
    assert calls["range"] == [] and calls["download"] == []
    assert not (tmp_path / "out").exists()


def test_existing_output_sentinel_preserved(patched):
    tmp_path, calls = patched
    out = tmp_path / "out"
    out.mkdir()
    (out / "INVENTORY.json").write_text("sentinel")
    (out / "a.bin").write_bytes(b"do-not-touch")

    with pytest.raises(m.SnapshotError):
        run(tmp_path, Source())
    assert (out / "INVENTORY.json").read_text() == "sentinel"
    assert (out / "a.bin").read_bytes() == b"do-not-touch"
    assert not (out / "SNAPSHOT_ERROR.json").exists()
    assert calls["range"] == [] and calls["download"] == []


def test_external_status_and_page_errors_fixed(patched):
    tmp_path, calls = patched

    class BadStatus(Source):
        def status(self):
            raise RuntimeError("kaboom")

    with pytest.raises(m.SnapshotError) as exc:
        run(tmp_path, BadStatus())
    assert str(exc.value) == "snapshot failed"
    assert not (tmp_path / "out").exists()

    class BadPage(Source):
        def page(self, token):
            raise m.SnapshotError("kaboom")

    with pytest.raises(m.SnapshotError) as exc:
        run(tmp_path, BadPage())
    assert str(exc.value) == "snapshot failed"
    assert not (tmp_path / "out").exists()
    assert calls["range"] == [] and calls["download"] == []


def test_clock_expiry_in_future_result(patched):
    tmp_path, calls = patched
    now = [0.0]

    class SlowFuture(FakeFuture):
        def result(self, timeout):
            now[0] = 2.0
            return self.fn()

    class SlowExecutor(FakeExecutor):
        def submit(self, fn, *args, **kwargs):
            self.submits.append(fn)
            return SlowFuture(lambda: fn(*args, **kwargs))

    saved = m.ThreadPoolExecutor
    m.ThreadPoolExecutor = SlowExecutor
    try:
        with pytest.raises(m.SnapshotError) as exc:
            m.snapshot(Source(), tmp_path / "out", ["a.bin", "b.bin"],
                       limits=m.Limits(io_threads=2, seconds=1),
                       get=bad_get, clock=lambda: now[0])
    finally:
        m.ThreadPoolExecutor = saved
    assert str(exc.value) == "snapshot failed"
    assert not (tmp_path / "out" / "INVENTORY.json").exists()
    assert calls["download"] == []
    assert [i.shutdowns for i in FakeExecutor.instances] == [[(False, True)]]


def test_success_actual_written_bytes_match_fixtures(patched):
    tmp_path, calls = patched
    run(tmp_path, Source())
    out = tmp_path / "out"
    for name in ("a.bin", "b.bin"):
        assert (out / name).read_bytes() == BODIES[name]
    assert sorted(calls["download"]) == sorted(str(out / n) for n in ("a.bin", "b.bin"))
    assert hashlib.sha256((out / "a.bin").read_bytes()).hexdigest() == HASHES["a.bin"]
    assert hashlib.sha256((out / "b.bin").read_bytes()).hexdigest() == HASHES["b.bin"]


