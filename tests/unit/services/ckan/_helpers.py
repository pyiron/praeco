import io
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

Reply = tuple[int, Mapping[str, str], bytes]


class RecordedBody(io.BytesIO):
    """Raw body of a recorded response that notes when it was released.

    `requests.Response.close` closes the raw body only if it was not read to
    the end, but always calls ``release_conn``.
    """

    def __init__(self, data: bytes):
        super().__init__(data)
        self.released = False

    def release_conn(self) -> None:
        self.released = True


class FakeRequest:
    def __init__(self, method: str):
        self.method = method


class FakeResponse:
    def __init__(
        self,
        *,
        url: str = "https://ckan.test/api/3/action/package_show",
        status_code: int = 200,
        text: str = "ok",
        json_value: Any = None,
        json_exc: Exception | None = None,
        request: FakeRequest | None = None,
        body: bytes = b"",
        chunks: list[bytes] | None = None,
    ):
        self.url = url
        self.status_code = status_code
        self.text = text
        self._json_value = json_value
        self._json_exc = json_exc
        self.request = request
        self._body = body
        self._chunks = chunks
        self.chunk_sizes: list[int] = []
        self.closed = False

    def json(self) -> Any:
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_value

    def iter_content(self, chunk_size: int = 1) -> Iterator[bytes]:
        """Yield `chunks` if given, else `body` split into `chunk_size` pieces."""
        self.chunk_sizes.append(chunk_size)
        if self._chunks is not None:
            yield from self._chunks
        else:
            for start in range(0, len(self._body), chunk_size):
                yield self._body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None):
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []
        self.responses = list(responses or [FakeResponse()])

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        response.url = url
        response.request = FakeRequest(method)
        return response


class RecordingAdapter(BaseAdapter):
    """Transport adapter that records prepared requests and never connects.

    Mount it on a real `requests.Session` for ``http://`` and ``https://``.
    `respond` maps each prepared request to a ``(status, headers, body)``
    reply. The prepared requests show the headers that would go on the wire,
    after `requests` merged the session and per-request headers and handled
    redirects.
    """

    def __init__(self, respond: Callable[[requests.PreparedRequest], Reply]):
        super().__init__()
        self.respond = respond
        self.requests: list[requests.PreparedRequest] = []
        self.streams: list[bool] = []
        self.bodies: list[RecordedBody] = []

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        self.requests.append(request)
        self.streams.append(stream)
        status, headers, body = self.respond(request)
        raw = RecordedBody(body)
        self.bodies.append(raw)
        response = requests.Response()
        response.status_code = status
        response.headers = CaseInsensitiveDict(headers)
        response.raw = raw
        response.url = str(request.url)
        response.request = request
        response.encoding = "utf-8"
        response.connection = self
        return response

    def close(self) -> None:
        return None


def recording_session(
    respond: Callable[[requests.PreparedRequest], Reply],
) -> tuple[requests.Session, RecordingAdapter]:
    """Return a real session whose HTTP(S) traffic goes to a recording adapter."""
    session = requests.Session()
    # Ignore proxies and .netrc credentials from the environment.
    session.trust_env = False
    adapter = RecordingAdapter(respond)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session, adapter
