"""Minimal JSON-over-HTTPS helper on the standard library (no requests/httpx dependency)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import ProviderError


def post_json(url: str, payload: dict, headers: dict[str, str], *, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    return _send(req, timeout)


def post_multipart(
    url: str,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    content: bytes,
    mime_type: str,
    headers: dict[str, str],
    *,
    timeout: float = 120.0,
) -> dict:
    boundary = "studybuddy-boundary-7f3a9c"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    for k, v in headers.items():
        req.add_header(k, v)
    return _send(req, timeout)


def _send(req: urllib.request.Request, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URL comes from config)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise ProviderError(f"HTTP {exc.code} from {req.full_url.split('?')[0]}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProviderError(f"request to {req.full_url.split('?')[0]} failed: {exc}") from exc
