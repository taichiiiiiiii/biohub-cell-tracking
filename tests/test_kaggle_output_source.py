"""Focused tests for KaggleOutputSource using an injected fake API."""

from types import SimpleNamespace

import pytest
from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest

from biohub.kaggle_output_snapshot import SnapshotError
from biohub.kaggle_output_source import KaggleOutputSource


class _Enum:
    def __init__(self, name):
        self.name = name


class _Ctx:
    def __init__(self, client, enter_error=None, exit_error=None):
        self.client = client
        self.enter_error = enter_error
        self.exit_error = exit_error
        self.entered = 0
        self.exited = 0

    def __enter__(self):
        self.entered += 1
        if self.enter_error:
            raise self.enter_error
        return self.client

    def __exit__(self, exc_type, exc, tb):
        self.exited += 1
        if self.exit_error:
            raise self.exit_error
        return False


def _client(files=None, log="ok", next_token="", list_error=None):
    calls = []

    class _Svc:
        def list_kernel_session_output(self, request):
            calls.append(request)
            if list_error:
                raise list_error
            return SimpleNamespaceResp(files, log, next_token)

    ns = SimpleNamespace(kernels=SimpleNamespace(kernels_api_client=_Svc()))
    return ns, calls


class SimpleNamespaceResp:
    def __init__(self, files, log, next_token):
        self.files = files
        self.log = log
        self.next_page_token = next_token


class FakeApi:
    def __init__(self, status="COMPLETE", kernels_status_error=None,
                 build_error=None, exit_error=None, client=None, calls=None):
        self.status = status
        self.kernels_status_error = kernels_status_error
        self.build_error = build_error
        self.exit_error = exit_error
        self._client = client
        self.status_calls = []
        self.build_calls = 0
        self.calls = calls if calls is not None else []

    def kernels_status(self, kernel):
        self.status_calls.append(kernel)
        if self.kernels_status_error:
            raise self.kernels_status_error
        return SimpleNamespace(status=_Enum(self.status))

    def build_kaggle_client(self):
        self.build_calls += 1
        if self.build_error:
            raise self.build_error
        return _Ctx(self._client, exit_error=self.exit_error)


def _file(name, url):
    return SimpleNamespace(file_name=name, url=url)


def test_init_makes_no_calls():
    api = FakeApi()
    src = KaggleOutputSource(api, "me/my-kernel")
    assert src.kernel == "me/my-kernel"
    assert api.status_calls == [] and api.build_calls == 0


def test_status_returns_name_once():
    api = FakeApi(status="RUNNING")
    src = KaggleOutputSource(api, "me/k")
    assert src.status() == "RUNNING"
    assert api.status_calls == ["me/k"]


def test_status_unknown_enum_rejected():
    api = FakeApi(status="WEIRD")
    src = KaggleOutputSource(api, "me/k")
    with pytest.raises(SnapshotError) as exc:
        src.status()
    assert str(exc.value) == "Kaggle output source failed"
    assert exc.value.__cause__ is None


@pytest.mark.parametrize("bad", ["me", "me/", "/k", "a/b/c", "me/a.b", "", 3])
def test_invalid_kernel_rejected_before_sdk(bad):
    api = FakeApi()
    with pytest.raises(SnapshotError):
        KaggleOutputSource(api, bad)
    assert api.build_calls == 0 and api.status_calls == []


@pytest.mark.parametrize("bad", [True, 0, 1001, "200", None, 1.5])
def test_invalid_page_size_rejected_before_sdk(bad):
    api = FakeApi()
    with pytest.raises(SnapshotError):
        KaggleOutputSource(api, "me/k", page_size=bad)
    assert api.build_calls == 0


def test_page_defaults_and_request_fields():
    client, calls = _client([_file("out/step1.parquet", "https://x/1")], "log-text", "tok2")
    api = FakeApi(client=client)
    src = KaggleOutputSource(api, "some_owner/some-slug", page_size=7)
    result = src.page(None)
    assert api.build_calls == 1
    req = calls[0]
    assert isinstance(req, ApiListKernelSessionOutputRequest)
    assert req.user_name == "some_owner"
    assert req.kernel_slug == "some-slug"
    assert req.page_size == 7
    assert req.page_token == ""
    assert req.version_label == ""
    assert result == {
        "files": [{"path": "out/step1.parquet", "url": "https://x/1"}],
        "log": "log-text",
        "next_page_token": "tok2",
    }


def test_page_second_call_uses_token_and_empty_files():
    client, calls = _client([], "", "")
    api = FakeApi(client=client)
    src = KaggleOutputSource(api, "me/k")
    out = src.page("abc")
    assert len(calls) == 1
    assert calls[0].page_token == "abc"
    assert calls[0].page_size == 200
    assert out == {"files": [], "log": "", "next_page_token": None}


@pytest.mark.parametrize("token", [1, b"x", True])
def test_invalid_token_rejected_before_sdk(token):
    client, calls = _client()
    api = FakeApi(client=client)
    src = KaggleOutputSource(api, "me/k")
    with pytest.raises(SnapshotError):
        src.page(token)
    assert calls == [] and api.build_calls == 0


@pytest.mark.parametrize("factory", [
    lambda: FakeApi(kernels_status_error=RuntimeError("boom")),
    lambda: FakeApi(build_error=RuntimeError("boom")),
])
def test_errors_wrapped_from_none(factory):
    api = factory()
    src = KaggleOutputSource(api, "me/k")
    fn = src.status if isinstance(api.kernels_status_error, RuntimeError) else lambda: src.page(None)
    with pytest.raises(SnapshotError) as exc:
        fn()
    assert str(exc.value) == "Kaggle output source failed"
    assert exc.value.__cause__ is None


def test_list_error_wrapped():
    client, _ = _client(list_error=SnapshotError("inner"))
    api = FakeApi(client=client)
    src = KaggleOutputSource(api, "me/k")
    with pytest.raises(SnapshotError) as exc:
        src.page(None)
    assert str(exc.value) == "Kaggle output source failed"
    assert exc.value.__cause__ is None


def test_context_exit_error_wrapped():
    client, _ = _client()
    api = FakeApi(client=client, exit_error=RuntimeError("exit"))
    src = KaggleOutputSource(api, "me/k")
    with pytest.raises(SnapshotError):
        src.page(None)


def test_keyboardinterrupt_propagates():
    client, _ = _client(list_error=KeyboardInterrupt())
    api = FakeApi(client=client)
    src = KaggleOutputSource(api, "me/k")
    with pytest.raises(KeyboardInterrupt):
        src.page(None)


def test_urls_not_in_error_message():
    api2 = FakeApi(client=_client(list_error=RuntimeError("e"))[0])
    src2 = KaggleOutputSource(api2, "me/k")
    with pytest.raises(SnapshotError) as exc:
        src2.page(None)
    msg = str(exc.value)
    assert "http" not in msg and "secret" not in msg

