from __future__ import annotations

from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
import json

import pytest

from flm_pipeline.census_http import CensusRequestError, request_json
from flm_pipeline.census_sample import _previous_snapshot


class FakeResponse:
    status = 200

    def __init__(self, payload: bytes, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {}
        self.reads = 0

    def read(self, size: int = -1) -> bytes:
        self.reads += 1
        if not self.payload:
            return b""
        result = self.payload[:size]
        self.payload = self.payload[size:]
        return result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, values):
        self.values = list(values)
        self.requests = []
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        self.requests.append((request, timeout))
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def _http_error(code: int, headers: dict[str, str] | None = None) -> HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return HTTPError("https://api.census.gov/data/path?key=secret-key-value", code, "failure", message, None)


def test_authenticated_request_is_cached_without_key_in_cache_metadata(tmp_path: Path) -> None:
    payload = b'[["x"],["ok"]]'
    opener = FakeOpener([FakeResponse(payload)])
    delays = []
    first = request_json(
        "https://api.census.gov/data/example", [("get", "x")], tmp_path,
        response_version="fixture-1", requires_key=True, api_key="secret-key-value",
        opener=opener, sleep=delays.append,
    )
    assert first.value == [["x"], ["ok"]]
    assert not first.cache_hit
    assert "secret-key-value" in opener.requests[0][0].full_url
    cache_text = "".join(path.read_text(encoding="utf-8") for path in tmp_path.iterdir() if path.name.endswith(".meta.json"))
    assert "secret-key-value" not in cache_text
    assert "key" not in json.loads(next(tmp_path.glob("*.meta.json")).read_text(encoding="utf-8"))["request"]["parameters"]

    second = request_json(
        "https://api.census.gov/data/example", [("get", "x")], tmp_path,
        response_version="fixture-1", requires_key=True, api_key=None,
        opener=FakeOpener([]), sleep=delays.append,
    )
    assert second.cache_hit
    assert second.body_sha256 == first.body_sha256
    assert opener.calls == 1


def test_missing_key_blocks_only_uncached_data_requests(tmp_path: Path) -> None:
    with pytest.raises(CensusRequestError, match="Census API key is required"):
        request_json(
            "https://api.census.gov/data/example", [], tmp_path,
            response_version="fixture-1", requires_key=True,
        )


@pytest.mark.parametrize("status", [401, 403, 302])
def test_auth_and_redirect_errors_fail_without_retries_or_secret_leak(tmp_path: Path, status: int) -> None:
    opener = FakeOpener([_http_error(status)])
    delays = []
    with pytest.raises(CensusRequestError) as caught:
        request_json(
            "https://api.census.gov/data/example", [], tmp_path,
            response_version="fixture-1", requires_key=True, api_key="secret-key-value",
            opener=opener, sleep=delays.append,
        )
    assert "secret-key-value" not in str(caught.value)
    assert opener.calls == 1
    assert delays == []


def test_transient_http_failure_retries_with_bounded_backoff(tmp_path: Path) -> None:
    opener = FakeOpener([_http_error(429, {"Retry-After": "7"}), FakeResponse(b'{"ok":true}')])
    delays = []
    result = request_json(
        "https://api.census.gov/data/example", [], tmp_path,
        response_version="fixture-1", opener=opener, sleep=delays.append,
    )
    assert result.value == {"ok": True}
    assert opener.calls == 2
    assert delays == [7]

    long_wait = FakeOpener([_http_error(429, {"Retry-After": "61"}), FakeResponse(b'{"should_not_be_read":true}')])
    with pytest.raises(CensusRequestError, match="longer than 60 seconds"):
        request_json(
            "https://api.census.gov/data/long-wait", [], tmp_path,
            response_version="fixture-1", opener=long_wait, sleep=delays.append,
        )
    assert long_wait.calls == 1


def test_server_error_retries_but_other_client_errors_do_not(tmp_path: Path) -> None:
    server = FakeOpener([_http_error(503), FakeResponse(b'{"ok":true}')])
    delays = []
    result = request_json(
        "https://api.census.gov/data/server-error", [], tmp_path,
        response_version="fixture-1", opener=server, sleep=delays.append,
    )
    assert result.value == {"ok": True}
    assert server.calls == 2
    assert delays == [1]

    client = FakeOpener([_http_error(404)])
    with pytest.raises(CensusRequestError, match="HTTP 404"):
        request_json(
            "https://api.census.gov/data/not-found", [], tmp_path,
            response_version="fixture-1", opener=client, sleep=delays.append,
        )
    assert client.calls == 1


def test_malformed_json_and_oversize_responses_fail(tmp_path: Path) -> None:
    with pytest.raises(CensusRequestError, match="non-JSON"):
        request_json(
            "https://api.census.gov/data/malformed", [], tmp_path,
            response_version="fixture-1", opener=FakeOpener([FakeResponse(b"<html>error</html>")]),
        )
    with pytest.raises(CensusRequestError, match="32 MiB limit"):
        request_json(
            "https://api.census.gov/data/large", [], tmp_path,
            response_version="fixture-1", max_bytes=3,
            opener=FakeOpener([FakeResponse(b"1234")]),
        )


def test_204_and_empty_success_are_not_valid_data(tmp_path: Path) -> None:
    response = FakeResponse(b"")
    response.status = 204
    with pytest.raises(CensusRequestError, match="HTTP 204"):
        request_json(
            "https://api.census.gov/data/no-content", [], tmp_path,
            response_version="fixture-1", opener=FakeOpener([response]),
        )
    with pytest.raises(CensusRequestError, match="non-JSON"):
        request_json(
            "https://api.census.gov/data/empty", [], tmp_path,
            response_version="fixture-1", opener=FakeOpener([FakeResponse(b"")]),
        )


def test_timeout_retries_then_succeeds_and_exhaustion_is_bounded(tmp_path: Path) -> None:
    delays = []
    opener = FakeOpener([TimeoutError(), TimeoutError(), FakeResponse(b'{"ok":true}')])
    result = request_json(
        "https://api.census.gov/data/retry", [], tmp_path,
        response_version="fixture-1", opener=opener, sleep=delays.append,
    )
    assert result.value == {"ok": True}
    assert delays == [1, 2]

    delays.clear()
    exhausted = FakeOpener([TimeoutError(), TimeoutError(), TimeoutError(), TimeoutError()])
    with pytest.raises(CensusRequestError, match="after retries"):
        request_json(
            "https://api.census.gov/data/exhausted", [], tmp_path,
            response_version="fixture-1", opener=exhausted, sleep=delays.append,
        )
    assert exhausted.calls == 4
    assert delays == [1, 2, 4]


def test_cancellation_propagates_without_writing_cache(tmp_path: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        request_json(
            "https://api.census.gov/data/cancel", [], tmp_path,
            response_version="fixture-1", opener=FakeOpener([KeyboardInterrupt()]),
        )
    assert list(tmp_path.iterdir()) == []


def test_response_echoing_key_is_never_cached(tmp_path: Path) -> None:
    with pytest.raises(CensusRequestError, match="contained the API key"):
        request_json(
            "https://api.census.gov/data/echo", [], tmp_path,
            response_version="fixture-1", requires_key=True, api_key="secret-key-value",
            opener=FakeOpener([FakeResponse(b'{"error":"secret-key-value"}')]),
        )
    assert list(tmp_path.iterdir()) == []


def test_cache_corruption_fails_without_silent_replacement(tmp_path: Path) -> None:
    opener = FakeOpener([FakeResponse(b'{"ok":true}')])
    response = request_json(
        "https://api.census.gov/data/cache", [("q", "1")], tmp_path,
        response_version="fixture-1", opener=opener,
    )
    (tmp_path / f"{response.cache_key}.json").write_bytes(b"corrupt")
    with pytest.raises(CensusRequestError, match="identity or content check failed"):
        request_json(
            "https://api.census.gov/data/cache", [("q", "1")], tmp_path,
            response_version="fixture-1", opener=FakeOpener([]),
        )


def test_explicit_cache_snapshot_revision_reports_content_change(tmp_path: Path) -> None:
    first = request_json(
        "https://api.census.gov/data/refresh", [("get", "x")], tmp_path,
        response_version="normalizer-1:snapshot-1", opener=FakeOpener([FakeResponse(b'{"value":1}')]),
    )
    second = request_json(
        "https://api.census.gov/data/refresh", [("get", "x")], tmp_path,
        response_version="normalizer-1:snapshot-2", opener=FakeOpener([FakeResponse(b'{"value":2}')]),
    )
    previous = _previous_snapshot(tmp_path, second.request_metadata, second.body_sha256)
    assert previous is not None
    assert previous["sha256"] == first.body_sha256
    assert previous["content_changed"] is True
