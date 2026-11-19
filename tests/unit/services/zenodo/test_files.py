import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from praeco.exceptions import ValidationError
from praeco.services.zenodo import ZenodoClient
from praeco.services.zenodo._urls import bucket_file_url
from praeco.services.zenodo.models import DepositionInfo

from ._helpers import FakeResponse, FakeSession, deposition_payload


class TestFilesResource(unittest.TestCase):
    def test_bucket_file_url_quotes_filename_segment(self):
        self.assertEqual(
            bucket_file_url("https://zenodo.org/api/files/bucket", "my file.zip"),
            "https://zenodo.org/api/files/bucket/my%20file.zip",
        )

    def test_bucket_file_url_requires_bucket_url(self):
        with self.assertRaisesRegex(ValidationError, "bucket URL"):
            bucket_file_url(" ", "artifact.zip")

    def test_list_parses_uploaded_files(self):
        session = FakeSession(
            [
                FakeResponse(
                    json_value=[
                        {
                            "id": "file-1",
                            "filename": "artifact.zip",
                            "filesize": "123",
                        }
                    ]
                )
            ]
        )
        c = ZenodoClient(session=cast(Any, session))

        files = c.files.list(42)

        self.assertEqual(files[0].filename, "artifact.zip")
        self.assertEqual(files[0].size, 123)
        self.assertEqual(
            session.calls[0]["url"],
            "https://zenodo.org/api/deposit/depositions/42/files",
        )

    def test_list_rejects_non_list_response(self):
        session = FakeSession([FakeResponse(json_value={"id": "file-1"})])
        c = ZenodoClient(session=cast(Any, session))

        with self.assertRaisesRegex(ValidationError, "must be a list"):
            c.files.list(42)

    def test_upload_uses_deposition_bucket_link(self):
        session = FakeSession(
            [
                FakeResponse(
                    status_code=200,
                    json_value={
                        "key": "artifact.zip",
                        "version_id": "v1",
                        "checksum": "md5:abc",
                        "size": 123,
                        "mimetype": "application/zip",
                        "links": {
                            "self": "https://zenodo.org/api/files/bucket/artifact.zip"
                        },
                    },
                )
            ]
        )
        c = ZenodoClient(session=cast(Any, session))
        deposition = DepositionInfo.from_dict(deposition_payload())

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            _ = path.write_bytes(b"payload")
            uploaded = c.files.upload(deposition, path, content_type="application/zip")

        self.assertEqual(len(uploaded), 1)
        self.assertEqual(uploaded[0].filename, "artifact.zip")
        self.assertEqual(uploaded[0].size, 123)
        self.assertEqual(session.calls[0]["method"], "PUT")
        self.assertEqual(
            session.calls[0]["url"],
            "https://zenodo.org/api/files/bucket-id/artifact.zip",
        )
        self.assertEqual(
            session.calls[0]["headers"], {"Content-Type": "application/zip"}
        )

    def test_upload_requires_filename(self):
        session = FakeSession()
        c = ZenodoClient(session=cast(Any, session))

        with self.assertRaisesRegex(ValidationError, "filename"):
            c.files.upload(42, " ", filename=" ")

    def test_upload_requires_bucket_link(self):
        session = FakeSession(
            [FakeResponse(json_value=deposition_payload(bucket=None))]
        )
        c = ZenodoClient(session=cast(Any, session))

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            _ = path.write_bytes(b"x")
            with self.assertRaisesRegex(ValidationError, "bucket"):
                c.files.upload(42, path)

    def test_upload_fetches_deposition_when_only_id_is_given(self):
        session = FakeSession(
            [
                FakeResponse(json_value=deposition_payload()),
                FakeResponse(json_value={"key": "artifact.zip", "size": 1}),
            ]
        )
        c = ZenodoClient(session=cast(Any, session))

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            _ = path.write_bytes(b"x")
            _ = c.files.upload(42, path)

        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(session.calls[1]["method"], "PUT")

    def test_upload_fetches_deposition_when_info_has_no_bucket(self):
        session = FakeSession(
            [
                FakeResponse(json_value=deposition_payload()),
                FakeResponse(json_value={"key": "artifact.zip", "size": 1}),
            ]
        )
        c = ZenodoClient(session=cast(Any, session))
        deposition = DepositionInfo.from_dict(deposition_payload(bucket=None))

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            _ = path.write_bytes(b"x")
            _ = c.files.upload(deposition, path)

        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertEqual(session.calls[1]["method"], "PUT")

    def test_upload_uploads_each_path(self):
        session = FakeSession(
            [
                FakeResponse(json_value={"key": "one.txt", "size": 1}),
                FakeResponse(json_value={"key": "two.txt", "size": 2}),
            ]
        )
        c = ZenodoClient(session=cast(Any, session))
        deposition = DepositionInfo.from_dict(deposition_payload())

        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "one.txt"
            second = Path(tmp) / "two.txt"
            _ = first.write_text("one")
            _ = second.write_text("two")
            uploaded = c.files.upload(deposition, [first, second])

        self.assertEqual([file.filename for file in uploaded], ["one.txt", "two.txt"])
        self.assertEqual([call["method"] for call in session.calls], ["PUT", "PUT"])

    def test_upload_accepts_empty_path_sequence(self):
        session = FakeSession()
        c = ZenodoClient(session=cast(Any, session))

        uploaded = c.files.upload(42, [])

        self.assertEqual(uploaded, [])
        self.assertEqual(session.calls, [])

    def test_upload_rejects_filename_for_multiple_paths(self):
        session = FakeSession()
        c = ZenodoClient(session=cast(Any, session))

        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "one.txt"
            second = Path(tmp) / "two.txt"
            with self.assertRaisesRegex(ValidationError, "filename"):
                c.files.upload(42, [first, second], filename="artifact.txt")

        self.assertEqual(session.calls, [])

    def test_upload_rejects_content_type_for_multiple_paths(self):
        session = FakeSession()
        c = ZenodoClient(session=cast(Any, session))

        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "one.txt"
            second = Path(tmp) / "two.txt"
            with self.assertRaisesRegex(ValidationError, "content_type"):
                c.files.upload(42, [first, second], content_type="text/plain")

        self.assertEqual(session.calls, [])

    def test_upload_checks_every_path_before_the_first_request(self):
        session = FakeSession()
        c = ZenodoClient(session=cast(Any, session))

        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "one.txt"
            _ = first.write_text("one")
            missing = Path(tmp) / "missing.txt"

            for paths in ([first, missing], [first, Path(tmp)], missing):
                with (
                    self.subTest(paths=paths),
                    self.assertRaisesRegex(
                        ValidationError, "upload path must be a file"
                    ),
                ):
                    c.files.upload(42, paths)

        self.assertEqual(
            session.calls, [], msg="neither the deposition nor any file is requested"
        )

    def test_rename_uses_file_endpoint(self):
        session = FakeSession(
            [FakeResponse(json_value={"id": "file-1", "filename": "renamed.txt"})]
        )
        c = ZenodoClient(session=cast(Any, session))

        out = c.files.rename(42, "file-1", "renamed.txt")

        self.assertEqual(out.filename, "renamed.txt")
        self.assertEqual(session.calls[0]["method"], "PUT")
        self.assertEqual(
            session.calls[0]["url"],
            "https://zenodo.org/api/deposit/depositions/42/files/file-1",
        )
        self.assertEqual(session.calls[0]["json"], {"filename": "renamed.txt"})

    def test_rename_accepts_deposition_info(self):
        session = FakeSession(
            [FakeResponse(json_value={"id": "file-1", "filename": "renamed.txt"})]
        )
        c = ZenodoClient(session=cast(Any, session))
        deposition = DepositionInfo.from_dict(deposition_payload())

        _ = c.files.rename(deposition, "file-1", "renamed.txt")

        self.assertEqual(
            session.calls[0]["url"],
            "https://zenodo.org/api/deposit/depositions/42/files/file-1",
        )

    def test_rename_requires_name(self):
        session = FakeSession()
        c = ZenodoClient(session=cast(Any, session))

        with self.assertRaisesRegex(ValidationError, "name"):
            c.files.rename(42, "file-1", " ")

    def test_delete_uses_file_endpoint(self):
        session = FakeSession([FakeResponse(status_code=204, text="")])
        c = ZenodoClient(session=cast(Any, session))

        c.files.delete(42, "file-1")

        self.assertEqual(session.calls[0]["method"], "DELETE")
        self.assertEqual(
            session.calls[0]["url"],
            "https://zenodo.org/api/deposit/depositions/42/files/file-1",
        )


if __name__ == "__main__":
    unittest.main()
