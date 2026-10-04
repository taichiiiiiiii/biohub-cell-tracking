"""Minimal adapter over an existing authenticated KaggleApi for session-output snapshots."""

from __future__ import annotations

import re

from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest

from biohub.kaggle_output_snapshot import SnapshotError

_KERNEL_RE = re.compile(r"\A[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\Z")
_ALLOWED_STATUS = frozenset(
    {
        "QUEUED",
        "RUNNING",
        "COMPLETE",
        "ERROR",
        "CANCEL_REQUESTED",
        "CANCEL_ACKNOWLEDGED",
        "NEW_SCRIPT",
    }
)


class KaggleOutputSource:
    """Read-only bridge from the snapshot protocol to a caller-provided KaggleApi.

    The API/client is never created, authenticated, or repaired here; no downloads
    are performed and returned URLs are held in memory only.
    """

    def __init__(self, api, kernel: str, *, page_size: int = 200) -> None:
        try:
            if not isinstance(kernel, str) or not _KERNEL_RE.match(kernel):
                raise ValueError("invalid kernel ref")
            if isinstance(page_size, bool) or not isinstance(page_size, int):
                raise ValueError("invalid page_size")
            if not 1 <= page_size <= 1000:
                raise ValueError("invalid page_size")
            owner, slug = kernel.split("/")
            self.kernel = kernel
            self._api = api
            self._owner = owner
            self._slug = slug
            self._size = page_size
        except Exception:
            raise SnapshotError("Kaggle output source failed") from None

    def status(self) -> str:
        try:
            response = self._api.kernels_status(self.kernel)
            name = response.status.name
            if name not in _ALLOWED_STATUS:
                raise ValueError("unknown session status")
            return name
        except Exception:
            raise SnapshotError("Kaggle output source failed") from None

    def page(self, token):
        try:
            if token is not None and not isinstance(token, str):
                raise ValueError("invalid page token")
            request = ApiListKernelSessionOutputRequest()
            request.user_name = self._owner
            request.kernel_slug = self._slug
            request.page_size = self._size
            if token is not None:
                request.page_token = token
            with self._api.build_kaggle_client() as client:
                response = client.kernels.kernels_api_client.list_kernel_session_output(
                    request
                )
            files = [
                {"path": item.file_name, "url": item.url}
                for item in (response.files or [])
            ]
            return {
                "files": files,
                "log": response.log,
                "next_page_token": response.next_page_token or None,
            }
        except Exception:
            raise SnapshotError("Kaggle output source failed") from None

