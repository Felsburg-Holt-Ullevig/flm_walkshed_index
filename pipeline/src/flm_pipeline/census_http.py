"""Bounded Census HTTP requests with a key-free immutable local cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 32 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4
RETRY_DELAYS_SECONDS = (1, 2, 4)


class CensusRequestError(RuntimeError):
    """A sanitized request/cache failure without request URLs or credentials."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


@dataclass(frozen=True)
class CensusResponse:
    value: Any
    body_sha256: str
    body_bytes: int
    cache_key: str
    cache_hit: bool
    request_metadata: dict[str, Any]
    retrieved_at_utc: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _identity(endpoint: str, parameters: Iterable[tuple[str, str]], response_version: str) -> tuple[str, dict[str, Any]]:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise CensusRequestError("Census endpoint must be a clean HTTPS URL without query or fragment")
    if any(str(name).casefold() in {"key", "api_key", "apikey"} for name, _ in parameters):
        raise CensusRequestError("credential parameters are managed by the Census adapter and cannot enter cache identity")
    safe_request = {
        "method": "GET",
        "host": parsed.hostname.casefold(),
        "path": parsed.path,
        "parameters": [[str(key), str(value)] for key, value in parameters],
        "response_version": response_version,
    }
    identity = hashlib.sha256(_canonical_json(safe_request)).hexdigest()
    return identity, safe_request


def _read_cache(cache_root: Path, key: str, safe_request: dict[str, Any]) -> CensusResponse | None:
    body_path = cache_root / f"{key}.json"
    metadata_path = cache_root / f"{key}.meta.json"
    if not body_path.exists() and not metadata_path.exists():
        return None
    if not body_path.is_file() or not metadata_path.is_file():
        raise CensusRequestError("Census cache entry is incomplete; preserve it for inspection and use a new cache identity")
    try:
        if body_path.stat().st_size > MAX_RESPONSE_BYTES or metadata_path.stat().st_size > 1024 * 1024:
            raise CensusRequestError("Census cache object exceeds its size limit; preserve it for inspection")
    except OSError as error:
        raise CensusRequestError("Census cache entry cannot be inspected") from error
    try:
        body = body_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CensusRequestError("Census cache entry cannot be read; preserve it for inspection and use a new cache identity") from error
    digest = hashlib.sha256(body).hexdigest()
    if (
        not isinstance(metadata, dict)
        or metadata.get("cache_key") != key
        or metadata.get("request") != safe_request
        or metadata.get("sha256") != digest
        or metadata.get("bytes") != len(body)
        or len(body) > MAX_RESPONSE_BYTES
    ):
        raise CensusRequestError("Census cache identity or content check failed; preserve it for inspection")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CensusRequestError("Cached Census response is not valid UTF-8 JSON") from error
    retrieved = metadata.get("retrieved_at_utc")
    if not isinstance(retrieved, str):
        raise CensusRequestError("Census cache metadata has no retrieval timestamp")
    return CensusResponse(value, digest, len(body), key, True, safe_request, retrieved)


def _immutable_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_file() and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(payload).digest():
            return
        raise CensusRequestError("Refusing to replace an existing Census cache object")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _retry_after(headers: object) -> int | None:
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get("Retry-After")
    if not isinstance(raw, str):
        return None
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0, int((retry_at - datetime.now(UTC)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


def request_json(
    endpoint: str,
    parameters: Iterable[tuple[str, str]],
    cache_root: Path,
    *,
    response_version: str,
    requires_key: bool = False,
    api_key: str | None = None,
    opener: object | None = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    max_bytes: int = MAX_RESPONSE_BYTES,
    max_attempts: int = MAX_ATTEMPTS,
) -> CensusResponse:
    """Fetch JSON once per key-free request identity, retrying only transient failures."""
    params = tuple((str(key), str(value)) for key, value in parameters)
    key, safe_request = _identity(endpoint, params, response_version)
    cached = _read_cache(cache_root, key, safe_request)
    if cached is not None:
        return cached
    if requires_key and (not isinstance(api_key, str) or not api_key.strip()):
        raise CensusRequestError("A Census API key is required for an uncached ACS data request; set CENSUS_API_KEY locally")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not (1 <= max_attempts <= 4):
        raise ValueError("max_attempts must be between 1 and 4")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not (1 <= timeout_seconds <= 120):
        raise ValueError("timeout_seconds must be between 1 and 120")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not (1 <= max_bytes <= MAX_RESPONSE_BYTES):
        raise ValueError("max_bytes must be between 1 and 32 MiB")

    query_parameters = list(params)
    if requires_key:
        query_parameters.append(("key", str(api_key)))
    request_url = endpoint + "?" + urlencode(query_parameters)
    request = Request(request_url, headers={"Accept": "application/json", "User-Agent": "flm-walkshed-prototype/0.1"}, method="GET")
    http = opener if opener is not None else build_opener(_NoRedirect())
    transient = (TimeoutError, socket.timeout, URLError)
    last_status: int | None = None
    for attempt in range(max_attempts):
        try:
            with http.open(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    last_status = status
                    if status in {429, 500, 502, 503, 504} and attempt + 1 < max_attempts:
                        delay = _retry_after(getattr(response, "headers", None))
                        if delay is not None and delay > 60:
                            raise CensusRequestError("Census endpoint requested a retry delay longer than 60 seconds")
                        sleep(delay if delay is not None else RETRY_DELAYS_SECONDS[attempt])
                        continue
                    raise CensusRequestError(f"Census endpoint returned HTTP {status}")
                content_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
                if content_length is not None:
                    try:
                        if int(content_length) > max_bytes:
                            raise CensusRequestError("Census response exceeded the 32 MiB limit")
                    except ValueError:
                        raise CensusRequestError("Census response has an invalid Content-Length")
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > max_bytes:
                        raise CensusRequestError("Census response exceeded the 32 MiB limit")
                body = b"".join(chunks)
            if requires_key and isinstance(api_key, str) and len(api_key) >= 8 and api_key.encode("utf-8") in body:
                raise CensusRequestError("Census response unexpectedly contained the API key; response was not cached")
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise CensusRequestError("Census endpoint returned a non-JSON or malformed response") from error
            digest = hashlib.sha256(body).hexdigest()
            retrieved_at = datetime.now(UTC).isoformat()
            metadata = {
                "cache_key": key,
                "request": safe_request,
                "retrieved_at_utc": retrieved_at,
                "sha256": digest,
                "bytes": len(body),
                "http_status": 200,
            }
            _immutable_write(cache_root / f"{key}.json", body)
            _immutable_write(cache_root / f"{key}.meta.json", _canonical_json(metadata) + b"\n")
            return CensusResponse(value, digest, len(body), key, False, safe_request, retrieved_at)
        except HTTPError as error:
            last_status = int(error.code)
            if last_status in {429, 500, 502, 503, 504} and attempt + 1 < max_attempts:
                delay = _retry_after(error.headers)
                if delay is not None and delay > 60:
                    raise CensusRequestError("Census endpoint requested a retry delay longer than 60 seconds") from None
                sleep(delay if delay is not None else RETRY_DELAYS_SECONDS[attempt])
                continue
            raise CensusRequestError(f"Census endpoint returned HTTP {last_status}") from None
        except transient:
            if attempt + 1 < max_attempts:
                sleep(RETRY_DELAYS_SECONDS[attempt])
                continue
            raise CensusRequestError("Census endpoint timed out or could not be reached after retries") from None
        except CensusRequestError:
            raise
        except OSError:
            raise CensusRequestError("Census response could not be read or cached") from None
    if last_status is not None:
        raise CensusRequestError(f"Census endpoint returned HTTP {last_status} after retries")
    raise CensusRequestError("Census endpoint failed after retries")
