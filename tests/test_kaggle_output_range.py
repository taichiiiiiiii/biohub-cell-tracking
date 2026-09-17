"""Focused tests for biohub.kaggle_output_snapshot.range_size."""

import pytest

from biohub.kaggle_output_snapshot import SnapshotError, range_size

URL = "https://example.invalid/resource"
BOUNDARIES = ("get", "enter", "read", "exit", "close")
EXPIRED = 2.0
DEADLINE = 1.0
MESSAGE = "HTTP size request failed"


class FakeResponse:
    def __init__(self, status_code=206, headers=None, body=b"x", hooks=None):
        self.status_code = status_code
        self.headers = dict(headers) if headers is not None else {}
        self.body = body
        self.raw = self
        self.hooks = hooks if hooks is not None else {}
        self.entered = []
        self.exited = []
        self.closed = 0
        self.read_calls = 0

    def read(self, amt):
        hook = self.hooks.get("read")
        if hook is not None:
            hook()
        self.read_calls += 1
        return self.body[:amt]

    def __enter__(self):
        self.entered.append(len(self.entered))
        hook = self.hooks.get("enter")
        if hook is not None:
            hook()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited.append(exc_type)
        hook = self.hooks.get("exit")
        if hook is not None:
            hook()
        return False

    def close(self):
        self.closed += 1
        hook = self.hooks.get("close")
        if hook is not None:
            hook()


class FakeGet:
    def __init__(self, response, raises=None, clock=None, hooks=None):
        self.response = response
        self.raises = raises
        self.clock = clock if clock is not None else [0.0]
        self.hooks = hooks if hooks is not None else {}
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        hook = self.hooks.get("get")
        if hook is not None:
            hook()
        if self.raises is not None:
            raise self.raises
        return self.response


def good_headers(total=11):
    return {"Content-Range": f"bytes 0-0/{total:d}", "Content-Length": "1"}


def expire_at(boundary, clock, hooks):
    for name in BOUNDARIES:
        if name == boundary:
            hooks[name] = lambda: clock.__setitem__(0, EXPIRED)


def _wire(hooks, response_kwargs, get_kwargs):
    """Attach the same hooks dictionary to both collaborators."""
    response_kwargs["hooks"] = hooks
    get_kwargs["hooks"] = hooks


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_expiry_explains_deadline(boundary):
    clock = [0.0]
    hooks = {}
    expire_at(boundary, clock, hooks)
    response_kwargs = {"headers": good_headers()}
    get_kwargs = {}
    _wire(hooks, response_kwargs, get_kwargs)
    response = FakeResponse(**response_kwargs)
    get = FakeGet(response, **get_kwargs)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, deadline=DEADLINE, clock=lambda: clock[0])
    assert str(info.value) == MESSAGE
    assert len(get.calls) == 1
    assert response.closed == 1


@pytest.mark.parametrize("exc", [RuntimeError("boom"), SnapshotError("inner")])
@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_exceptions_are_wrapped_only(exc, boundary):
    clock = [0.0]
    hooks = {}

    def raise_it():
        raise exc

    hooks[boundary] = raise_it
    response_kwargs = {"headers": good_headers()}
    get_kwargs = {}
    _wire(hooks, response_kwargs, get_kwargs)
    response = FakeResponse(**response_kwargs)
    get = FakeGet(response, **get_kwargs)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, deadline=DEADLINE, clock=lambda: clock[0])
    assert str(info.value) == MESSAGE
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True
    assert len(get.calls) == 1
    assert response.closed == (0 if boundary == "get" else 1)


@pytest.mark.parametrize("bad", [None, 4, "https://"])
def test_invalid_inputs_reject_before_get(bad):
    get = FakeGet(FakeResponse(headers=good_headers()))
    with pytest.raises(SnapshotError) as info:
        range_size(bad, get, deadline=DEADLINE, clock=lambda: 0.0)
    assert str(info.value) == MESSAGE
    assert get.calls == []


@pytest.mark.parametrize("deadline", [None, float("nan"), float("inf")])
def test_deadline_validation_and_none(deadline):
    clock = [0.0]
    response = FakeResponse(headers=good_headers())
    get = FakeGet(response)
    if deadline is None:
        size = range_size(URL, get, deadline=deadline, clock=lambda: clock[0])
        assert size == 11
        assert len(get.calls) == 1
        assert response.closed == 1
    else:
        with pytest.raises(SnapshotError) as info:
            range_size(URL, get, deadline=deadline, clock=lambda: clock[0])
        assert str(info.value) == MESSAGE
        assert get.calls == []


@pytest.mark.parametrize("deadline", [-1.0, 0.0, float("nan"), float("inf"), True])
def test_expired_or_invalid_deadline_makes_no_calls(deadline):
    clock = [0.0]
    response = FakeResponse(headers=good_headers())
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, deadline=deadline, clock=lambda: clock[0])
    assert str(info.value) == MESSAGE
    assert get.calls == []
    assert response.closed == 0


@pytest.mark.parametrize("clock_value", [None, "x", float("nan"), float("inf"), True])
def test_invalid_clock_makes_no_calls(clock_value):
    response = FakeResponse(headers=good_headers())
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, deadline=DEADLINE, clock=lambda: clock_value)
    assert str(info.value) == MESSAGE
    assert get.calls == []
    assert response.closed == 0


def test_success_206_identity_and_strict_headers():
    clock = [0.0]
    response = FakeResponse(headers=good_headers(42))
    get = FakeGet(response)
    size = range_size(URL, get, deadline=DEADLINE, clock=lambda: clock[0])
    assert size == 42
    assert len(get.calls) == 1
    url, kwargs = get.calls[0]
    assert url == URL
    assert kwargs["stream"] is True
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Range"] == "bytes=0-0"
    assert kwargs["headers"]["Accept-Encoding"] == "identity"
    assert response.read_calls == 1
    assert response.entered and response.exited == [None]
    assert response.closed == 1


@pytest.mark.parametrize(
    "content_range",
    [
        None,
        "bytes 0-0/11\n",
        " bytes 0-0/11",
        "bytes 0-0/011",
        "bytes 0-1/11",
        "bytes 0-0/0",
        "bytes 0-0/abc",
        "items 0-0/11",
    ],
)
def test_content_range_is_strict(content_range):
    headers = {"Content-Length": "1"}
    if content_range is not None:
        headers["Content-Range"] = content_range
    response = FakeResponse(headers=headers)
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, clock=lambda: 0.0)
    assert str(info.value) == MESSAGE
    assert response.closed == 1


@pytest.mark.parametrize("content_length", ["0", "2", "1 ", " 1", "1\n", "", "x"])
def test_content_length_whitespace_is_rejected(content_length):
    response = FakeResponse(
        headers={"Content-Range": "bytes 0-0/11", "Content-Length": content_length}
    )
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, clock=lambda: 0.0)
    assert str(info.value) == MESSAGE
    assert response.read_calls == 0
    assert response.closed == 1


@pytest.mark.parametrize("encoding", [None, "identity"])
def test_identity_encoding_is_accepted(encoding):
    headers = good_headers(7)
    if encoding is not None:
        headers["Content-Encoding"] = encoding
    response = FakeResponse(headers=headers, body=b"abcdefg")
    get = FakeGet(response)
    size = range_size(URL, get, clock=lambda: 0.0)
    assert size == 7
    assert response.read_calls == 1
    assert response.closed == 1


def test_encoded_body_is_not_read():
    response = FakeResponse(headers=good_headers())
    response.headers["Content-Encoding"] = "gzip"
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, clock=lambda: 0.0)
    assert str(info.value) == MESSAGE
    assert response.read_calls == 0
    assert response.closed == 1


def test_416_returns_zero_without_reading():
    response = FakeResponse(
        status_code=416, headers={"Content-Range": "bytes */0"}
    )
    get = FakeGet(response)
    size = range_size(URL, get, clock=lambda: 0.0)
    assert size == 0
    assert response.read_calls == 0
    assert response.closed == 1


@pytest.mark.parametrize(
    "status,content_range",
    [
        (416, None),
        (416, "bytes */1"),
        (416, "bytes */0 \n"),
        (500, "bytes */0"),
        (301, "bytes */0"),
    ],
)
def test_bad_status_or_range_does_not_succeed(status, content_range):
    headers = {}
    if content_range is not None:
        headers["Content-Range"] = content_range
    response = FakeResponse(status_code=status, headers=headers)
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, clock=lambda: 0.0)
    assert str(info.value) == MESSAGE
    assert response.read_calls == 0
    assert response.closed == 1


def test_200_body_is_not_read():
    response = FakeResponse(status_code=200, headers=good_headers(), body=b"abcdef")
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, clock=lambda: 0.0)
    assert str(info.value) == MESSAGE
    assert response.read_calls == 0
    assert response.closed == 1


def test_tiny_deadline_builds_timeout_from_leftover():
    clock = [0.0]
    response = FakeResponse(headers=good_headers())
    get = FakeGet(response)
    size = range_size(URL, get, deadline=1e-9, clock=lambda: clock[0])
    assert size == 11
    timeout = get.calls[0][1]["timeout"]
    assert timeout.total <= 1e-9


@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_keyboard_interrupt_propagates(boundary):
    clock = [0.0]
    hooks = {}

    def interrupt():
        raise KeyboardInterrupt

    hooks[boundary] = interrupt
    response_kwargs = {"headers": good_headers()}
    get_kwargs = {}
    _wire(hooks, response_kwargs, get_kwargs)
    response = FakeResponse(**response_kwargs)
    get = FakeGet(response, **get_kwargs)
    with pytest.raises(KeyboardInterrupt):
        range_size(URL, get, deadline=DEADLINE, clock=lambda: clock[0])
    assert response.closed == (0 if boundary == "get" else 1)


@pytest.mark.parametrize("status_code", [206, 416])
@pytest.mark.parametrize("boundary", ["exit"])
def test_expiry_at_exit_status_boundaries_raises_and_closes(status_code, boundary):
    clock = [0.0]
    hooks = {}
    expire_at(boundary, clock, hooks)
    if status_code == 416:
        headers = {"Content-Range": "bytes */0"}
    else:
        headers = good_headers()
    response_kwargs = {"headers": headers}
    get_kwargs = {}
    _wire(hooks, response_kwargs, get_kwargs)
    response = FakeResponse(status_code=status_code, **response_kwargs)
    get = FakeGet(response, **get_kwargs)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, deadline=DEADLINE, clock=lambda: clock[0])
    assert str(info.value) == MESSAGE
    assert len(get.calls) == 1
    assert response.closed == 1


@pytest.mark.parametrize("encoding", ["IDENTITY", "Identity", " identity", "identity "])
def test_non_exact_identity_encoding_is_rejected(encoding):
    headers = good_headers(7)
    headers["Content-Encoding"] = encoding
    response = FakeResponse(headers=headers, body=b"abcdefg")
    get = FakeGet(response)
    with pytest.raises(SnapshotError) as info:
        range_size(URL, get, clock=lambda: 0.0)
    assert str(info.value) == MESSAGE
    assert response.read_calls == 0
    assert response.closed == 1
