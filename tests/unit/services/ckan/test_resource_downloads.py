"""Tests for `client.resources.download` and `download_all`.

The expected behavior comes from the approved API of #106: the token rule
(D2), local file names (D3), the size check (D4), the local checks and the
error handling.
"""

import contextlib
import json
import os
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from urllib.parse import quote

import requests

from praeco.exceptions import HttpError, ValidationError
from praeco.services.ckan import CkanClient
from praeco.services.ckan._download import is_safe_file_name, sends_token
from praeco.services.ckan.exceptions import CkanApiError
from praeco.services.ckan.models import CkanPackageInfo, CkanResourceInfo

from ._helpers import FakeResponse, FakeSession, Reply, recording_session

TOKEN = "secret-token"
OWN_URL = "https://ckan.test/dataset/pkg-1/resource/res-1/download/data.ttl"
OTHER_URL = "https://files.example.test/storage/data.ttl"

RESERVED_NAMES = (
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{digit}" for digit in range(1, 10)]
    + [f"LPT{digit}" for digit in range(1, 10)]
)

# Names that break a D3 rule. 256 bytes in UTF-8 but only 130 characters.
TOO_LONG_TWO_BYTE = "é" * 126 + "abcd"
TOO_LONG_THREE_BYTE = "€" * 85 + "a"
UNSAFE_NAMES = (
    ["", ".", ".."]
    + [f"a{character}b.ttl" for character in '/\\:*?"<>|']
    + [f"a{chr(code)}b.ttl" for code in [*range(0x20), 0x7F]]
    + ["data.", "data.ttl.", "data.ttl ", "data ", "data. ", "data .", " "]
    + RESERVED_NAMES
    + [name.lower() for name in RESERVED_NAMES]
    + [name[0] + name[1:].lower() for name in RESERVED_NAMES]
    + [f"{name}.txt" for name in RESERVED_NAMES]
    + [f"{name.lower()}.tar.gz" for name in RESERVED_NAMES]
    + [TOO_LONG_TWO_BYTE, TOO_LONG_THREE_BYTE, "a" * 256]
)

# Names close to a D3 rule that are safe. Each is short enough in characters
# to stay below the Windows path length limit when written to disk.
EXACTLY_255_BYTES_TWO_BYTE = "é" * 125 + "abcde"
EXACTLY_255_BYTES_THREE_BYTE = "€" * 85
SAFE_NAMES = [
    "data.ttl",
    ".hidden",
    "a..b.ttl",
    " leading-space.ttl",
    "data ttl",
    "été.ttl",
    "100%.ttl",
    "CONSOLE",
    "CON-data.txt",
    "AUXILIARY.txt",
    "data.CON",
    "x.nul",
    "COM10",
    "lpt10.txt",
    EXACTLY_255_BYTES_TWO_BYTE,
    EXACTLY_255_BYTES_THREE_BYTE,
]


def resource(
    resource_id: str = "res-1",
    *,
    url: str | None = OWN_URL,
    url_type: str | None = "upload",
    **extra: Any,
) -> dict[str, Any]:
    """Build a `resource_show` result; `url=None` omits the URL."""
    payload: dict[str, Any] = {
        "id": resource_id,
        "package_id": "pkg-1",
        "name": "Data",
        "url_type": url_type,
    }
    if url is not None:
        payload["url"] = url
    payload.update(extra)
    return payload


def package(*resources: dict[str, Any], package_id: str = "pkg-1") -> dict[str, Any]:
    return {"id": package_id, "name": "dataset", "resources": list(resources)}


def action(result: Any) -> FakeResponse:
    return FakeResponse(json_value={"success": True, "result": result})


def content(data: bytes) -> FakeResponse:
    return FakeResponse(body=data)


def error_response(status_code: int) -> FakeResponse:
    return FakeResponse(
        status_code=status_code,
        text="<html><body>Access denied</body></html>",
        json_exc=ValueError("not JSON"),
    )


def make_client(
    responses: list[FakeResponse], **kwargs: Any
) -> tuple[CkanClient, FakeSession]:
    session = FakeSession(responses)
    return CkanClient("ckan.test", session=cast(Any, session), **kwargs), session


def upload_url(name: str) -> str:
    return f"https://ckan.test/dataset/pkg-1/resource/res/download/{name}"


def tree(root: Path) -> list[str]:
    """Return every path below `root`, including hidden temporary files."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


class _TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def fresh_directory(self) -> Path:
        """Return a new empty directory for one subtest."""
        directory = Path(self._tmp.name) / f"case-{len(list(self.root.iterdir()))}"
        directory.mkdir()
        return directory

    def symlink(self, link: Path, destination: Path) -> None:
        try:
            link.symlink_to(destination)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")


class TestDownloadRequests(_TempDirTestCase):
    """Criterion 2: request counts and order."""

    def test_download_shows_resource_then_streams_content(self):
        response = content(b"@prefix x: <https://example.test/> .")
        c, session = make_client([action(resource()), response])

        path = c.resources.download("res-1", directory=self.root)

        self.assertEqual(path, self.root / "data.ttl")
        self.assertEqual(path.read_bytes(), b"@prefix x: <https://example.test/> .")
        self.assertEqual(tree(self.root), ["data.ttl"])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["method"], "POST")
        self.assertEqual(
            session.calls[0]["url"], "https://ckan.test/api/3/action/resource_show"
        )
        self.assertEqual(session.calls[0]["json"], {"id": "res-1"})
        self.assertEqual(session.calls[1]["method"], "GET")
        self.assertEqual(session.calls[1]["url"], OWN_URL)
        self.assertIs(session.calls[1]["stream"], True)
        self.assertTrue(response.closed)

    def test_download_shows_a_resource_model_again_and_uses_fresh_metadata(self):
        stale = CkanResourceInfo.from_dict(
            resource("res-2", url="https://ckan.test/old/stale.ttl", size=1)
        )
        fresh = resource("res-2", url=upload_url("fresh.ttl"), size=3)
        c, session = make_client([action(fresh), content(b"abc")])

        path = c.resources.download(stale, directory=self.root)

        self.assertEqual(path, self.root / "fresh.ttl")
        self.assertEqual(path.read_bytes(), b"abc")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(
            session.calls[0]["url"], "https://ckan.test/api/3/action/resource_show"
        )
        self.assertEqual(session.calls[0]["json"], {"id": "res-2"})
        self.assertEqual(session.calls[1]["url"], upload_url("fresh.ttl"))

    def test_content_request_uses_client_timeout_and_verify(self):
        c, session = make_client(
            [action(resource()), content(b"abc")], timeout=(3.0, 7.0), verify=False
        )

        _ = c.resources.download("res-1", directory=self.root)

        get = session.calls[1]
        self.assertEqual(get["timeout"], (3.0, 7.0))
        self.assertIs(get["verify"], False)
        self.assertIs(get["stream"], True)
        self.assertIs(get.get("allow_redirects", True), True)

    def test_returned_path_joins_directory_and_name_without_resolving(self):
        (self.root / "sub").mkdir()
        for directory in (str(self.root / "sub" / ".."), self.root / "sub" / ".."):
            with self.subTest(directory=type(directory).__name__):
                c, _ = make_client([action(resource()), content(b"abc")])

                path = c.resources.download(
                    "res-1", directory=directory, overwrite=True
                )

                self.assertEqual(path, Path(directory) / "data.ttl")
                self.assertIn("..", path.parts)
                self.assertEqual((self.root / "data.ttl").read_bytes(), b"abc")

    def test_default_directory_is_current_directory(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        c, _ = make_client(
            [
                action(resource()),
                content(b"abc"),
                action(package(resource())),
                content(b"abc"),
            ]
        )

        path = c.resources.download("res-1")
        os.remove(path)
        paths = c.resources.download_all("pkg-1")

        self.assertEqual(path, Path(".") / "data.ttl")
        self.assertEqual(paths, [Path(".") / "data.ttl"])
        self.assertEqual((self.root / "data.ttl").read_bytes(), b"abc")

    def test_missing_directory_is_created(self):
        directory = self.root / "new" / "deeper"
        c, _ = make_client([action(resource()), content(b"abc")])

        path = c.resources.download("res-1", directory=directory)

        self.assertEqual(path, directory / "data.ttl")
        self.assertEqual(path.read_bytes(), b"abc")

    def test_download_all_shows_package_then_streams_each_upload_in_order(self):
        resources = [
            resource("res-b", url=upload_url("b.ttl")),
            resource("link-missing", url="https://other.test/b.ttl", url_type=None),
            resource("res-a", url=upload_url("a.ttl")),
            resource("link-empty", url="https://other.test/a.ttl", url_type=""),
            resource("res-c", url=upload_url("c.ttl")),
            resource("other-type", url=upload_url("x.ttl"), url_type="datastore"),
        ]
        del resources[1]["url_type"]
        c, session = make_client(
            [
                action(package(*resources)),
                content(b"B"),
                content(b"A"),
                content(b"C"),
            ]
        )

        paths = c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(
            paths,
            [self.root / "b.ttl", self.root / "a.ttl", self.root / "c.ttl"],
        )
        self.assertEqual(tree(self.root), ["a.ttl", "b.ttl", "c.ttl"])
        self.assertEqual((self.root / "b.ttl").read_bytes(), b"B")
        self.assertEqual((self.root / "a.ttl").read_bytes(), b"A")
        self.assertEqual((self.root / "c.ttl").read_bytes(), b"C")
        self.assertEqual(len(session.calls), 4)
        self.assertEqual(
            session.calls[0]["url"], "https://ckan.test/api/3/action/package_show"
        )
        self.assertEqual(session.calls[0]["json"], {"id": "pkg-1"})
        self.assertEqual(
            [(call["method"], call["url"]) for call in session.calls[1:]],
            [
                ("GET", upload_url("b.ttl")),
                ("GET", upload_url("a.ttl")),
                ("GET", upload_url("c.ttl")),
            ],
        )
        self.assertTrue(all(call["stream"] is True for call in session.calls[1:]))

    def test_download_all_accepts_a_package_model(self):
        model = CkanPackageInfo.from_dict(package(package_id="pkg-2"))
        c, session = make_client(
            [action(package(resource(), package_id="pkg-2")), content(b"abc")]
        )

        paths = c.resources.download_all(model, directory=self.root)

        self.assertEqual(paths, [self.root / "data.ttl"])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["json"], {"id": "pkg-2"})

    def test_download_all_ignores_link_resources_with_bad_urls_or_names(self):
        resources = [
            resource("res-1", url=upload_url("data.ttl")),
            resource("link-1", url="ftp://other.test/data.ttl", url_type=""),
            resource("link-2", url=None, url_type=None),
            resource("link-3", url="https://other.test/data.ttl", url_type=""),
            resource("CON", url="https://other.test/", url_type=""),
        ]
        c, session = make_client([action(package(*resources)), content(b"abc")])

        paths = c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(paths, [self.root / "data.ttl"])
        self.assertEqual(len(session.calls), 2)

    def test_download_all_without_uploads_returns_empty_list_after_one_request(self):
        packages = {
            "no resources": package(),
            "links only": package(
                resource("link-1", url="https://other.test/a.ttl", url_type="")
            ),
        }
        for label, payload in packages.items():
            for directory in (self.root, self.root / "missing"):
                with self.subTest(package=label, directory=directory.name):
                    c, session = make_client([action(payload)])

                    paths = c.resources.download_all("pkg-1", directory=directory)

                    self.assertEqual(paths, [])
                    self.assertEqual(len(session.calls), 1)
                    # Nothing is written, and a missing directory is not created.
                    self.assertEqual(tree(self.root), [])

    def test_download_all_without_uploads_still_rejects_a_file_as_directory(self):
        file_path = self.root / "file.txt"
        file_path.write_text("keep")
        packages = {
            "no resources": package(),
            "links only": package(
                resource("link-1", url="https://other.test/a.ttl", url_type="")
            ),
        }
        for label, payload in packages.items():
            for overwrite in (False, True):
                with self.subTest(package=label, overwrite=overwrite):
                    c, session = make_client([action(payload)])

                    with self.assertRaises(FileExistsError):
                        c.resources.download_all(
                            "pkg-1", directory=file_path, overwrite=overwrite
                        )

                    self.assertEqual(len(session.calls), 1)
                    self.assertEqual(tree(self.root), ["file.txt"])
                    self.assertEqual(file_path.read_text(), "keep")

    def test_download_all_names_files_like_download(self):
        resources = [
            resource("res-1", url=upload_url("my%20data.ttl")),
            resource("res-2", url=upload_url("CON.ttl")),
        ]
        c, _ = make_client([action(package(*resources)), content(b"1"), content(b"2")])

        paths = c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(paths, [self.root / "my data.ttl", self.root / "res-2"])

    def test_download_all_keeps_earlier_files_when_a_later_one_fails(self):
        resources = [
            resource("res-1", url=upload_url("a.ttl"), size=1),
            resource("res-2", url=upload_url("b.ttl"), size=1),
        ]
        failures = {
            "content error": error_response(500),
            "size mismatch": content(b"too long"),
        }
        for label, failure in failures.items():
            with self.subTest(failure=label):
                directory = self.fresh_directory()
                c, session = make_client(
                    [action(package(*resources)), content(b"A"), failure]
                )

                with self.assertRaises((CkanApiError, ValidationError)):
                    c.resources.download_all("pkg-1", directory=directory)

                self.assertEqual(tree(directory), ["a.ttl"])
                self.assertEqual((directory / "a.ttl").read_bytes(), b"A")
                self.assertEqual(len(session.calls), 3)
                self.assertTrue(failure.closed)


def json_reply(result: Any) -> Reply:
    body = json.dumps({"success": True, "result": result}).encode()
    return 200, {"Content-Type": "application/json"}, body


def responder(
    result: Any,
    replies: Mapping[str, Reply] | None = None,
    *,
    default: Reply = (200, {}, b"content"),
) -> Callable[[requests.PreparedRequest], Reply]:
    """Answer action calls with `result`, other requests by prepared URL."""
    by_url = dict(replies or {})

    def respond(request: requests.PreparedRequest) -> Reply:
        if request.method == "POST":
            return json_reply(result)
        return by_url.get(str(request.url), default)

    return respond


class TestTokenRule(_TempDirTestCase):
    """Criterion 3, on a real `requests.Session` with a recording adapter."""

    def download(
        self, url: str, *, address: str = "ckan.test"
    ) -> list[requests.PreparedRequest]:
        """Download a resource whose content URL is `url`; return the requests."""
        session, adapter = recording_session(responder(resource(url=url)))
        c = CkanClient(address, api_token=TOKEN, session=session)
        directory = self.fresh_directory()

        path = c.resources.download("res-1", directory=directory)

        self.assertEqual(path.read_bytes(), b"content")
        self.assertEqual([r.method for r in adapter.requests], ["POST", "GET"])
        self.assertEqual(adapter.requests[0].headers.get("Authorization"), TOKEN)
        self.assertIs(adapter.streams[1], True)
        return adapter.requests

    def test_token_is_sent_to_the_clients_own_origin(self):
        cases = [
            ("ckan.test", OWN_URL),
            ("ckan.test", "https://ckan.test:443/download/data.ttl"),
            ("ckan.test", "https://CKAN.Test/download/data.ttl"),
            ("CKAN.Test", "https://ckan.test/download/data.ttl"),
            ("ckan.test", "https://ckan.test/download/data.ttl?format=ttl#top"),
            ("https://ckan.test:443", "https://ckan.test/download/data.ttl"),
            ("http://ckan.test", "http://ckan.test/download/data.ttl"),
            ("http://ckan.test", "http://ckan.test:80/download/data.ttl"),
            ("ckan.test:8443", "https://ckan.test:8443/download/data.ttl"),
        ]
        for address, url in cases:
            with self.subTest(address=address, url=url):
                requests_sent = self.download(url, address=address)

                self.assertEqual(requests_sent[1].headers.get("Authorization"), TOKEN)

    def test_token_is_not_sent_to_another_origin(self):
        cases = [
            ("ckan.test", OTHER_URL),
            ("ckan.test", "https://sub.ckan.test/download/data.ttl"),
            ("ckan.test", "https://ckan.test.example.test/download/data.ttl"),
            ("ckan.test", "https://ckan.test@files.example.test/data.ttl"),
            ("ckan.test", "https://ckan.test:8443/download/data.ttl"),
            ("ckan.test", "https://ckan.test:80/download/data.ttl"),
            ("ckan.test", "http://ckan.test/download/data.ttl"),
            ("ckan.test", "http://ckan.test:443/download/data.ttl"),
            ("http://ckan.test", "https://ckan.test/download/data.ttl"),
            ("ckan.test:8443", "https://ckan.test/download/data.ttl"),
        ]
        for address, url in cases:
            with self.subTest(address=address, url=url):
                requests_sent = self.download(url, address=address)

                self.assertNotIn("Authorization", requests_sent[1].headers)

    def test_token_is_dropped_for_one_request_only(self):
        urls = iter([OTHER_URL, OWN_URL])

        def respond(request: requests.PreparedRequest) -> Reply:
            if request.method == "POST":
                return json_reply(resource(url=next(urls)))
            return 200, {}, b"content"

        session, adapter = recording_session(respond)
        c = CkanClient("ckan.test", api_token=TOKEN, session=session)

        _ = c.resources.download("res-1", directory=self.fresh_directory())
        _ = c.resources.download("res-1", directory=self.fresh_directory())

        self.assertEqual(session.headers.get("Authorization"), TOKEN)
        self.assertEqual(
            [r.headers.get("Authorization") for r in adapter.requests],
            [TOKEN, None, TOKEN, TOKEN],
        )

    def test_token_is_not_sent_on_a_redirect_to_another_host(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                respond = responder(
                    resource(url=OWN_URL),
                    {OWN_URL: (status, {"Location": OTHER_URL}, b"")},
                    default=(200, {}, b"redirected content"),
                )
                session, adapter = recording_session(respond)
                c = CkanClient("ckan.test", api_token=TOKEN, session=session)
                directory = self.fresh_directory()

                path = c.resources.download("res-1", directory=directory)

                self.assertEqual(path.read_bytes(), b"redirected content")
                self.assertEqual(
                    [(r.method, r.url) for r in adapter.requests],
                    [
                        ("POST", "https://ckan.test/api/3/action/resource_show"),
                        ("GET", OWN_URL),
                        ("GET", OTHER_URL),
                    ],
                )
                self.assertEqual(
                    adapter.requests[1].headers.get("Authorization"), TOKEN
                )
                self.assertNotIn("Authorization", adapter.requests[2].headers)

    def test_download_all_applies_the_token_rule_per_upload(self):
        resources = [
            resource("res-1", url=upload_url("own.ttl")),
            resource("res-2", url="https://files.example.test/other.ttl"),
        ]
        session, adapter = recording_session(responder(package(*resources)))
        c = CkanClient("ckan.test", api_token=TOKEN, session=session)

        paths = c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(paths, [self.root / "own.ttl", self.root / "other.ttl"])
        self.assertEqual(
            [r.headers.get("Authorization") for r in adapter.requests],
            [TOKEN, TOKEN, None],
        )

    def test_content_responses_are_released_on_a_real_session(self):
        for url, status in ((OWN_URL, 200), (OTHER_URL, 200), (OTHER_URL, 403)):
            with self.subTest(url=url, status=status):
                respond = responder(
                    resource(url=url), default=(status, {}, b"<html>body</html>")
                )
                session, adapter = recording_session(respond)
                c = CkanClient("ckan.test", api_token=TOKEN, session=session)
                directory = self.fresh_directory()

                try:
                    c.resources.download("res-1", directory=directory)
                except CkanApiError as exc:
                    self.assertEqual(exc.status_code, 403)
                else:
                    self.assertEqual(status, 200)

                body = adapter.bodies[1]
                self.assertTrue(body.released or body.closed)

    def test_client_without_token_sends_no_authorization(self):
        session, adapter = recording_session(responder(resource(url=OWN_URL)))
        c = CkanClient("ckan.test", session=session)

        _ = c.resources.download("res-1", directory=self.root)

        self.assertEqual(
            ["Authorization" in r.headers for r in adapter.requests], [False, False]
        )

    def test_origins_that_cannot_be_determined_never_match(self):
        # The download validates content URLs first, so the URL cases are
        # checked on the helper.
        cases = [
            ("https://ckan.test:abc", "https://ckan.test/data.ttl"),
            ("https://ckan.test:abc", "https://ckan.test:abc/data.ttl"),
            ("https://ckan.test:99999", "https://ckan.test:99999/data.ttl"),
            ("https://ckan.test", "https://ckan.test:abc/data.ttl"),
            ("ftp://ckan.test", "ftp://ckan.test/data.ttl"),
            ("https://ckan.test", "ftp://ckan.test/data.ttl"),
            ("https://ckan.test", "https:///data.ttl"),
            ("https://ckan.test", "/data.ttl"),
        ]
        for base_url, url in cases:
            with self.subTest(base_url=base_url, url=url):
                self.assertFalse(sends_token(url, base_url))

    def test_unparsable_base_url_port_withholds_the_token(self):
        session = FakeSession(
            [action(resource(url="https://ckan.test/data.ttl")), content(b"abc")]
        )
        c = CkanClient("ckan.test:abc", api_token=TOKEN, session=cast(Any, session))

        _ = c.resources.download("res-1", directory=self.root)

        self.assertEqual(session.calls[1]["headers"], {"Authorization": None})


class TestContentUrl(_TempDirTestCase):
    """Criterion 4: invalid content URLs fail before any content request."""

    INVALID_URLS = [
        None,
        "",
        "ftp://ckan.test/data.ttl",
        "file:///tmp/data.ttl",
        "mailto:someone@ckan.test",
        "data.ttl",
        "/dataset/pkg-1/resource/res-1/download/data.ttl",
        "//ckan.test/data.ttl",
        "https:///data.ttl",
        "https://:443/data.ttl",
        "https://ckan.test:abc/data.ttl",
        "https://ckan.test:99999/data.ttl",
    ]

    def test_invalid_content_url_raises_before_content_request(self):
        for url in self.INVALID_URLS:
            for filename in (None, "data.ttl"):
                with self.subTest(url=url, filename=filename):
                    c, session = make_client([action(resource(url=url))])

                    with self.assertRaises(ValidationError):
                        c.resources.download(
                            "res-1", directory=self.root, filename=filename
                        )

                    self.assertEqual(len(session.calls), 1)
                    self.assertEqual(tree(self.root), [])

    def test_download_all_checks_every_upload_before_the_first_content_request(self):
        for url in self.INVALID_URLS:
            with self.subTest(url=url):
                resources = [
                    resource("res-1", url=upload_url("a.ttl")),
                    resource("res-2", url=url),
                ]
                c, session = make_client([action(package(*resources))])

                with self.assertRaises(ValidationError):
                    c.resources.download_all("pkg-1", directory=self.root)

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])


class TestFileNames(_TempDirTestCase):
    """Criterion 5: local file names follow D3."""

    def test_unsafe_filename_raises_before_any_request(self):
        for name in UNSAFE_NAMES:
            with self.subTest(name=name):
                c, session = make_client([action(resource()), content(b"abc")])

                with self.assertRaises(ValidationError):
                    c.resources.download("res-1", directory=self.root, filename=name)

                self.assertEqual(session.calls, [])
                self.assertEqual(tree(self.root), [])

    def test_safe_filename_is_used_as_given(self):
        for name in SAFE_NAMES:
            with self.subTest(name=name):
                directory = self.fresh_directory()
                c, session = make_client([action(resource()), content(b"abc")])

                path = c.resources.download("res-1", directory=directory, filename=name)

                self.assertEqual(path, directory / name)
                self.assertEqual(path.read_bytes(), b"abc")
                self.assertEqual(len(session.calls), 2)

    def test_names_near_the_reserved_device_names_are_safe(self):
        # Checked on the helper: some Windows versions treat COM0 and LPT0 as
        # devices, so these names are not written to disk.
        for name in ("COM0", "LPT0", "com0.txt"):
            with self.subTest(name=name):
                self.assertTrue(is_safe_file_name(name))

    def test_filename_without_a_utf8_encoding_is_unsafe(self):
        # A lone surrogate has no UTF-8 byte length, so it cannot meet the
        # 255-byte rule.
        c, session = make_client([action(resource()), content(b"abc")])

        with self.assertRaises(ValidationError):
            c.resources.download("res-1", directory=self.root, filename="a\ud800")

        self.assertEqual(session.calls, [])

    def test_filename_overrides_the_url_name(self):
        c, _ = make_client([action(resource()), content(b"abc")])

        path = c.resources.download("res-1", directory=self.root, filename="x.ttl")

        self.assertEqual(path, self.root / "x.ttl")
        self.assertEqual(tree(self.root), ["x.ttl"])

    def test_filename_is_not_stripped(self):
        c, _ = make_client([action(resource()), content(b"abc")])

        path = c.resources.download("res-1", directory=self.root, filename=" data.ttl")

        self.assertEqual(path, self.root / " data.ttl")
        self.assertEqual(tree(self.root), [" data.ttl"])
        for name in ("data.ttl ", "data.ttl\n", "\tdata.ttl"):
            with self.subTest(name=name):
                c, session = make_client([action(resource()), content(b"abc")])

                with self.assertRaises(ValidationError):
                    c.resources.download("res-1", directory=self.root, filename=name)

                self.assertEqual(session.calls, [])

    def test_url_name_is_the_percent_decoded_last_path_segment(self):
        cases = [
            (upload_url("data.ttl"), "data.ttl"),
            (upload_url("my%20data.ttl"), "my data.ttl"),
            (upload_url("%C3%A9t%C3%A9.ttl"), "été.ttl"),
            (upload_url("100%25.ttl"), "100%.ttl"),
            (upload_url("a%252Fb.ttl"), "a%2Fb.ttl"),
            (upload_url("data.ttl?name=other.ttl"), "data.ttl"),
            (upload_url("data.ttl#other.ttl"), "data.ttl"),
            ("https://ckan.test/data.ttl", "data.ttl"),
        ]
        for url, name in cases:
            with self.subTest(url=url):
                directory = self.fresh_directory()
                c, _ = make_client([action(resource(url=url)), content(b"abc")])

                path = c.resources.download("res-1", directory=directory)

                self.assertEqual(path, directory / name)
                self.assertEqual((directory / name).read_bytes(), b"abc")

    def test_unsafe_url_name_falls_back_to_the_resource_id(self):
        segments = [
            "",
            ".",
            "..",
            "%2E",
            "%2e%2E",
            "a%2Fb.ttl",
            "%2F",
            "..%2F..%2Fescape.ttl",
            "a%5Cb.ttl",
            "C%3Adata.ttl",
            "a%2Ab.ttl",
            "a%3Fb.ttl",
            "a%22b.ttl",
            "a%3Cb%3E.ttl",
            "a%7Cb.ttl",
            "a%00b.ttl",
            "a%0Ab.ttl",
            "a%1Fb.ttl",
            "a%7Fb.ttl",
            "data.ttl.",
            "data.ttl%20",
            "CON",
            "con.ttl",
            "Lpt9.tar.gz",
            "nul",
            quote(TOO_LONG_TWO_BYTE),
            quote(TOO_LONG_THREE_BYTE),
        ]
        for segment in segments:
            with self.subTest(segment=segment):
                directory = self.fresh_directory()
                url = upload_url(segment)
                c, session = make_client(
                    [action(resource("res-1", url=url)), content(b"abc")]
                )

                path = c.resources.download("res-1", directory=directory)

                self.assertEqual(path, directory / "res-1")
                self.assertEqual(tree(directory), ["res-1"])
                self.assertEqual(session.calls[1]["url"], url)

    def test_url_without_path_falls_back_to_the_resource_id(self):
        for url in ("https://ckan.test", "https://ckan.test/"):
            with self.subTest(url=url):
                directory = self.fresh_directory()
                c, _ = make_client([action(resource(url=url)), content(b"abc")])

                path = c.resources.download("res-1", directory=directory)

                self.assertEqual(path, directory / "res-1")

    def test_unsafe_url_name_and_unsafe_id_raise_before_content_request(self):
        for resource_id in ("CON", "a:b", "res.", "res ", "..", "a/b"):
            with self.subTest(resource_id=resource_id):
                payload = resource(resource_id, url=upload_url("a%2Fb.ttl"))
                c, session = make_client([action(payload)])

                with self.assertRaises(ValidationError):
                    c.resources.download("res-1", directory=self.root)

                self.assertEqual(len(session.calls), 1)
                c, session = make_client([action(package(payload))])

                with self.assertRaises(ValidationError):
                    c.resources.download_all("pkg-1", directory=self.root)

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])

    def test_filename_replaces_unsafe_url_name_and_unsafe_id(self):
        payload = resource("CON", url=upload_url("a%2Fb.ttl"))
        c, _ = make_client([action(payload), content(b"abc")])

        path = c.resources.download("res-1", directory=self.root, filename="x.ttl")

        self.assertEqual(path, self.root / "x.ttl")


class TestLocalChecks(_TempDirTestCase):
    """Criterion 6: local problems are rejected before any content request."""

    def two_uploads(self) -> dict[str, Any]:
        return package(
            resource("res-1", url=upload_url("a.ttl")),
            resource("res-2", url=upload_url("b.ttl")),
        )

    def test_directory_that_is_a_file_raises(self):
        file_path = self.root / "file.txt"
        file_path.write_text("keep")
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                c, session = make_client([action(resource())])

                with self.assertRaises(FileExistsError):
                    c.resources.download(
                        "res-1", directory=file_path, overwrite=overwrite
                    )

                self.assertEqual(len(session.calls), 1)
                c, session = make_client([action(self.two_uploads())])

                with self.assertRaises(FileExistsError):
                    c.resources.download_all(
                        "pkg-1", directory=file_path, overwrite=overwrite
                    )

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(file_path.read_text(), "keep")

    def test_target_that_is_a_directory_raises_also_with_overwrite(self):
        (self.root / "b.ttl").mkdir()
        (self.root / "data.ttl").mkdir()
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                c, session = make_client([action(resource())])

                with self.assertRaises(FileExistsError):
                    c.resources.download(
                        "res-1", directory=self.root, overwrite=overwrite
                    )

                self.assertEqual(len(session.calls), 1)
                c, session = make_client([action(self.two_uploads())])

                with self.assertRaises(FileExistsError):
                    c.resources.download_all(
                        "pkg-1", directory=self.root, overwrite=overwrite
                    )

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), ["b.ttl", "data.ttl"])

    def test_existing_target_raises_without_overwrite(self):
        (self.root / "data.ttl").write_text("old")
        (self.root / "b.ttl").write_text("old")
        c, session = make_client([action(resource())])

        with self.assertRaises(FileExistsError):
            c.resources.download("res-1", directory=self.root)

        self.assertEqual(len(session.calls), 1)
        c, session = make_client([action(self.two_uploads())])

        with self.assertRaises(FileExistsError):
            c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(tree(self.root), ["b.ttl", "data.ttl"])
        self.assertEqual((self.root / "data.ttl").read_text(), "old")
        self.assertEqual((self.root / "b.ttl").read_text(), "old")

    def test_dangling_symlink_at_target_counts_as_existing(self):
        destination = self.root / "missing.txt"
        link = self.root / "data.ttl"
        self.symlink(link, destination)
        c, session = make_client([action(resource())])

        with self.assertRaises(FileExistsError):
            c.resources.download("res-1", directory=self.root)

        self.assertEqual(len(session.calls), 1)
        c, session = make_client([action(package(resource()))])

        with self.assertRaises(FileExistsError):
            c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(len(session.calls), 1)
        self.assertTrue(link.is_symlink())
        self.assertFalse(destination.exists())

    def test_overwrite_replaces_existing_files(self):
        (self.root / "data.ttl").write_text("old")
        (self.root / "a.ttl").write_text("old")
        c, _ = make_client([action(resource()), content(b"new")])

        path = c.resources.download("res-1", directory=self.root, overwrite=True)

        self.assertEqual(path.read_bytes(), b"new")
        c, _ = make_client(
            [action(self.two_uploads()), content(b"new a"), content(b"new b")]
        )

        paths = c.resources.download_all("pkg-1", directory=self.root, overwrite=True)

        self.assertEqual([p.read_bytes() for p in paths], [b"new a", b"new b"])
        self.assertEqual(tree(self.root), ["a.ttl", "b.ttl", "data.ttl"])

    def test_duplicate_names_raise_naming_the_resource_ids(self):
        cases = {
            "same URL name": [
                resource("res-1", url=upload_url("data.ttl")),
                resource("res-2", url=upload_url("other.ttl")),
                resource("res-3", url="https://files.example.test/x/data.ttl"),
            ],
            "URL name equals a fallback id": [
                resource("res-1", url=upload_url("res-3")),
                resource("res-2", url=upload_url("other.ttl")),
                resource("res-3", url=upload_url("CON")),
            ],
        }
        for label, resources in cases.items():
            with self.subTest(case=label):
                c, session = make_client([action(package(*resources))])

                with self.assertRaises(ValidationError) as caught:
                    c.resources.download_all("pkg-1", directory=self.root)

                self.assertIn("res-1", str(caught.exception))
                self.assertIn("res-3", str(caught.exception))
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])

    def test_names_differing_only_in_case_are_not_duplicates(self):
        resources = [
            resource("res-1", url=upload_url("data.ttl")),
            resource("res-2", url=upload_url("DATA.ttl")),
        ]
        c, session = make_client(
            [action(package(*resources)), content(b"1"), content(b"2")]
        )

        # On case-insensitive file systems the second target exists by then.
        with contextlib.suppress(FileExistsError):
            _ = c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(len(session.calls), 3)

    def test_name_errors_come_before_local_path_errors(self):
        file_path = self.root / "file.txt"
        file_path.write_text("keep")
        (self.root / "data.ttl").write_text("old")
        duplicates = package(
            resource("res-1", url=upload_url("data.ttl")),
            resource("res-2", url="https://files.example.test/data.ttl"),
        )
        unsafe = resource("CON", url=upload_url("CON"))
        cases = [
            ("duplicate, directory is a file", duplicates, file_path),
            ("duplicate, existing target", duplicates, self.root),
            ("unsafe id, directory is a file", package(unsafe), file_path),
            ("unsafe id, existing target", package(unsafe), self.root),
        ]
        for label, payload, directory in cases:
            with self.subTest(case=label):
                c, session = make_client([action(payload)])

                with self.assertRaises(ValidationError):
                    c.resources.download_all("pkg-1", directory=directory)

                self.assertEqual(len(session.calls), 1)

    def test_unsafe_filename_comes_before_local_path_errors(self):
        file_path = self.root / "file.txt"
        file_path.write_text("keep")
        c, session = make_client([action(resource())])

        with self.assertRaises(ValidationError):
            c.resources.download("res-1", directory=file_path, filename="a:b")

        self.assertEqual(session.calls, [])


class TestSizeCheck(_TempDirTestCase):
    """Criterion 7: the size of uploads is checked (D4)."""

    def download(self, payload: dict[str, Any], data: bytes) -> tuple[Path, Path]:
        directory = self.fresh_directory()
        c, _ = make_client([action(payload), content(data)])
        return c.resources.download("res-1", directory=directory), directory

    def test_matching_size_is_accepted(self):
        for size, data in ((3, b"abc"), ("3", b"abc"), ("003", b"abc"), (0, b"")):
            with self.subTest(size=size):
                path, _ = self.download(resource(size=size), data)

                self.assertEqual(path.read_bytes(), data)

    def test_size_mismatch_raises_and_leaves_no_file(self):
        for size, data in ((4, b"abc"), ("2", b"abc"), (0, b"a"), ("0", b"a")):
            with self.subTest(size=size):
                directory = self.fresh_directory()
                response = content(data)
                c, session = make_client([action(resource(size=size)), response])

                with self.assertRaises(ValidationError):
                    c.resources.download("res-1", directory=directory)

                self.assertEqual(tree(directory), [])
                self.assertEqual(len(session.calls), 2)
                self.assertTrue(response.closed)

    def test_size_mismatch_keeps_the_existing_file_with_overwrite(self):
        (self.root / "data.ttl").write_text("old")
        c, _ = make_client([action(resource(size=99)), content(b"new")])

        with self.assertRaises(ValidationError):
            c.resources.download("res-1", directory=self.root, overwrite=True)

        self.assertEqual(tree(self.root), ["data.ttl"])
        self.assertEqual((self.root / "data.ttl").read_text(), "old")

    def test_size_mismatch_in_download_all_raises(self):
        payload = package(resource(size=5))
        c, _ = make_client([action(payload), content(b"abc")])

        with self.assertRaises(ValidationError):
            c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual(tree(self.root), [])

    def test_size_check_is_skipped_for_link_resources(self):
        for url_type in (None, "", "link", "datastore"):
            for size in (99, "99"):
                with self.subTest(url_type=url_type, size=size):
                    path, _ = self.download(
                        resource(url_type=url_type, size=size), b"ab"
                    )

                    self.assertEqual(path.read_bytes(), b"ab")

    def test_size_check_is_skipped_for_unusable_sizes(self):
        # The body has 2 bytes; each size would mismatch if it were used.
        sizes = [
            True,
            False,
            -1,
            -2,
            3.0,
            None,
            [3],
            {"bytes": 3},
            "",
            " 3",
            "3 ",
            "3\n",
            "+3",
            "-2",
            "3.0",
            "1_0",
            "0x3",
            "abc",
            "٣",
            "３",
            "²",
        ]
        for size in sizes:
            with self.subTest(size=size):
                path, _ = self.download(resource(size=size), b"ab")

                self.assertEqual(path.read_bytes(), b"ab")

    def test_md5_hash_is_not_checked(self):
        for checksum in ("0" * 32, "md5:" + "0" * 32, "sha256:" + "0" * 64):
            with self.subTest(hash=checksum):
                path, _ = self.download(resource(size=2, hash=checksum), b"ab")

                self.assertEqual(path.read_bytes(), b"ab")


class TestContentErrors(_TempDirTestCase):
    """Criterion 8: HTTP errors raise `CkanApiError` and close the response."""

    def test_error_status_raises_ckan_api_error_and_closes_response(self):
        for url in (OWN_URL, OTHER_URL):
            for status in (400, 401, 403, 404, 500, 503):
                with self.subTest(url=url, status=status):
                    directory = self.fresh_directory()
                    response = error_response(status)
                    c, session = make_client([action(resource(url=url)), response])

                    with self.assertRaises(CkanApiError) as caught:
                        c.resources.download("res-1", directory=directory)

                    self.assertIsInstance(caught.exception, HttpError)
                    self.assertEqual(caught.exception.status_code, status)
                    self.assertTrue(response.closed)
                    self.assertEqual(len(session.calls), 2)
                    self.assertEqual(tree(directory), [])

    def test_successful_content_responses_are_closed(self):
        responses = [content(b"1"), content(b"2")]
        payload = package(
            resource("res-1", url=upload_url("a.ttl")),
            resource("res-2", url=upload_url("b.ttl")),
        )
        c, _ = make_client([action(payload), *responses])

        _ = c.resources.download_all("pkg-1", directory=self.root)

        self.assertEqual([r.closed for r in responses], [True, True])

    def test_metadata_errors_keep_the_action_error_handling(self):
        failure = FakeResponse(
            status_code=404,
            json_value={"success": False, "error": {"message": "Not found"}},
        )
        for method in ("download", "download_all"):
            with self.subTest(method=method):
                c, session = make_client([failure])

                with self.assertRaisesRegex(CkanApiError, "Not found"):
                    getattr(c.resources, method)("x", directory=self.root)

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])


if __name__ == "__main__":
    unittest.main()
