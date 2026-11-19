"""Dataportal dataset operations."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from praeco.exceptions import ValidationError
from praeco.metadata import PublicationMetadata
from praeco.services.dataportal._uploads import (
    UploadPaths,
    check_upload_files,
    default_asset_name,
    normalize_upload_paths,
)
from praeco.services.dataportal.exceptions import DatasetUploadError
from praeco.services.dataportal.metadata import DataportalMetadata
from praeco.services.dataportal.models import (
    DataportalAssetInfo,
    DataportalDatasetInfo,
    DataportalDatasetSearchResult,
    DatasetWithAssets,
)

if TYPE_CHECKING:
    from praeco.services.dataportal.client import DataportalClient

DatasetMetadata: TypeAlias = DataportalMetadata | Mapping[str, Any]


@dataclass
class DatasetsResource:
    """Dataportal-facing dataset operations."""

    client: DataportalClient

    def create(self, metadata: DatasetMetadata) -> DataportalDatasetInfo:
        """Create a Dataportal dataset."""
        package = self.client.packages.create(_metadata_payload(metadata))
        return DataportalDatasetInfo.from_ckan(package)

    def create_with_assets(
        self,
        metadata: DataportalMetadata,
        paths: UploadPaths,
        *,
        cleanup_on_error: bool = False,
    ) -> DatasetWithAssets:
        """Create a dataset and upload its files in one step.

        The dataset is created private, the files are uploaded one at a time,
        and only then is `metadata.private` applied, so an incomplete dataset
        is never public. Nothing is published beyond what `metadata` says.

        All arguments are checked before the first request. A failing
        dataset creation propagates unchanged, since nothing was created.
        An error after that raises `DatasetUploadError`, which carries the
        dataset as created and the assets uploaded so far. By default the
        incomplete dataset is kept for inspection or for uploading the
        remaining files with `client.assets.upload`. It is still private,
        unless the request to make it public failed: that request may have
        been applied anyway, so read the dataset again to see its state.

        Parameters
        ----------
        metadata
            Complete Dataportal metadata. `private` must be True or False,
            and `owner_org` must be set, because CKAN keeps private datasets
            only in an organization.
        paths
            One file path or a non-empty sequence of file paths. Each file
            becomes an asset named after the file.
        cleanup_on_error
            Delete the dataset when an error occurs after it was created.
            CKAN only marks a deleted dataset as deleted: its name stays taken
            until a sysadmin purges it, so a retry needs another name.

        Returns
        -------
        result
            The dataset as the Dataportal reports it after the last step, and
            the uploaded assets in the given order.

        Raises
        ------
        ValidationError
            Before any request, if `metadata` is not valid
            `DataportalMetadata`, `private` or `owner_org` is not set, `paths`
            is empty, a path is not a file, or a file name is blank.
        DatasetUploadError
            If uploading, making the dataset public, or reading it back
            fails after the dataset was created.
        """
        upload_paths = _checked_create_with_assets_arguments(metadata, paths)
        make_public = metadata.private is False
        dataset = self.create(dataclasses.replace(metadata, private=True))
        assets: list[DataportalAssetInfo] = []
        step = "uploading its files"
        try:
            for path in upload_paths:
                assets.append(self.client.assets.upload(dataset, path))
            if make_public:
                step = "making it public"
                final = self.patch(dataset, {"private": False})
            else:
                step = "reading it back"
                final = self.show(dataset)
        except Exception as exc:
            raise self._upload_error(
                dataset,
                assets,
                total=len(upload_paths),
                step=step,
                error=exc,
                cleanup=cleanup_on_error,
                visibility_unknown=step == "making it public",
            ) from exc
        return DatasetWithAssets(dataset=final, assets=assets)

    def _upload_error(
        self,
        dataset: DataportalDatasetInfo,
        assets: list[DataportalAssetInfo],
        *,
        total: int,
        step: str,
        error: Exception,
        cleanup: bool,
        visibility_unknown: bool,
    ) -> DatasetUploadError:
        delete_error: Exception | None = None
        if cleanup:
            try:
                self.delete(dataset)
            except Exception as exc:
                delete_error = exc
        # A failed request to make the dataset public may still have been
        # applied, for example if only its response was lost.
        if not cleanup:
            outcome = (
                "the dataset was kept and may already be public"
                if visibility_unknown
                else "the private dataset was kept"
            )
        elif delete_error is None:
            outcome = "the dataset was deleted"
        else:
            outcome = "deleting the dataset failed too; " + (
                "it may already be public" if visibility_unknown else "it stays private"
            )
        upload_error = DatasetUploadError(
            f"dataset {dataset.name!r} ({dataset.id}) was created, but "
            f"{step} failed after {len(assets)} of {total} files were uploaded; "
            f"{outcome}: {error}",
            dataset=dataset,
            assets=list(assets),
            deleted=cleanup and delete_error is None,
        )
        if delete_error is not None:
            upload_error.add_note(
                f"deleting dataset {dataset.id} failed: "
                f"{type(delete_error).__name__}: {delete_error}"
            )
        return upload_error

    def show(self, dataset: str | DataportalDatasetInfo) -> DataportalDatasetInfo:
        """Retrieve a Dataportal dataset by id, name, or dataset model."""
        package = self.client.packages.show(_dataset_id(dataset))
        return DataportalDatasetInfo.from_ckan(package)

    def search(
        self,
        query: str | None = None,
        **filters: Any,
    ) -> DataportalDatasetSearchResult:
        """Search Dataportal datasets."""
        result = self.client.packages.search(query, **filters)
        return DataportalDatasetSearchResult.from_ckan(result)

    def patch(
        self,
        dataset: str | DataportalDatasetInfo,
        metadata: DatasetMetadata,
    ) -> DataportalDatasetInfo:
        """Partially update a Dataportal dataset."""
        package = self.client.packages.patch(
            _dataset_id(dataset),
            _metadata_payload(metadata),
        )
        return DataportalDatasetInfo.from_ckan(package)

    def delete(self, dataset: str | DataportalDatasetInfo) -> None:
        """Delete a Dataportal dataset."""
        self.client.packages.delete(_dataset_id(dataset))


def _dataset_id(dataset: str | DataportalDatasetInfo) -> str:
    if isinstance(dataset, DataportalDatasetInfo):
        return dataset.id
    text = str(dataset).strip()
    if not text:
        raise ValidationError("dataset id must be non-empty")
    return text


def _metadata_payload(metadata: DatasetMetadata) -> dict[str, Any]:
    if isinstance(metadata, DataportalMetadata):
        return metadata.to_payload()
    if isinstance(metadata, PublicationMetadata):
        raise ValidationError(
            "dataset metadata must be wrapped in DataportalMetadata; "
            "plain PublicationMetadata is not accepted"
        )
    if isinstance(metadata, Mapping):
        return dict(metadata)
    raise ValidationError("dataset metadata must be DataportalMetadata or a mapping")


def _checked_create_with_assets_arguments(
    metadata: object,
    paths: UploadPaths,
) -> list[Path]:
    if not isinstance(metadata, DataportalMetadata):
        raise ValidationError(
            "create_with_assets requires DataportalMetadata, "
            f"not {type(metadata).__name__}"
        )
    metadata.validate()
    if metadata.private is None:
        raise ValidationError(
            "create_with_assets requires metadata.private to be True or False"
        )
    if metadata.owner_org is None:
        raise ValidationError(
            "create_with_assets requires metadata.owner_org: the dataset is "
            "private until its files are uploaded, and CKAN keeps private "
            "datasets only in an organization"
        )
    upload_paths = normalize_upload_paths(paths)
    if not upload_paths:
        raise ValidationError(
            "create_with_assets requires at least one path; "
            "use create for a dataset without files"
        )
    check_upload_files(upload_paths)
    for path in upload_paths:
        _ = default_asset_name(path)
    return upload_paths
