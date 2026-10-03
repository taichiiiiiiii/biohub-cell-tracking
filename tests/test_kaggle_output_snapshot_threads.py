"""Real snapshot + range_size + download + ThreadPoolExecutor integration test (fake HTTP only)."""

import hashlib
import json
import threading

import biohub.kaggle_output_snapshot as m

DATA = {"a.bin": b"AAA", "b.bin": b"BBBBB"}
KERNEL = "owner/slug"


class Response:
    def __init__(self, status_code, headers, body=b"", chunks=None):
        self.status_code = status_code
        self.headers = headers
        self.raw = self
        self._body = body
        self._chunks = chunks or []
        self.closed = 0

    def read(self, n):
        return self._body[:n]

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        self.closed += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class Source:
    def __init__(self):
        self.kernel = KERNEL
        self.tokens = []

    def status(self):
        return "COMPLETE"

    def page(self, token):
        self.tokens.append(token)
        name = "a.bin" if token is None else "b.bin"
        return {
            "files": [{"path": name, "url": "https://example.invalid/" + name}],
            "log": "ok",
            "next_page_token": "p2" if token is None else None,
        }


def test_snapshot_uses_worker_threads_for_size_and_main_thread_for_download(tmp_path):
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    size_ids, dl_ids, responses, ranges, fulls = [], [], [], [], []
    main = threading.get_ident()

    def fakeget(url, *, stream, allow_redirects, headers, timeout):
        assert stream is True and allow_redirects is False
        assert headers.get("Accept-Encoding") == "identity"
        assert headers.get("Range") in (None, "bytes=0-0")
        name = url.rsplit("/", 1)[-1]
        assert url == "https://example.invalid/" + name
        if headers.get("Range") == "bytes=0-0":
            with lock:
                size_ids.append(threading.get_ident())
            barrier.wait(timeout=5)
            resp = Response(206, {"Content-Range": f"bytes 0-0/{len(DATA[name])}"}, DATA[name][:1])
            with lock:
                ranges.append(url)
                responses.append(resp)
            return resp
        with lock:
            fulls.append(url)
            dl_ids.append(threading.get_ident())
            resp = Response(200, {"Content-Length": str(len(DATA[name]))}, chunks=[DATA[name]])
            responses.append(resp)
        return resp

    out = tmp_path / "out"
    src = Source()
    receipt = m.snapshot(src, out, ["a.bin", "b.bin"],
                         limits=m.Limits(io_threads=2, seconds=20), get=fakeget)

    assert len(size_ids) == 2 and len(set(size_ids)) == 2
    assert all(t != main for t in size_ids)
    assert dl_ids and all(t == main for t in dl_ids)
    assert len(ranges) == 2 and len(fulls) == 2
    assert all(r.closed >= 1 for r in responses)

    files = sorted(receipt["files"], key=lambda f: f["path"])
    assert [f["path"] for f in files] == ["a.bin", "b.bin"]
    assert [f["bytes"] for f in files] == [3, 5]
    assert set(files[0]) == {"path", "bytes"}
    assert set(files[1]) == {"path", "bytes"}

    assert (out / "a.bin").read_bytes() == DATA["a.bin"]
    assert (out / "b.bin").read_bytes() == DATA["b.bin"]

    downloaded = {entry["path"]: entry for entry in receipt["downloaded"]}
    assert downloaded["a.bin"]["sha256"] == hashlib.sha256(DATA["a.bin"]).hexdigest()
    assert downloaded["b.bin"]["sha256"] == hashlib.sha256(DATA["b.bin"]).hexdigest()
    for entry in receipt["downloaded"]:
        assert set(entry) == {"path", "bytes", "sha256"}

    assert receipt["downloaded_bytes"] == 10
    assert (out / "slug.log").read_bytes() == b"ok"
    assert not (out / "SNAPSHOT_ERROR.json").exists()

    inv = json.loads((out / "INVENTORY.json").read_text())
    assert inv == json.loads(json.dumps(receipt))

    assert src.tokens == [None, "p2", None, "p2"]

