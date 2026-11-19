import json
import os
import re
import unittest
from pathlib import Path, PurePath
from tempfile import TemporaryDirectory
from typing import Any, cast

import requests

from praeco.exceptions import ValidationError
from praeco.services.ckan.models import CkanPackageInfo, CkanResourceInfo
from praeco.services.dataportal import (
    DataportalAssetInfo,
    DataportalClient,
    DataportalDatasetInfo,
)

from ..ckan._helpers import Reply, recording_session
from ._helpers import FakeResponse, FakeSession

DOWNLOADED = Path("downloaded", "data.csv")
TOKEN = "secret-token"
DATAPORTAL_URL = (
    "https://dataportal.material-digital.de/dataset/pkg-1/resource/res-1/"
    "download/data.ttl"
)


def resource_payload(
    *,
    resource_id: str = "res-1",
    package_id: str = "pkg-1",
) -> dict[str, Any]:
    return {
        "id": resource_id,
        "package_id": package_id,
        "name": "data.csv",
        "description": "Measurements.",
        "url": "https://example.test/data.csv",
        "format": "csv",
        "mimetype": "text/csv",
    }


class StubResourcesResource:
    def __init__(self):
        self.calls: list[tuple[Any, ...]] = []

    def create(self, payload: dict[str, Any], **kwargs: Any) -> CkanResourceInfo:
        self.calls.append(("create", payload, kwargs))
        return CkanResourceInfo.from_dict(resource_payload())

    def show(self, resource: str) -> CkanResourceInfo:
        self.calls.append(("show", resource))
        return CkanResourceInfo.from_dict(resource_payload())

    def patch(
        self,
        resource: str,
        payload: dict[str, Any],
    ) -> CkanResourceInfo:
        self.calls.append(("patch", resource, payload))
        return CkanResourceInfo.from_dict(resource_payload())

    def delete(self, resource: str) -> None:
        self.calls.append(("delete", resource))

    def download(self, resource: str, **kwargs: Any) -> Path:
        self.calls.append(("download", resource, kwargs))
        return DOWNLOADED

    def download_all(self, package: str, **kwargs: Any) -> list[Path]:
        self.calls.append(("download_all", package, kwargs))
        return [DOWNLOADED]


def client_with_stub() -> tuple[DataportalClient, StubResourcesResource]:
    client = DataportalClient(session=cast(Any, FakeSession()))
    resources = StubResourcesResource()
    client.resources = cast(Any, resources)
    return client, resources


class TestAssetsResource(unittest.TestCase):
    def test_upload_delegates_file_and_metadata(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "measurements.csv"
            path.write_text("temperature,value\n300,1\n")

            asset = client.assets.upload(
                "pkg-1",
                path,
                name="data.csv",
                description="Measurements.",
                format="csv",
                content_type="text/csv",
            )

        self.assertEqual(asset.id, "res-1")
        self.assertEqual(
            resources.calls,
            [
                (
                    "create",
                    {
                        "package_id": "pkg-1",
                        "name": "data.csv",
                        "description": "Measurements.",
                        "format": "csv",
                        "mimetype": "text/csv",
                    },
                    {"upload": path, "content_type": "text/csv"},
                )
            ],
        )

    def test_upload_uses_filename_as_default_name(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "measurements.csv"
            path.write_text("temperature,value\n300,1\n")

            _ = client.assets.upload("pkg-1", path)

        self.assertEqual(resources.calls[0][1]["name"], "measurements.csv")
        self.assertEqual(
            resources.calls[0][2],
            {"upload": path, "content_type": None},
        )

    def test_upload_rejects_non_file_path(self):
        client, resources = client_with_stub()

        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValidationError, "must be a file"),
        ):
            client.assets.upload("pkg-1", directory)

        self.assertEqual(resources.calls, [])

    def test_upload_rejects_blank_optional_metadata(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "measurements.csv"
            path.write_text("temperature,value\n300,1\n")

            for field_name in ("name", "description", "format", "content_type"):
                with (
                    self.subTest(field_name=field_name),
                    self.assertRaisesRegex(ValidationError, field_name),
                ):
                    client.assets.upload(
                        "pkg-1",
                        path,
                        **{field_name: " "},
                    )

        self.assertEqual(resources.calls, [])

    def test_create_url_delegates_ckan_payload_and_converts_result(self):
        client, resources = client_with_stub()

        asset = client.assets.create_url(
            "pkg-1",
            url="https://example.test/data.csv",
            name="data.csv",
            description="Measurements.",
            format="csv",
        )

        self.assertIsInstance(asset, DataportalAssetInfo)
        self.assertEqual(asset.id, "res-1")
        self.assertEqual(
            resources.calls,
            [
                (
                    "create",
                    {
                        "package_id": "pkg-1",
                        "url": "https://example.test/data.csv",
                        "name": "data.csv",
                        "description": "Measurements.",
                        "format": "csv",
                    },
                    {},
                )
            ],
        )

    def test_upload_rdf_uses_turtle_defaults(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.ttl"
            path.write_text("@prefix x: <https://example.test/> .")

            asset = client.assets.upload_rdf("pkg-1", path)

        self.assertEqual(asset.id, "res-1")
        self.assertEqual(resources.calls[0][1]["format"], "ttl")
        self.assertEqual(resources.calls[0][1]["mimetype"], "text/turtle")
        self.assertEqual(resources.calls[0][2]["content_type"], "text/turtle")

    def test_upload_rdf_allows_format_and_content_type_overrides(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "data.rdf"
            path.write_text("<rdf:RDF />")

            _ = client.assets.upload_rdf(
                "pkg-1",
                path,
                format="rdf",
                content_type="application/rdf+xml",
            )

        self.assertEqual(resources.calls[0][1]["format"], "rdf")
        self.assertEqual(
            resources.calls[0][1]["mimetype"],
            "application/rdf+xml",
        )
        self.assertEqual(
            resources.calls[0][2]["content_type"],
            "application/rdf+xml",
        )

    def test_create_url_accepts_dataset_model(self):
        client, resources = client_with_stub()
        dataset = DataportalDatasetInfo.from_ckan(
            CkanPackageInfo.from_dict({"id": "pkg-2", "name": "dataset"})
        )

        _ = client.assets.create_url(
            dataset,
            url="https://example.test/data.csv",
        )

        self.assertEqual(resources.calls[0][1]["package_id"], "pkg-2")

    def test_create_url_rejects_non_http_absolute_urls(self):
        client, resources = client_with_stub()

        for url in ("data.csv", "/data.csv", "ftp://example.test/data.csv", " "):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(ValidationError, "url"),
            ):
                client.assets.create_url("pkg-1", url=url)

        self.assertEqual(resources.calls, [])

    def test_create_url_rejects_blank_optional_fields(self):
        client, resources = client_with_stub()

        for field_name in ("name", "description", "format"):
            with (
                self.subTest(field_name=field_name),
                self.assertRaisesRegex(ValidationError, field_name),
            ):
                client.assets.create_url(
                    "pkg-1",
                    url="https://example.test/data.csv",
                    **{field_name: " "},
                )

        self.assertEqual(resources.calls, [])

    def test_show_accepts_asset_model_and_uses_its_id(self):
        client, resources = client_with_stub()
        asset = DataportalAssetInfo.from_ckan(
            CkanResourceInfo.from_dict(resource_payload(resource_id="res-2"))
        )

        result = client.assets.show(asset)

        self.assertEqual(result.id, "res-1")
        self.assertEqual(resources.calls, [("show", "res-2")])

    def test_patch_delegates_raw_metadata_mapping(self):
        client, resources = client_with_stub()
        payload = {"name": "renamed.csv", "description": "Updated."}

        asset = client.assets.patch("res-1", payload)

        self.assertEqual(asset.id, "res-1")
        self.assertEqual(resources.calls, [("patch", "res-1", payload)])

    def test_delete_delegates_asset_id(self):
        client, resources = client_with_stub()

        result = client.assets.delete("res-1")

        self.assertIsNone(result)
        self.assertEqual(resources.calls, [("delete", "res-1")])

    def test_blank_dataset_and_asset_ids_are_rejected(self):
        client, resources = client_with_stub()

        with self.assertRaisesRegex(
            ValidationError,
            "dataset id must be non-empty",
        ):
            client.assets.create_url(" ", url="https://example.test/data.csv")
        with self.assertRaisesRegex(
            ValidationError,
            "asset id must be non-empty",
        ):
            client.assets.show(" ")

        self.assertEqual(resources.calls, [])


class FailingStubResourcesResource(StubResourcesResource):
    """Stub whose `create` raises on the call with index `fail_at`."""

    def __init__(self, fail_at: int):
        super().__init__()
        self.fail_at = fail_at

    def create(self, payload: dict[str, Any], **kwargs: Any) -> CkanResourceInfo:
        if len(self.calls) == self.fail_at:
            self.calls.append(("create failed", payload, kwargs))
            raise RuntimeError("upload failed")
        return super().create(payload, **kwargs)


def write_files(directory: str, *names: str) -> list[Path]:
    paths = [Path(directory) / name for name in names]
    for path in paths:
        path.write_text(f"content of {path.name}\n")
    return paths


class TestMultiFileUpload(unittest.TestCase):
    def test_sequence_uploads_each_file_in_order_and_returns_a_list(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "data.csv", "README.md")

            assets = client.assets.upload(
                "pkg-1",
                [str(paths[0]), paths[1]],
                format="csv",
                content_type="text/csv",
            )

        self.assertIsInstance(assets, list)
        self.assertEqual(len(assets), 2)
        self.assertTrue(all(isinstance(a, DataportalAssetInfo) for a in assets))
        self.assertEqual(
            resources.calls,
            [
                (
                    "create",
                    {
                        "package_id": "pkg-1",
                        "name": path.name,
                        "format": "csv",
                        "mimetype": "text/csv",
                    },
                    {"upload": path, "content_type": "text/csv"},
                )
                for path in paths
            ],
            msg="format and content_type apply to every file",
        )

    def test_tuple_and_dataset_model_are_accepted(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "two.txt")

            assets = client.assets.upload(dataset_model("pkg-2"), tuple(paths))

        self.assertEqual(len(assets), 2)
        self.assertEqual(
            [call[1]["package_id"] for call in resources.calls], ["pkg-2", "pkg-2"]
        )

    def test_path_like_objects_are_single_paths(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "data.csv")
            with os.scandir(directory) as entries:
                entry = next(iter(entries))
            for given in (PurePath(paths[0]), entry):
                with self.subTest(type=type(given).__name__):
                    asset = client.assets.upload("pkg-1", given)
                    rdf_asset = client.assets.upload_rdf("pkg-1", given)

                    self.assertIsInstance(asset, DataportalAssetInfo)
                    self.assertIsInstance(rdf_asset, DataportalAssetInfo)
                    self.assertEqual(resources.calls[-1][2]["upload"], paths[0])

    def test_one_element_sequence_accepts_name_and_description(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "data.csv")

            assets = client.assets.upload(
                "pkg-1", paths, name="Raw data", description="Measurements."
            )

        self.assertIsInstance(assets, list)
        self.assertEqual(len(assets), 1)
        self.assertEqual(resources.calls[0][1]["name"], "Raw data")
        self.assertEqual(resources.calls[0][1]["description"], "Measurements.")

    def test_name_and_description_are_rejected_for_several_files(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "two.txt")

            for option in ("name", "description"):
                for given in (paths, []):
                    with (
                        self.subTest(option=option, paths=len(given)),
                        self.assertRaisesRegex(
                            ValidationError,
                            f"{option} is only supported for single-file uploads",
                        ),
                    ):
                        client.assets.upload("pkg-1", given, **{option: "x"})

        self.assertEqual(resources.calls, [])

    def test_empty_sequence_returns_empty_list_without_request(self):
        client, resources = client_with_stub()

        self.assertEqual(client.assets.upload("pkg-1", []), [])
        self.assertEqual(client.assets.upload_rdf("pkg-1", []), [])
        self.assertEqual(resources.calls, [])

    def test_every_path_is_checked_before_the_first_upload(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "two.txt")
            missing = Path(directory) / "missing.txt"

            for bad in (missing, Path(directory)):
                with (
                    self.subTest(bad=bad.name),
                    self.assertRaisesRegex(
                        ValidationError, re.escape(f"upload path must be a file: {bad}")
                    ),
                ):
                    client.assets.upload("pkg-1", [paths[0], bad, paths[1]])

        self.assertEqual(resources.calls, [])

    @unittest.skipIf(os.name == "nt", "Windows does not allow such file names")
    def test_blank_file_name_is_rejected_before_the_first_upload(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "   ")

            with self.assertRaisesRegex(
                ValidationError, "upload filename must be non-empty"
            ):
                client.assets.upload("pkg-1", paths)

        self.assertEqual(resources.calls, [], msg="no asset is created")

    def test_blank_options_are_rejected_before_the_first_upload(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "two.txt")

            for option in ("format", "content_type"):
                with (
                    self.subTest(option=option),
                    self.assertRaisesRegex(ValidationError, option),
                ):
                    client.assets.upload("pkg-1", paths, **{option: " "})

        self.assertEqual(resources.calls, [])

    def test_failed_upload_propagates_and_keeps_earlier_assets(self):
        client = DataportalClient(session=cast(Any, FakeSession()))
        resources = FailingStubResourcesResource(fail_at=1)
        client.resources = cast(Any, resources)

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "two.txt", "three.txt")

            with self.assertRaisesRegex(RuntimeError, "upload failed"):
                client.assets.upload("pkg-1", paths)

        self.assertEqual(
            [(call[0], call[2]["upload"]) for call in resources.calls],
            [("create", paths[0]), ("create failed", paths[1])],
            msg="the first asset stays, the third file is never sent",
        )

    def test_upload_rdf_applies_turtle_defaults_to_every_file(self):
        client, resources = client_with_stub()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "s355.ttl", "s235.ttl")

            assets = client.assets.upload_rdf("pkg-1", paths)

        self.assertEqual(len(assets), 2)
        self.assertEqual(
            [(call[1]["format"], call[2]["content_type"]) for call in resources.calls],
            [("ttl", "text/turtle"), ("ttl", "text/turtle")],
        )


def dataset_model(dataset_id: str) -> DataportalDatasetInfo:
    return DataportalDatasetInfo.from_ckan(
        CkanPackageInfo.from_dict({"id": dataset_id, "name": "dataset"})
    )


def asset_model(asset_id: str) -> DataportalAssetInfo:
    return DataportalAssetInfo.from_ckan(
        CkanResourceInfo.from_dict(resource_payload(resource_id=asset_id))
    )


class TestAssetDownloadWrappers(unittest.TestCase):
    """The `client.assets` download methods only map ids and delegate."""

    def test_download_delegates_asset_id_and_options(self):
        client, resources = client_with_stub()

        for asset in ("res-2", asset_model("res-2")):
            with self.subTest(asset=type(asset).__name__):
                resources.calls.clear()

                path = client.assets.download(
                    asset, directory="out", filename="x.csv", overwrite=True
                )

                self.assertEqual(path, DOWNLOADED)
                self.assertEqual(
                    resources.calls,
                    [
                        (
                            "download",
                            "res-2",
                            {
                                "directory": "out",
                                "filename": "x.csv",
                                "overwrite": True,
                            },
                        )
                    ],
                )

    def test_download_passes_the_default_options(self):
        client, resources = client_with_stub()

        _ = client.assets.download("res-1")

        self.assertEqual(
            resources.calls,
            [
                (
                    "download",
                    "res-1",
                    {"directory": ".", "filename": None, "overwrite": False},
                )
            ],
        )

    def test_download_all_delegates_dataset_id_and_options(self):
        client, resources = client_with_stub()
        directory = Path("out")

        for dataset in ("pkg-2", dataset_model("pkg-2")):
            with self.subTest(dataset=type(dataset).__name__):
                resources.calls.clear()

                paths = client.assets.download_all(
                    dataset, directory=directory, overwrite=True
                )

                self.assertEqual(paths, [DOWNLOADED])
                self.assertEqual(
                    resources.calls,
                    [
                        (
                            "download_all",
                            "pkg-2",
                            {"directory": directory, "overwrite": True},
                        )
                    ],
                )

    def test_download_all_passes_the_default_options(self):
        client, resources = client_with_stub()

        _ = client.assets.download_all("pkg-1")

        self.assertEqual(
            resources.calls,
            [("download_all", "pkg-1", {"directory": ".", "overwrite": False})],
        )

    def test_blank_ids_are_rejected_without_delegating(self):
        client, resources = client_with_stub()

        with self.assertRaisesRegex(ValidationError, "asset id must be non-empty"):
            client.assets.download(" ")
        with self.assertRaisesRegex(ValidationError, "dataset id must be non-empty"):
            client.assets.download_all(" ")

        self.assertEqual(resources.calls, [])


def action(result: Any) -> FakeResponse:
    return FakeResponse(json_value={"success": True, "result": result})


def uploaded(resource_id: str, name: str, **extra: Any) -> dict[str, Any]:
    return {
        **resource_payload(resource_id=resource_id),
        "url": DATAPORTAL_URL.replace("data.ttl", name),
        "url_type": "upload",
        **extra,
    }


class TestAssetDownloads(unittest.TestCase):
    """End to end through `DataportalClient` and its CKAN resources."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_download_writes_the_asset_after_one_resource_show(self):
        response = FakeResponse(body=b"abc")
        session = FakeSession([action(uploaded("res-1", "data.ttl", size=3)), response])
        client = DataportalClient(session=cast(Any, session))

        path = client.assets.download(asset_model("res-1"), directory=self.root)

        self.assertEqual(path, self.root / "data.ttl")
        self.assertEqual(path.read_bytes(), b"abc")
        self.assertEqual(
            [(call["method"], call["url"]) for call in session.calls],
            [
                (
                    "POST",
                    "https://dataportal.material-digital.de/api/3/action/resource_show",
                ),
                ("GET", DATAPORTAL_URL),
            ],
        )
        self.assertEqual(session.calls[0]["json"], {"id": "res-1"})
        self.assertTrue(response.closed)

    def test_download_all_writes_uploaded_assets_only(self):
        link = {**resource_payload(resource_id="link-1"), "url_type": ""}
        payload = {
            "id": "pkg-1",
            "name": "dataset",
            "resources": [uploaded("res-1", "a.ttl"), link, uploaded("res-2", "b.ttl")],
        }
        session = FakeSession(
            [action(payload), FakeResponse(body=b"A"), FakeResponse(body=b"B")]
        )
        client = DataportalClient(session=cast(Any, session))

        paths = client.assets.download_all(dataset_model("pkg-1"), directory=self.root)

        self.assertEqual(paths, [self.root / "a.ttl", self.root / "b.ttl"])
        self.assertEqual([p.read_bytes() for p in paths], [b"A", b"B"])
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(session.calls[0]["json"], {"id": "pkg-1"})

    def test_token_goes_to_the_dataportal_only(self):
        for url, expected in (
            (DATAPORTAL_URL, TOKEN),
            ("https://files.example.test/data.ttl", None),
        ):
            with self.subTest(url=url):

                def respond(request: requests.PreparedRequest, url: str = url) -> Reply:
                    if request.method == "POST":
                        payload = {**resource_payload(), "url": url}
                        result = {"success": True, "result": payload}
                        return 200, {}, json.dumps(result).encode()
                    return 200, {}, b"content"

                session, adapter = recording_session(respond)
                client = DataportalClient(api_token=TOKEN, session=session)

                with TemporaryDirectory() as directory:
                    path = client.assets.download("res-1", directory=directory)

                    self.assertEqual(path.read_bytes(), b"content")

                self.assertEqual(
                    [r.headers.get("Authorization") for r in adapter.requests],
                    [TOKEN, expected],
                )


if __name__ == "__main__":
    unittest.main()
