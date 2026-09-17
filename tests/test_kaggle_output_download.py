"""Focused tests for biohub.kaggle_output_snapshot.download."""

import hashlib

import pytest

from biohub.kaggle_output_snapshot import SnapshotError, download

URL = "https://example.invalid/file.bin"
CHUNK = 1024 ** 2


HOOK_NAMES = ("get", "enter", "exit", "chunk", "eof", "close")


def _noop():
    return None


class FakeResponse:
    def __init__(self, chunks, status=200, headers=None, hooks=None):
        self._chunks = list(chunks)
        self.status_code = status
        self.headers = {} if headers is None else dict(headers)
        self.hooks = {name: _noop for name in HOOK_NAMES}
        if hooks:
            self.hooks.update(hooks)
        self.entered = 0
        self.exited = 0
        self.closed = 0

    def __enter__(self):
        self.entered += 1
        self.hooks["enter"]()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        self.hooks["exit"]()
        return False

    def iter_content(self, chunk_size):
        assert chunk_size == CHUNK
        it = iter(self._chunks)

        def gen():
            while True:
                try:
                    item = next(it)
                except StopIteration:
                    self.hooks["eof"]()
                    return
                self.hooks["chunk"]()
                yield item

        return gen()

    def close(self):
        self.closed += 1
        self.hooks["close"]()


class Recorder:
    def __init__(self, response):
        self.calls = []
        self.response = response

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        self.response.hooks["get"]()
        return self.response


def make(partial, payload=b"", clock=None, deadline=None, **kw):
    body = [payload[i:i + CHUNK] for i in range(0, len(payload), CHUNK)] or [b""]
    resp = FakeResponse(body, **kw)
    return resp, Recorder(resp), (clock if clock is not None else [0.0])


def check_request(rec, timeout):
    assert len(rec.calls) == 1
    url, kw = rec.calls[0]
    assert url == URL
    assert kw["stream"] is True
    assert kw["allow_redirects"] is False
    assert kw["headers"] == {"Accept-Encoding": "identity"}
    assert tuple(kw["timeout"]) == timeout


@pytest.mark.parametrize("size", [0, 10, CHUNK, CHUNK + 7])
def test_success_empty_and_nonempty(tmp_path, size):
    payload = bytes(range(256)) * (size // 256) + b"x" * (size % 256)
    resp, rec, clock = make(tmp_path / "a.bin", payload, clock=[0.0])
    out = tmp_path / "out" / "a.bin"
    got = download(URL, out, size, get=rec, deadline=None, clock=lambda: clock[0])
    assert got == hashlib.sha256(payload).hexdigest()
    assert out.read_bytes() == payload
    assert not out.with_suffix(".bin.partial").exists()
    assert resp.closed == 1
    check_request(rec, (10, 30))


def test_deadline_none_works_and_tiny_timeout(tmp_path):
    payload = b"abc"
    resp, rec, clock = make(tmp_path / "a.bin", payload, clock=[0.0])
    got = download(URL, tmp_path / "a.bin", 3, get=rec, deadline=None,
                   clock=lambda: clock[0])
    assert got == hashlib.sha256(payload).hexdigest()
    check_request(rec, (10, 30))

    resp, rec, clock = make(tmp_path / "b.bin", payload, clock=[0.0])
    got = download(URL, tmp_path / "b.bin", 3, get=rec, deadline=1e-9,
                   clock=lambda: clock[0])
    assert got == hashlib.sha256(payload).hexdigest()
    timeout = rec.calls[0][1]["timeout"]
    total = getattr(timeout, "total", None)
    connect = getattr(timeout, "connect_timeout", None)
    read = getattr(timeout, "read_timeout", None)
    assert total is not None
    assert 0 < total <= 1e-9
    assert 0 < connect <= 1e-9
    assert 0 < read <= 30


@pytest.mark.parametrize("stage", ["get", "enter", "chunk", "eof", "exit", "close"])
def test_expiry_at_each_boundary_fails(tmp_path, stage):
    resp, rec, clock = make(tmp_path / "a.bin", b"abc", clock=[0.0])

    def advance():
        clock[0] = 2.0

    for name in ("get", "enter", "chunk", "eof", "exit", "close"):
        resp.hooks[name] = advance if name == stage else (lambda: None)
    out = tmp_path / "a.bin"
    with pytest.raises(SnapshotError):
        download(URL, out, 3, get=rec, deadline=1.0, clock=lambda: clock[0])
    assert not out.exists()
    assert resp.closed == 1


@pytest.mark.parametrize("external", [SnapshotError("boom"), RuntimeError("boom")])
def test_external_error_becomes_fixed_message_without_cause(tmp_path, external):
    def raiser(*args, **kwargs):
        raise external

    with pytest.raises(SnapshotError) as info:
        download(URL, tmp_path / "a.bin", 3, get=raiser, deadline=None,
                 clock=lambda: 0.0)
    assert str(info.value) == "HTTP download failed"
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


@pytest.mark.parametrize("body", [b"ab", b"abcd"])
def test_truncated_and_overflow(tmp_path, body):
    resp, rec, clock = make(tmp_path / "a.bin", body)
    with pytest.raises(SnapshotError):
        download(URL, tmp_path / "a.bin", 3, get=rec, deadline=None,
                 clock=lambda: clock[0])
    assert not (tmp_path / "a.bin").exists()


def test_chunk_not_bytes(tmp_path):
    resp, rec, clock = make(tmp_path / "a.bin", b"abc")
    resp._chunks = [bytearray(b"abc")]
    with pytest.raises(SnapshotError):
        download(URL, tmp_path / "a.bin", 3, get=rec, deadline=None,
                 clock=lambda: clock[0])


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "1"])
def test_invalid_deadline_before_get(tmp_path, bad):
    resp, rec, clock = make(tmp_path / "a.bin", b"abc")
    with pytest.raises(SnapshotError):
        download(URL, tmp_path / "a.bin", 3, get=rec, deadline=bad,
                 clock=lambda: clock[0])
    assert rec.calls == []


@pytest.mark.parametrize("bad", [-1, True, "3", 1.0])
def test_invalid_size_before_get(tmp_path, bad):
    resp, rec, clock = make(tmp_path / "a.bin", b"abc")
    with pytest.raises(SnapshotError):
        download(URL, tmp_path / "a.bin", bad, get=rec, deadline=None,
                 clock=lambda: clock[0])
    assert rec.calls == []


@pytest.mark.parametrize("status,headers", [
    (302, {}),
    (500, {}),
    (200, {"Content-Encoding": "gzip"}),
    (200, {"Content-Length": "2"}),
])
def test_status_and_headers(tmp_path, status, headers):
    resp, rec, clock = make(tmp_path / "a.bin", b"abc", status=status,
                            headers=headers)
    with pytest.raises(SnapshotError):
        download(URL, tmp_path / "a.bin", 3, get=rec, deadline=None,
                 clock=lambda: clock[0])
    assert resp.closed == 1
    assert not (tmp_path / "a.bin").exists()


def test_existing_final_and_partial_untouched(tmp_path):
    final = tmp_path / "a.bin"
    final.write_bytes(b"keep")
    resp, rec, clock = make(final, b"abc")
    with pytest.raises(SnapshotError):
        download(URL, final, 3, get=rec, deadline=None, clock=lambda: clock[0])
    assert final.read_bytes() == b"keep"
    assert rec.calls == []

    partial = tmp_path / "b.bin.partial"
    partial.write_bytes(b"keep")
    resp, rec, clock = make(tmp_path / "b.bin", b"abc")
    with pytest.raises(SnapshotError):
        download(URL, tmp_path / "b.bin", 3, get=rec, deadline=None,
                 clock=lambda: clock[0])
    assert partial.read_bytes() == b"keep"
    assert rec.calls == []


def test_error_partial_is_retained(tmp_path):
    resp, rec, clock = make(tmp_path / "a.bin", b"abc")
    resp._chunks = [b"ab", b"cd"]
    with pytest.raises(SnapshotError):
        download(URL, tmp_path / "a.bin", 3, get=rec, deadline=None,
                 clock=lambda: clock[0])
    assert (tmp_path / "a.bin.partial").read_bytes() == b"ab"
    assert resp.closed == 1


def test_keyboard_interrupt_propagates(tmp_path):
    def raiser(*args, **kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        download(URL, tmp_path / "a.bin", 3, get=raiser, deadline=None,
                 clock=lambda: 0.0)


@pytest.mark.parametrize("stage", HOOK_NAMES)
@pytest.mark.parametrize("external", [
    KeyboardInterrupt,
    SnapshotError("boom"),
    RuntimeError("boom"),
])
def test_error_at_each_boundary(tmp_path, stage, external):
    boom = external("boom") if isinstance(external, type) and issubclass(
        external, BaseException) else external
    resp, rec, clock = make(tmp_path / "a.bin", b"abc")

    if isinstance(boom, KeyboardInterrupt):
        expected = KeyboardInterrupt
    elif isinstance(boom, SnapshotError):
        expected = SnapshotError
    else:
        expected = SnapshotError

    def raiser(*args, **kwargs):
        raise boom

    for name in HOOK_NAMES:
        resp.hooks[name] = raiser if name == stage else _noop

    out = tmp_path / "a.bin"
    with pytest.raises(expected) as info:
        download(URL, out, 3, get=rec, deadline=None, clock=lambda: clock[0])

    if expected is SnapshotError:
        assert str(info.value) == "HTTP download failed"
        assert info.value.__cause__ is None
        assert info.value.__suppress_context__ is True

    assert not out.exists()
    assert resp.closed == (0 if stage == "get" else 1)



