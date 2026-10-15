import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from praeco.exceptions import ValidationError
from praeco.services.zenodo import ZenodoClient
from praeco.services.zenodo.exceptions import (
    ZenodoAuthenticationError,
    ZenodoNotFoundError,
    ZenodoPermissionError,
)
from praeco.services.zenodo.models import DepositionInfo
from praeco.services.zenodo.records import _target_paths

from ._helpers import FakeResponse, FakeSession, deposition_payload

RECORD_ID = 123
FILES_URL = "https://zenodo.org/api/records/123/files"
DRAFT_FILES_URL = "https://zenodo.org/api/records/123/draft/files"

# Reference MD5 digests (RFC 1321 test suite and the common "hello world").
MD5_ABC = "900150983cd24fb0d6963f7d28e17f72"
MD5_HELLO_WORLD = "5eb63bbbe01eeed093cb22bb8f5acdc3"

HTTP_ERRORS = [
    (401, ZenodoAuthenticationError),
    (403, ZenodoPermissionError),
    (404, ZenodoNotFoundError),
]

UNSAFE_KEYS = [
    "/etc/passwd",
    "../outside.txt",
    "sub/../../outside.txt",
    "sub/../inside.txt",
    "..",
    "C:\\outside.txt",
    "C:outside.txt",
    "\\\\server\\share\\outside.txt",
    "\\outside.txt",
    ".",
    "",
]


def content_url(key: str, *, draft: bool = False) -> str:
    files = "draft/files" if draft else "files"
    return f"https://zenodo.org/api/records/{RECORD_ID}/{files}/{key}/content"


def file_entry(
    key: str,
    *,
    checksum: str | None = None,
    size: int | None = None,
    status: str | None = "completed",
    content: str | None = None,
) -> dict[str, Any]:
    """Build one listing entry as served by InvenioRDM."""
    entry: dict[str, Any] = {
        "key": key,
        "links": {"content": content or content_url(key)},
    }
    if checksum is not None:
        entry["checksum"] = checksum
    if size is not None:
        entry["size"] = size
    if status is not None:
        entry["status"] = status
    return entry


def listing(*entries: dict[str, Any]) -> FakeResponse:
    return FakeResponse(json_value={"enabled": True, "entries": list(entries)})


def body(data: bytes) -> FakeResponse:
    return FakeResponse(body=data)


def error_response(status_code: int) -> FakeResponse:
    return FakeResponse(
        status_code=status_code,
        text="error",
        json_value={"status": status_code, "message": "request failed"},
    )


def make_client(responses: list[FakeResponse]) -> tuple[ZenodoClient, FakeSession]:
    session = FakeSession(responses)
    return ZenodoClient(session=cast(Any, session)), session


def tree(root: Path) -> list[str]:
    """Return every path below `root`, including hidden temporary files."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


class _TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class TestRecordFilesList(unittest.TestCase):
    def test_lists_published_record_files(self):
        c, session = make_client([listing(file_entry("a.txt"))])

        names = c.records.files.list(RECORD_ID)

        self.assertEqual(names, ["a.txt"])
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(session.calls[0]["url"], FILES_URL)

    def test_draft_lists_draft_files(self):
        c, session = make_client([listing(file_entry("a.txt"))])

        names = c.records.files.list(RECORD_ID, draft=True)

        self.assertEqual(names, ["a.txt"])
        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(session.calls[0]["url"], DRAFT_FILES_URL)

    def test_record_may_be_given_as_string(self):
        c, session = make_client([listing()])

        _ = c.records.files.list(str(RECORD_ID))

        self.assertEqual(session.calls[0]["url"], FILES_URL)

    def test_deposition_info_is_mapped_to_its_id(self):
        deposition = DepositionInfo.from_dict(deposition_payload(RECORD_ID))
        for draft, url in [(False, FILES_URL), (True, DRAFT_FILES_URL)]:
            with self.subTest(draft=draft):
                c, session = make_client([listing()])

                _ = c.records.files.list(deposition, draft=draft)

                self.assertEqual(session.calls[0]["url"], url)

    def test_keeps_server_order(self):
        c, _ = make_client(
            [listing(file_entry("b.txt"), file_entry("c.txt"), file_entry("a.txt"))]
        )

        self.assertEqual(c.records.files.list(RECORD_ID), ["b.txt", "c.txt", "a.txt"])

    def test_returns_keys_containing_slashes_verbatim(self):
        key = "pyiron/semantikon-1.4.4.zip"
        c, _ = make_client([listing(file_entry(key))])

        self.assertEqual(c.records.files.list(RECORD_ID), [key])

    def test_excludes_entries_that_are_not_completed(self):
        c, _ = make_client(
            [
                listing(
                    file_entry("done.txt", status="completed"),
                    file_entry("pending.txt", status="pending"),
                    file_entry("failed.txt", status="failed"),
                    file_entry("no-status.txt", status=None),
                )
            ]
        )

        self.assertEqual(c.records.files.list(RECORD_ID), ["done.txt", "no-status.txt"])

    def test_disabled_files_give_empty_list(self):
        payloads: list[dict[str, Any]] = [
            {"enabled": False},
            {"enabled": False, "entries": []},
            {"enabled": False, "entries": [file_entry("a.txt")]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                c, _ = make_client([FakeResponse(json_value=payload)])

                self.assertEqual(c.records.files.list(RECORD_ID), [])

    def test_missing_entries_give_empty_list(self):
        for payload in [{}, {"enabled": True}]:
            with self.subTest(payload=payload):
                c, _ = make_client([FakeResponse(json_value=payload)])

                self.assertEqual(c.records.files.list(RECORD_ID), [])

    def test_empty_entries_give_empty_list(self):
        c, _ = make_client([listing()])

        self.assertEqual(c.records.files.list(RECORD_ID), [])

    def test_malformed_listing_raises_validation_error(self):
        payloads: list[Any] = [
            [file_entry("a.txt")],
            "files",
            None,
            {"enabled": True, "entries": {"a.txt": file_entry("a.txt")}},
            {"enabled": True, "entries": "a.txt"},
            {"enabled": True, "entries": ["a.txt"]},
            {"enabled": True, "entries": [file_entry("a.txt"), None]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                c, _ = make_client([FakeResponse(json_value=payload)])

                with self.assertRaises(ValidationError):
                    c.records.files.list(RECORD_ID)

    def test_http_errors_map_to_zenodo_exceptions(self):
        for status_code, error_cls in HTTP_ERRORS:
            for draft in (False, True):
                with self.subTest(status_code=status_code, draft=draft):
                    c, _ = make_client([error_response(status_code)])

                    with self.assertRaises(error_cls) as ctx:
                        c.records.files.list(RECORD_ID, draft=draft)

                    self.assertEqual(ctx.exception.status_code, status_code)


class TestRecordFilesDownload(_TempDirTestCase):
    def test_single_name_downloads_one_file(self):
        content = body(b"hello world")
        c, session = make_client(
            [
                listing(
                    file_entry("other.txt"),
                    file_entry("hello.txt", checksum=f"md5:{MD5_HELLO_WORLD}", size=11),
                ),
                content,
            ]
        )

        paths = c.records.files.download(RECORD_ID, "hello.txt", directory=self.root)

        self.assertEqual(paths, [self.root / "hello.txt"])
        self.assertEqual((self.root / "hello.txt").read_bytes(), b"hello world")
        self.assertEqual(tree(self.root), ["hello.txt"])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["url"], FILES_URL)
        self.assertEqual(session.calls[1]["method"], "GET")
        self.assertEqual(session.calls[1]["url"], content_url("hello.txt"))
        self.assertIs(session.calls[1]["stream"], True)
        self.assertTrue(content.closed)

    def test_uses_server_provided_content_link(self):
        link = "https://files.zenodo.test/some/opaque/location?token=1"
        c, session = make_client(
            [listing(file_entry("a.txt", content=link)), body(b"abc")]
        )

        _ = c.records.files.download(RECORD_ID, "a.txt", directory=self.root)

        self.assertEqual(session.calls[1]["url"], link)
        self.assertIs(session.calls[1]["stream"], True)

    def test_draft_downloads_from_draft_listing(self):
        link = content_url("a.txt", draft=True)
        c, session = make_client(
            [listing(file_entry("a.txt", content=link)), body(b"abc")]
        )

        paths = c.records.files.download(
            RECORD_ID, ["a.txt"], directory=self.root, draft=True
        )

        self.assertEqual(paths, [self.root / "a.txt"])
        self.assertEqual(
            [call["url"] for call in session.calls], [DRAFT_FILES_URL, link]
        )

    def test_returns_paths_in_requested_order(self):
        c, session = make_client(
            [
                listing(file_entry("a.txt"), file_entry("b.txt"), file_entry("c.txt")),
                body(b"C"),
                body(b"A"),
            ]
        )

        paths = c.records.files.download(
            RECORD_ID, ("c.txt", "a.txt"), directory=self.root
        )

        self.assertEqual(paths, [self.root / "c.txt", self.root / "a.txt"])
        self.assertEqual((self.root / "c.txt").read_bytes(), b"C")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"A")
        self.assertEqual(tree(self.root), ["a.txt", "c.txt"])
        # Each file's bytes must come from that file's own content link.
        self.assertEqual(
            [call["url"] for call in session.calls[1:]],
            [content_url("c.txt"), content_url("a.txt")],
        )
        for call in session.calls[1:]:
            self.assertIs(call["stream"], True)

    def test_returned_paths_join_directory_and_key_without_resolving(self):
        (self.root / "sub").mkdir()
        directory = f"{self.root}/sub/.."
        c, _ = make_client([listing(file_entry("a.txt")), body(b"abc")])

        paths = c.records.files.download(RECORD_ID, "a.txt", directory=directory)

        self.assertEqual(paths, [Path(directory) / "a.txt"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"abc")

    def test_default_directory_is_current_directory(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        c, _ = make_client([listing(file_entry("a.txt")), body(b"abc")])

        paths = c.records.files.download(RECORD_ID, "a.txt")

        self.assertEqual(paths, [Path(".") / "a.txt"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"abc")

    def test_empty_sequence_makes_no_request(self):
        for files in ([], ()):
            with self.subTest(files=files):
                c, session = make_client([])

                paths = c.records.files.download(RECORD_ID, files, directory=self.root)

                self.assertEqual(paths, [])
                self.assertEqual(session.calls, [])

    def test_duplicate_names_raise_before_any_request(self):
        c, session = make_client([])

        with self.assertRaises(ValidationError):
            c.records.files.download(
                RECORD_ID, ["a.txt", "b.txt", "a.txt"], directory=self.root
            )

        self.assertEqual(session.calls, [])
        self.assertEqual(tree(self.root), [])

    def test_unsafe_keys_raise_before_any_request(self):
        for key in UNSAFE_KEYS:
            with self.subTest(key=key):
                c, session = make_client([])

                with self.assertRaises(ValidationError):
                    c.records.files.download(
                        RECORD_ID, ["ok.txt", key], directory=self.root
                    )

                self.assertEqual(session.calls, [])
                self.assertEqual(tree(self.root), [])

    def test_key_escaping_through_symlink_raises_before_any_request(self):
        outside = self.root / "outside"
        outside.mkdir()
        directory = self.root / "downloads"
        directory.mkdir()
        try:
            (directory / "link").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        c, session = make_client([])

        with self.assertRaises(ValidationError):
            c.records.files.download(RECORD_ID, "link/a.txt", directory=directory)

        self.assertEqual(session.calls, [])
        self.assertEqual(list(outside.iterdir()), [])

    def test_existing_target_raises_before_any_request(self):
        _ = (self.root / "b.txt").write_bytes(b"original")
        c, session = make_client([])

        with self.assertRaises(FileExistsError):
            c.records.files.download(RECORD_ID, ["a.txt", "b.txt"], directory=self.root)

        self.assertEqual(session.calls, [])
        self.assertEqual((self.root / "b.txt").read_bytes(), b"original")
        self.assertEqual(tree(self.root), ["b.txt"])

    def test_unknown_name_raises_after_listing_before_content(self):
        c, session = make_client([listing(file_entry("a.txt"), file_entry("b.txt"))])

        with self.assertRaises(ValidationError):
            c.records.files.download(
                RECORD_ID, ["a.txt", "missing.txt"], directory=self.root
            )

        self.assertEqual([call["url"] for call in session.calls], [FILES_URL])
        self.assertEqual(tree(self.root), [])

    def test_names_must_match_keys_exactly(self):
        for name in ["A.txt", " a.txt", "./a.txt", "sub//a.txt"]:
            with self.subTest(name=name):
                c, session = make_client(
                    [listing(file_entry("a.txt"), file_entry("sub/a.txt"))]
                )

                with self.assertRaises(ValidationError):
                    c.records.files.download(RECORD_ID, name, directory=self.root)

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])

    def test_not_completed_file_is_unknown(self):
        c, session = make_client([listing(file_entry("pending.txt", status="pending"))])

        with self.assertRaises(ValidationError):
            c.records.files.download(RECORD_ID, "pending.txt", directory=self.root)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(tree(self.root), [])

    def test_missing_content_link_raises_before_any_content_request(self):
        without_link = file_entry("b.txt")
        del without_link["links"]
        blank_link = file_entry("c.txt")
        blank_link["links"] = {"content": " "}
        for entry in (without_link, blank_link):
            with self.subTest(entry=entry):
                c, session = make_client([listing(file_entry("a.txt"), entry)])

                with self.assertRaises(ValidationError):
                    c.records.files.download(
                        RECORD_ID, ["a.txt", entry["key"]], directory=self.root
                    )

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])

    def test_nested_key_creates_subdirectories(self):
        key = "pyiron/data/semantikon-1.4.4.zip"
        c, session = make_client([listing(file_entry(key)), body(b"zip")])

        paths = c.records.files.download(RECORD_ID, key, directory=self.root)

        target = self.root / "pyiron" / "data" / "semantikon-1.4.4.zip"
        self.assertEqual(paths, [target])
        self.assertEqual(target.read_bytes(), b"zip")
        self.assertEqual(session.calls[1]["url"], content_url(key))
        self.assertNotIn("%2F", session.calls[1]["url"])

    def test_overwrite_replaces_existing_files(self):
        _ = (self.root / "a.txt").write_bytes(b"old contents")
        c, _ = make_client([listing(file_entry("a.txt")), body(b"new")])

        paths = c.records.files.download(
            RECORD_ID, "a.txt", directory=self.root, overwrite=True
        )

        self.assertEqual(paths, [self.root / "a.txt"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"new")
        self.assertEqual(tree(self.root), ["a.txt"])

    def test_matching_checksums_are_accepted(self):
        for checksum in [
            f"md5:{MD5_ABC}",
            MD5_ABC,
            f"md5:{MD5_ABC.upper()}",
        ]:
            with self.subTest(checksum=checksum), TemporaryDirectory() as tmp:
                c, _ = make_client(
                    [
                        listing(file_entry("a.txt", checksum=checksum, size=3)),
                        body(b"abc"),
                    ]
                )

                _ = c.records.files.download(RECORD_ID, "a.txt", directory=tmp)

                self.assertEqual((Path(tmp) / "a.txt").read_bytes(), b"abc")

    def test_md5_mismatch_raises_and_leaves_no_file(self):
        for checksum in [f"md5:{MD5_HELLO_WORLD}", MD5_HELLO_WORLD]:
            with self.subTest(checksum=checksum):
                content = body(b"abc")
                c, _ = make_client(
                    [listing(file_entry("a.txt", checksum=checksum)), content]
                )

                with self.assertRaises(ValidationError):
                    c.records.files.download(RECORD_ID, "a.txt", directory=self.root)

                self.assertEqual(tree(self.root), [])
                self.assertTrue(content.closed)

    def test_other_or_malformed_checksums_skip_verification(self):
        for checksum in [
            "sha256:" + "0" * 64,
            "adler32:00000000",
            "md5:not-a-digest",
            "md5:",
            "md5:" + "0" * 31,
            "",
        ]:
            with self.subTest(checksum=checksum), TemporaryDirectory() as tmp:
                c, _ = make_client(
                    [listing(file_entry("a.txt", checksum=checksum)), body(b"abc")]
                )

                paths = c.records.files.download(RECORD_ID, "a.txt", directory=tmp)

                self.assertEqual(paths, [Path(tmp) / "a.txt"])
                self.assertEqual((Path(tmp) / "a.txt").read_bytes(), b"abc")

    def test_size_mismatch_raises_and_leaves_no_file(self):
        content = body(b"abc")
        c, _ = make_client(
            [listing(file_entry("a.txt", checksum=f"md5:{MD5_ABC}", size=4)), content]
        )

        with self.assertRaises(ValidationError):
            c.records.files.download(RECORD_ID, "a.txt", directory=self.root)

        self.assertEqual(tree(self.root), [])
        self.assertTrue(content.closed)

    def test_invalid_listed_sizes_skip_size_verification(self):
        # None of these is a usable byte count for the six-byte body; if any
        # were compared, the download would fail with a size mismatch.
        for size in [True, False, -6, "6", "999", None]:
            with self.subTest(size=size), TemporaryDirectory() as tmp:
                entry = file_entry("a.txt")
                entry["size"] = size
                c, _ = make_client([listing(entry), body(b"abcdef")])

                paths = c.records.files.download(RECORD_ID, "a.txt", directory=tmp)

                self.assertEqual(paths, [Path(tmp) / "a.txt"])
                self.assertEqual((Path(tmp) / "a.txt").read_bytes(), b"abcdef")

    def test_unsafe_keys_of_unrequested_entries_are_ignored(self):
        c, session = make_client(
            [
                listing(
                    file_entry("../evil"),
                    file_entry("good.txt"),
                    file_entry("/etc/passwd"),
                ),
                body(b"good"),
            ]
        )

        paths = c.records.files.download(RECORD_ID, ["good.txt"], directory=self.root)

        self.assertEqual(paths, [self.root / "good.txt"])
        self.assertEqual((self.root / "good.txt").read_bytes(), b"good")
        self.assertEqual(tree(self.root), ["good.txt"])
        self.assertEqual(
            [call["url"] for call in session.calls],
            [FILES_URL, content_url("good.txt")],
        )

    def test_listing_http_errors_map_to_zenodo_exceptions(self):
        for status_code, error_cls in HTTP_ERRORS:
            with self.subTest(status_code=status_code):
                c, session = make_client([error_response(status_code)])

                with self.assertRaises(error_cls):
                    c.records.files.download(RECORD_ID, "a.txt", directory=self.root)

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])

    def test_content_http_errors_map_to_zenodo_exceptions(self):
        for status_code, error_cls in HTTP_ERRORS:
            with self.subTest(status_code=status_code):
                content = error_response(status_code)
                c, session = make_client([listing(file_entry("a.txt")), content])

                with self.assertRaises(error_cls) as ctx:
                    c.records.files.download(RECORD_ID, "a.txt", directory=self.root)

                self.assertEqual(ctx.exception.status_code, status_code)
                self.assertEqual(ctx.exception.url, content_url("a.txt"))
                self.assertIs(session.calls[1]["stream"], True)
                self.assertTrue(content.closed)
                self.assertEqual(tree(self.root), [])

    def test_later_failure_keeps_earlier_files(self):
        first = body(b"abc")
        second = body(b"abc")
        c, _ = make_client(
            [
                listing(
                    file_entry("a.txt", checksum=f"md5:{MD5_ABC}"),
                    file_entry("b.txt", checksum=f"md5:{MD5_HELLO_WORLD}"),
                ),
                first,
                second,
            ]
        )

        with self.assertRaises(ValidationError):
            c.records.files.download(RECORD_ID, ["a.txt", "b.txt"], directory=self.root)

        self.assertEqual(tree(self.root), ["a.txt"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"abc")
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)

    def test_later_content_error_keeps_earlier_files(self):
        second = error_response(404)
        c, _ = make_client(
            [
                listing(file_entry("a.txt"), file_entry("b.txt")),
                body(b"abc"),
                second,
            ]
        )

        with self.assertRaises(ZenodoNotFoundError):
            c.records.files.download(RECORD_ID, ["a.txt", "b.txt"], directory=self.root)

        self.assertEqual(tree(self.root), ["a.txt"])
        self.assertTrue(second.closed)


class TestRecordFilesDownloadAll(_TempDirTestCase):
    def test_downloads_every_listed_file_in_server_order(self):
        contents = [body(b"B"), body(b"nested"), body(b"A")]
        c, session = make_client(
            [
                listing(
                    file_entry("b.txt"),
                    file_entry("pending.txt", status="pending"),
                    file_entry("sub/c.txt"),
                    file_entry("a.txt", status=None),
                ),
                *contents,
            ]
        )

        paths = c.records.files.download_all(RECORD_ID, directory=self.root)

        self.assertEqual(
            paths,
            [self.root / "b.txt", self.root / "sub/c.txt", self.root / "a.txt"],
        )
        self.assertEqual((self.root / "b.txt").read_bytes(), b"B")
        self.assertEqual((self.root / "sub" / "c.txt").read_bytes(), b"nested")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"A")
        self.assertEqual(tree(self.root), ["a.txt", "b.txt", "sub", "sub/c.txt"])
        self.assertEqual(
            [call["url"] for call in session.calls[1:]],
            [content_url("b.txt"), content_url("sub/c.txt"), content_url("a.txt")],
        )
        for call in session.calls[1:]:
            self.assertIs(call["stream"], True)
        for content in contents:
            self.assertTrue(content.closed)

    def test_draft_uses_draft_listing(self):
        link = content_url("a.txt", draft=True)
        c, session = make_client(
            [listing(file_entry("a.txt", content=link)), body(b"abc")]
        )

        paths = c.records.files.download_all(RECORD_ID, directory=self.root, draft=True)

        self.assertEqual(paths, [self.root / "a.txt"])
        self.assertEqual(
            [call["url"] for call in session.calls], [DRAFT_FILES_URL, link]
        )

    def test_empty_listing_gives_empty_list_after_one_request(self):
        for payload in [
            {"enabled": True, "entries": []},
            {"enabled": False},
        ]:
            with self.subTest(payload=payload):
                c, session = make_client([FakeResponse(json_value=payload)])

                paths = c.records.files.download_all(RECORD_ID, directory=self.root)

                self.assertEqual(paths, [])
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])

    def test_duplicate_listing_key_raises_before_any_content_request(self):
        c, session = make_client(
            [listing(file_entry("a.txt"), file_entry("b.txt"), file_entry("a.txt"))]
        )

        with self.assertRaises(ValidationError):
            c.records.files.download_all(RECORD_ID, directory=self.root)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(tree(self.root), [])

    def test_unsafe_listing_key_raises_before_any_content_request(self):
        for key in UNSAFE_KEYS:
            with self.subTest(key=key):
                c, session = make_client(
                    [listing(file_entry("ok.txt"), file_entry(key))]
                )

                with self.assertRaises(ValidationError):
                    c.records.files.download_all(RECORD_ID, directory=self.root)

                self.assertEqual(len(session.calls), 1)
                self.assertEqual(tree(self.root), [])

    def test_existing_target_raises_before_any_content_request(self):
        _ = (self.root / "b.txt").write_bytes(b"original")
        c, session = make_client([listing(file_entry("a.txt"), file_entry("b.txt"))])

        with self.assertRaises(FileExistsError):
            c.records.files.download_all(RECORD_ID, directory=self.root)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual((self.root / "b.txt").read_bytes(), b"original")
        self.assertEqual(tree(self.root), ["b.txt"])

    def test_overwrite_replaces_existing_files(self):
        _ = (self.root / "a.txt").write_bytes(b"old contents")
        c, _ = make_client([listing(file_entry("a.txt")), body(b"new")])

        paths = c.records.files.download_all(
            RECORD_ID, directory=self.root, overwrite=True
        )

        self.assertEqual(paths, [self.root / "a.txt"])
        self.assertEqual((self.root / "a.txt").read_bytes(), b"new")

    def test_missing_content_link_raises_before_any_content_request(self):
        without_link = file_entry("b.txt")
        without_link["links"] = {}
        c, session = make_client([listing(file_entry("a.txt"), without_link)])

        with self.assertRaises(ValidationError):
            c.records.files.download_all(RECORD_ID, directory=self.root)

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(tree(self.root), [])

    def test_listing_http_errors_map_to_zenodo_exceptions(self):
        for status_code, error_cls in HTTP_ERRORS:
            with self.subTest(status_code=status_code):
                c, _ = make_client([error_response(status_code)])

                with self.assertRaises(error_cls):
                    c.records.files.download_all(RECORD_ID, directory=self.root)

    def test_content_http_errors_map_to_zenodo_exceptions(self):
        for status_code, error_cls in HTTP_ERRORS:
            with self.subTest(status_code=status_code):
                content = error_response(status_code)
                c, _ = make_client([listing(file_entry("a.txt")), content])

                with self.assertRaises(error_cls):
                    c.records.files.download_all(RECORD_ID, directory=self.root)

                self.assertTrue(content.closed)
                self.assertEqual(tree(self.root), [])

    def test_later_failure_keeps_earlier_files(self):
        c, _ = make_client(
            [
                listing(
                    file_entry("a.txt", size=3),
                    file_entry("b.txt", size=99),
                ),
                body(b"abc"),
                body(b"abc"),
            ]
        )

        with self.assertRaises(ValidationError):
            c.records.files.download_all(RECORD_ID, directory=self.root)

        self.assertEqual(tree(self.root), ["a.txt"])


class TestRecordFilesLocalPathChecks(_TempDirTestCase):
    """Colliding keys and blocked local paths are rejected up front.

    `download` with explicit names makes no request at all; `download_all`
    makes only the listing request.
    """

    def symlink(self, link: Path, destination: Path) -> None:
        try:
            link.symlink_to(destination)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

    def assert_rejected_before_content(
        self,
        keys: list[str],
        error: type[Exception],
        *,
        directory: Path | None = None,
        overwrite: bool = False,
    ) -> None:
        directory = self.root if directory is None else directory
        before = tree(self.root)

        with self.subTest(api="download", keys=keys, overwrite=overwrite):
            c, session = make_client([])

            with self.assertRaises(error):
                c.records.files.download(
                    RECORD_ID, keys, directory=directory, overwrite=overwrite
                )

            self.assertEqual(session.calls, [])
            self.assertEqual(tree(self.root), before)

        with self.subTest(api="download_all", keys=keys, overwrite=overwrite):
            c, session = make_client([listing(*(file_entry(key) for key in keys))])

            with self.assertRaises(error):
                c.records.files.download_all(
                    RECORD_ID, directory=directory, overwrite=overwrite
                )

            self.assertEqual([call["url"] for call in session.calls], [FILES_URL])
            self.assertEqual(tree(self.root), before)

    def test_keys_naming_the_same_or_nested_paths_collide(self):
        pairs = [
            ["x/y", "x//y"],
            ["x/./y", "x/y"],
            ["a/", "a"],
            ["a", "a/b"],
            ["a/b", "a"],
            ["a/b/c", "a"],
        ]
        for keys in pairs:
            for overwrite in (False, True):
                self.assert_rejected_before_content(
                    keys, ValidationError, overwrite=overwrite
                )

    def test_collision_is_reported_before_existing_targets(self):
        _ = (self.root / "a").write_bytes(b"original")

        self.assert_rejected_before_content(["a", "a/b"], ValidationError)
        self.assertEqual((self.root / "a").read_bytes(), b"original")

    def test_keys_differing_only_in_case_do_not_collide(self):
        keys = ["A.txt", "a.txt", "Dir/x", "dir/x/y"]

        targets = _target_paths(self.root, keys, overwrite=False)

        self.assertEqual(targets, [self.root / key for key in keys])

    def test_directory_that_is_a_file_blocks_downloads(self):
        blocker = self.root / "blocker"
        _ = blocker.write_bytes(b"not a directory")
        for overwrite in (False, True):
            self.assert_rejected_before_content(
                ["a.txt"], FileExistsError, directory=blocker, overwrite=overwrite
            )
        self.assertEqual(blocker.read_bytes(), b"not a directory")

    def test_existing_directory_at_target_blocks_downloads(self):
        (self.root / "a.txt").mkdir()
        for overwrite in (False, True):
            self.assert_rejected_before_content(
                ["b.txt", "a.txt"], FileExistsError, overwrite=overwrite
            )
        self.assertTrue((self.root / "a.txt").is_dir())

    def test_file_at_ancestor_blocks_downloads(self):
        _ = (self.root / "sub").write_bytes(b"not a directory")
        for keys in (["sub/a.txt"], ["ok.txt", "sub/deeper/a.txt"]):
            for overwrite in (False, True):
                self.assert_rejected_before_content(
                    keys, FileExistsError, overwrite=overwrite
                )
        self.assertEqual((self.root / "sub").read_bytes(), b"not a directory")

    def test_dangling_symlink_at_ancestor_blocks_downloads(self):
        destination = self.root / "missing"
        self.symlink(self.root / "sub", destination)
        for overwrite in (False, True):
            self.assert_rejected_before_content(
                ["sub/a.txt"], FileExistsError, overwrite=overwrite
            )
        self.assertFalse(os.path.lexists(destination))

    def test_symlink_to_file_at_ancestor_blocks_downloads(self):
        _ = (self.root / "file.txt").write_bytes(b"data")
        self.symlink(self.root / "sub", self.root / "file.txt")
        for overwrite in (False, True):
            self.assert_rejected_before_content(
                ["sub/a.txt"], FileExistsError, overwrite=overwrite
            )
        self.assertEqual((self.root / "file.txt").read_bytes(), b"data")

    def test_symlink_to_directory_inside_directory_is_allowed_as_ancestor(self):
        (self.root / "real").mkdir()
        self.symlink(self.root / "link", self.root / "real")

        c, session = make_client([listing(file_entry("link/a.txt")), body(b"abc")])
        paths = c.records.files.download(RECORD_ID, "link/a.txt", directory=self.root)

        self.assertEqual(paths, [self.root / "link" / "a.txt"])
        self.assertEqual((self.root / "real" / "a.txt").read_bytes(), b"abc")
        self.assertEqual(len(session.calls), 2)

        c, _ = make_client([listing(file_entry("link/b.txt")), body(b"xyz")])
        paths = c.records.files.download_all(RECORD_ID, directory=self.root)

        self.assertEqual(paths, [self.root / "link" / "b.txt"])
        self.assertEqual((self.root / "real" / "b.txt").read_bytes(), b"xyz")

    def test_dangling_symlink_at_target_counts_as_existing(self):
        destination = self.root / "missing"
        self.symlink(self.root / "a.txt", destination)

        self.assert_rejected_before_content(["a.txt"], FileExistsError)

        self.assertTrue((self.root / "a.txt").is_symlink())
        self.assertFalse(os.path.lexists(destination))

    def test_overwrite_replaces_dangling_symlink_at_target(self):
        destination = self.root / "missing"
        link = self.root / "a.txt"
        self.symlink(link, destination)
        c, _ = make_client([listing(file_entry("a.txt")), body(b"abc")])

        paths = c.records.files.download(
            RECORD_ID, "a.txt", directory=self.root, overwrite=True
        )

        self.assertEqual(paths, [link])
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_bytes(), b"abc")
        self.assertFalse(os.path.lexists(destination))


if __name__ == "__main__":
    unittest.main()
