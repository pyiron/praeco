import unittest

import requests

from praeco.exceptions import HttpError
from praeco.transport.request import (
    ERROR_TEXT_LIMIT,
    _raise_for_status_with_body,
    read_json,
    shorten_error_text,
)


class _FakeRequest:
    def __init__(self, method: str):
        self.method = method


class _FakeResponse:
    def __init__(
        self,
        *,
        url="https://example.test/api",
        status_code=200,
        text="body",
        request=None,
        json_exc=None,
        raise_for_status_exc=None,
        json_value=None,
    ):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.request = request
        self._json_exc = json_exc
        self._raise_for_status_exc = raise_for_status_exc
        self._json_value = json_value

        self.raise_for_status_called = False
        self.json_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True
        if self._raise_for_status_exc is not None:
            raise self._raise_for_status_exc
        return None

    def json(self):
        self.json_called = True
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_value


class TestShortenErrorText(unittest.TestCase):
    def test_short_text_is_returned_with_collapsed_whitespace(self):
        self.assertEqual(
            shorten_error_text("  Server\n\t unavailable  "),
            "Server unavailable",
        )

    def test_text_at_the_limit_is_not_cut(self):
        text = "x" * ERROR_TEXT_LIMIT

        self.assertEqual(shorten_error_text(text), text)

    def test_long_text_is_cut_and_reports_the_full_length(self):
        body = "<html>\n  <body>\n" + "a" * 500 + "\n  </body>\n</html>\n"

        message = shorten_error_text(body)

        collapsed = " ".join(body.split())
        self.assertEqual(
            message,
            f"{collapsed[:ERROR_TEXT_LIMIT]}... "
            f"({len(body)} characters; see response_text)",
            msg="the length refers to the full body, not the collapsed one",
        )

    def test_trailing_space_before_the_cut_is_removed(self):
        message = shorten_error_text("abc def", limit=4)

        self.assertEqual(message, "abc... (7 characters; see response_text)")


class TestRaiseForStatusWithBody(unittest.TestCase):
    def test_http_error_is_wrapped_as_http_error(self):
        resp = _FakeResponse(
            status_code=404,
            request=_FakeRequest("GET"),
            raise_for_status_exc=requests.HTTPError("404 Client Error"),
            text="Not Found",
        )

        with self.assertRaises(HttpError) as ctx:
            _raise_for_status_with_body(resp)

        err = ctx.exception
        self.assertEqual(err.method, "GET")
        self.assertEqual(err.url, "https://example.test/api")
        self.assertEqual(err.status_code, 404)
        self.assertIn("404", err.message)
        self.assertEqual(err.response_text, "Not Found")
        self.assertIsInstance(err.__cause__, requests.HTTPError)

    def test_missing_request_falls_back_to_http_method_label(self):
        resp = _FakeResponse(
            status_code=500,
            request=None,
            raise_for_status_exc=requests.HTTPError("500 Server Error"),
        )

        with self.assertRaises(HttpError) as ctx:
            _raise_for_status_with_body(resp)

        self.assertEqual(ctx.exception.method, "HTTP")


class TestReadJson(unittest.TestCase):
    def test_decodes_json_on_success(self):
        resp = _FakeResponse(
            status_code=200,
            request=_FakeRequest("POST"),
            json_value={"ok": True},
        )
        self.assertEqual(read_json(resp), {"ok": True})

    def test_http_error_happens_before_json_decode(self):
        # If status is bad, we should not attempt JSON decoding at all.
        resp = _FakeResponse(
            status_code=404,
            request=_FakeRequest("GET"),
            raise_for_status_exc=requests.HTTPError("404 Client Error"),
            json_exc=ValueError("bad json"),  # would happen if json() were called
            text="Not Found",
        )

        with self.assertRaises(HttpError) as ctx:
            _ = read_json(resp)

        self.assertTrue(resp.raise_for_status_called)
        self.assertFalse(
            resp.json_called,
            msg="read_json() should not attempt JSON decoding after HTTP status handling fails",
        )

        err = ctx.exception
        self.assertIsInstance(err.__cause__, requests.HTTPError)
        # Ensure we didn't take the JSON-decode error path
        self.assertNotEqual(err.message, "Failed to decode JSON response.")

    def test_value_error_from_json_is_wrapped(self):
        resp = _FakeResponse(
            status_code=200,
            request=_FakeRequest("GET"),
            json_exc=ValueError("bad json"),
            text="<<< not json >>>",
        )

        with self.assertRaises(HttpError) as ctx:
            _ = read_json(resp)

        err = ctx.exception
        self.assertEqual(err.method, "GET")
        self.assertEqual(err.status_code, 200)
        self.assertEqual(err.message, "Failed to decode JSON response.")
        self.assertEqual(err.response_text, "<<< not json >>>")
        self.assertIsInstance(err.__cause__, ValueError)

    def test_non_value_error_from_json_is_not_wrapped(self):
        # Regression test for narrowing "except Exception" -> "except ValueError"
        resp = _FakeResponse(
            status_code=200,
            request=_FakeRequest("GET"),
            json_exc=RuntimeError("boom"),
        )

        with self.assertRaises(RuntimeError):
            _ = read_json(resp)


if __name__ == "__main__":
    unittest.main()
