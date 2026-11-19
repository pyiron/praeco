import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from praeco.exceptions import PraecoError, ValidationError
from praeco.metadata import Person, PublicationMetadata
from praeco.services.ckan.models import CkanPackageInfo, CkanResourceInfo
from praeco.services.dataportal import (
    DataportalAssetInfo,
    DataportalClient,
    DataportalMetadata,
    DatasetUploadError,
    DatasetWithAssets,
)

from ._helpers import FakeSession


def package_payload(*, private: bool, resources: int = 0) -> dict[str, Any]:
    return {
        "id": "pkg-1",
        "name": "steel-data",
        "title": "Steel data",
        "owner_org": "materials-org",
        "private": private,
        "type": "dataset",
        "num_resources": resources,
    }


class Recorder:
    """Stubs for the CKAN package and resource layers sharing one call log.

    `failures` maps a call name to the exception it raises; for "upload",
    the value is a pair of the failing upload's index and the exception.
    """

    def __init__(self, failures: dict[str, Any] | None = None):
        self.calls: list[tuple[Any, ...]] = []
        self.failures = failures or {}
        self.uploads = 0

    def _maybe_fail(self, name: str) -> None:
        if name in self.failures:
            raise self.failures[name]

    # packages
    def create(self, payload: dict[str, Any]) -> CkanPackageInfo:
        self.calls.append(("create", payload))
        self._maybe_fail("create")
        return CkanPackageInfo.from_dict(package_payload(private=payload["private"]))

    def show(self, package: str) -> CkanPackageInfo:
        self.calls.append(("show", package))
        self._maybe_fail("show")
        return CkanPackageInfo.from_dict(
            package_payload(private=True, resources=self.uploads)
        )

    def patch(self, package: str, payload: dict[str, Any]) -> CkanPackageInfo:
        self.calls.append(("patch", package, payload))
        self._maybe_fail("patch")
        return CkanPackageInfo.from_dict(
            package_payload(private=payload["private"], resources=self.uploads)
        )

    def delete(self, package: str) -> None:
        self.calls.append(("delete", package))
        self._maybe_fail("delete")


class ResourceRecorder:
    def __init__(self, recorder: Recorder):
        self.recorder = recorder

    def create(self, payload: dict[str, Any], **kwargs: Any) -> CkanResourceInfo:
        recorder = self.recorder
        recorder.calls.append(("upload", payload["package_id"], kwargs["upload"]))
        failure = recorder.failures.get("upload")
        if failure is not None and failure[0] == recorder.uploads:
            raise failure[1]
        recorder.uploads += 1
        return CkanResourceInfo.from_dict(
            {
                "id": f"res-{recorder.uploads}",
                "package_id": payload["package_id"],
                "name": payload["name"],
                "url_type": "upload",
            }
        )


def client_with(
    failures: dict[str, Any] | None = None,
) -> tuple[DataportalClient, Recorder]:
    client = DataportalClient(session=cast(Any, FakeSession()))
    recorder = Recorder(failures)
    client.packages = cast(Any, recorder)
    client.resources = cast(Any, ResourceRecorder(recorder))
    return client, recorder


def metadata(**overrides: Any) -> DataportalMetadata:
    fields: dict[str, Any] = {
        "metadata": PublicationMetadata(
            title="Steel data",
            description="Heat treatment measurements.",
            creators=[Person(name="Doe, Jane")],
        ),
        "name": "steel-data",
        "owner_org": "materials-org",
        "private": False,
    }
    fields.update(overrides)
    return DataportalMetadata(**fields)


def write_files(directory: str, *names: str) -> list[Path]:
    paths = [Path(directory) / name for name in names]
    for path in paths:
        path.write_text(f"content of {path.name}\n")
    return paths


def call_names(recorder: Recorder) -> list[str]:
    return [call[0] for call in recorder.calls]


class TestCreateWithAssets(unittest.TestCase):
    def test_public_dataset_is_created_private_and_made_public_last(self):
        client, recorder = client_with()
        md = metadata(private=False)

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "data.csv", "README.md")

            result = client.datasets.create_with_assets(md, paths)

        self.assertIsInstance(result, DatasetWithAssets)
        self.assertEqual(call_names(recorder), ["create", "upload", "upload", "patch"])
        create_payload = recorder.calls[0][1]
        self.assertIs(create_payload["private"], True)
        self.assertEqual(create_payload["owner_org"], "materials-org")
        self.assertEqual(create_payload["name"], "steel-data")
        self.assertEqual(
            recorder.calls[1:3],
            [("upload", "pkg-1", paths[0]), ("upload", "pkg-1", paths[1])],
        )
        self.assertEqual(recorder.calls[3], ("patch", "pkg-1", {"private": False}))
        self.assertIs(result.dataset.private, False)
        self.assertEqual(result.dataset.raw["num_resources"], 2)
        self.assertEqual(
            [asset.name for asset in result.assets], [p.name for p in paths]
        )
        self.assertTrue(
            all(isinstance(asset, DataportalAssetInfo) for asset in result.assets)
        )
        self.assertIs(md.private, False, msg="the caller's metadata is not changed")

    def test_private_dataset_is_read_back_instead_of_patched(self):
        client, recorder = client_with()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "data.csv")

            result = client.datasets.create_with_assets(
                metadata(private=True), str(paths[0])
            )

        self.assertEqual(call_names(recorder), ["create", "upload", "show"])
        self.assertIs(recorder.calls[0][1]["private"], True)
        self.assertIs(result.dataset.private, True)
        self.assertEqual(result.dataset.raw["num_resources"], 1)
        self.assertEqual(len(result.assets), 1)

    def test_invalid_arguments_are_rejected_before_any_request(self):
        client, recorder = client_with()

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "data.csv")
            missing = Path(directory) / "missing.csv"
            cases: list[tuple[str, Any, Any, str]] = [
                (
                    "publication metadata",
                    metadata().metadata,
                    paths,
                    "requires DataportalMetadata, not PublicationMetadata",
                ),
                (
                    "mapping",
                    {"name": "steel-data"},
                    paths,
                    "requires DataportalMetadata, not dict",
                ),
                (
                    "private unset",
                    metadata(private=None),
                    paths,
                    "metadata.private to be True or False",
                ),
                (
                    "owner_org unset",
                    metadata(owner_org=None),
                    paths,
                    "requires metadata.owner_org",
                ),
                ("no paths", metadata(), [], "requires at least one path"),
                (
                    "missing path",
                    metadata(),
                    [paths[0], missing],
                    re.escape(f"upload path must be a file: {missing}"),
                ),
                (
                    "directory",
                    metadata(),
                    directory,
                    "upload path must be a file",
                ),
            ]
            for label, md, given, message in cases:
                with (
                    self.subTest(label),
                    self.assertRaisesRegex(ValidationError, message),
                ):
                    client.datasets.create_with_assets(md, given)

        self.assertEqual(recorder.calls, [])

    def test_failing_create_propagates_unchanged(self):
        client, recorder = client_with({"create": RuntimeError("create failed")})

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "data.csv")

            with self.assertRaisesRegex(RuntimeError, "create failed"):
                client.datasets.create_with_assets(
                    metadata(), paths, cleanup_on_error=True
                )

        self.assertEqual(call_names(recorder), ["create"])

    def test_failed_upload_keeps_the_private_dataset_by_default(self):
        original = RuntimeError("upload failed")
        client, recorder = client_with({"upload": (1, original)})

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "two.txt", "three.txt")

            with self.assertRaises(DatasetUploadError) as ctx:
                client.datasets.create_with_assets(metadata(), paths)

        error = ctx.exception
        self.assertIsInstance(error, PraecoError)
        self.assertIs(error.__cause__, original)
        self.assertEqual(error.dataset.id, "pkg-1")
        self.assertIs(error.dataset.private, True)
        self.assertEqual([asset.id for asset in error.assets], ["res-1"])
        self.assertIs(error.deleted, False)
        self.assertEqual(
            str(error),
            "dataset 'steel-data' (pkg-1) was created, but uploading its files "
            "failed after 1 of 3 files were uploaded; the private dataset was "
            "kept: upload failed",
        )
        self.assertEqual(
            call_names(recorder),
            ["create", "upload", "upload"],
            msg="neither the third file, the patch, nor a delete is sent",
        )

    def test_failed_upload_deletes_the_dataset_with_cleanup(self):
        client, recorder = client_with({"upload": (0, RuntimeError("upload failed"))})

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt", "two.txt")

            with self.assertRaises(DatasetUploadError) as ctx:
                client.datasets.create_with_assets(
                    metadata(), paths, cleanup_on_error=True
                )

        error = ctx.exception
        self.assertIs(error.deleted, True)
        self.assertEqual(error.assets, [])
        self.assertIn("after 0 of 2 files", str(error))
        self.assertIn("the dataset was deleted", str(error))
        self.assertEqual(call_names(recorder), ["create", "upload", "delete"])
        self.assertEqual(recorder.calls[-1], ("delete", "pkg-1"))

    def test_failed_cleanup_is_reported_as_a_note(self):
        original = RuntimeError("upload failed")
        client, recorder = client_with(
            {
                "upload": (0, original),
                "delete": RuntimeError("delete failed"),
            }
        )

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt")

            with self.assertRaises(DatasetUploadError) as ctx:
                client.datasets.create_with_assets(
                    metadata(), paths, cleanup_on_error=True
                )

        error = ctx.exception
        self.assertIs(error.deleted, False)
        self.assertIs(error.__cause__, original)
        self.assertIn("deleting the dataset failed too; it stays private", str(error))
        self.assertEqual(
            error.__notes__,
            ["deleting dataset pkg-1 failed: RuntimeError: delete failed"],
        )
        self.assertEqual(call_names(recorder), ["create", "upload", "delete"])

    def test_failed_final_step_carries_every_asset(self):
        for private, step, final_call in (
            (False, "making it public", "patch"),
            (True, "reading it back", "show"),
        ):
            with self.subTest(private=private):
                client, recorder = client_with(
                    {final_call: RuntimeError(f"{final_call} failed")}
                )

                with TemporaryDirectory() as directory:
                    paths = write_files(directory, "one.txt", "two.txt")

                    with self.assertRaises(DatasetUploadError) as ctx:
                        client.datasets.create_with_assets(
                            metadata(private=private), paths
                        )

                error = ctx.exception
                self.assertEqual(len(error.assets), 2)
                self.assertIn(
                    f"but {step} failed after 2 of 2 files were uploaded",
                    str(error),
                )
                self.assertEqual(
                    call_names(recorder), ["create", "upload", "upload", final_call]
                )

    def test_interrupt_propagates_without_cleanup(self):
        client, recorder = client_with({"upload": (0, KeyboardInterrupt())})

        with TemporaryDirectory() as directory:
            paths = write_files(directory, "one.txt")

            with self.assertRaises(KeyboardInterrupt):
                client.datasets.create_with_assets(
                    metadata(), paths, cleanup_on_error=True
                )

        self.assertEqual(call_names(recorder), ["create", "upload"])


if __name__ == "__main__":
    unittest.main()
