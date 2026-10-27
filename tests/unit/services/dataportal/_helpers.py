from collections.abc import Iterator
from typing import Any


class FakeResponse:
    def __init__(
        self,
        *,
        json_value: Any = None,
        status_code: int = 200,
        body: bytes = b"",
    ):
        self.url = "https://dataportal.material-digital.de"
        self.status_code = status_code
        self.text = ""
        self.request = None
        self._json_value = json_value
        self._body = body
        self.closed = False

    def json(self) -> Any:
        return self._json_value

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1) -> Iterator[bytes]:
        """Yield `body` split into `chunk_size` pieces."""
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Session double that records requests.

    Without `responses`, every request returns the same `response`. With
    `responses`, each request returns the next one in order.
    """

    def __init__(self, responses: list[FakeResponse] | None = None):
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []
        self.response = FakeResponse()
        self.responses = None if responses is None else list(responses)

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.response if self.responses is None else self.responses.pop(0)
        response.url = url
        return response
