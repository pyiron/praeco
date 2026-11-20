"""Dataportal asset operations."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload
from urllib.parse import urlsplit

from praeco.exceptions import ValidationError
from praeco.services.dataportal._uploads import (
    UploadPath,
    UploadPaths,
    UploadPathT,
    check_upload_files,
    default_asset_name,
    normalize_upload_paths,
)
from praeco.services.dataportal.models import (
    DataportalAssetInfo,
    DataportalDatasetInfo,
)

if TYPE_CHECKING:
    from praeco.services.dataportal.client import DataportalClient


@dataclass
class AssetsResource:
    """Dataportal-facing asset operations."""

    client: DataportalClient

    @overload
    def upload(
        self,
        dataset: str | DataportalDatasetInfo,
        path: UploadPath,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str | None = None,
        content_type: str | None = None,
    ) -> DataportalAssetInfo: ...

    @overload
    def upload(
        self,
        dataset: str | DataportalDatasetInfo,
        path: list[UploadPathT] | tuple[UploadPathT, ...],
        *,
        name: str | None = None,
        description: str | None = None,
        format: str | None = None,
        content_type: str | None = None,
    ) -> list[DataportalAssetInfo]: ...

    @overload
    def upload(
        self,
        dataset: str | DataportalDatasetInfo,
        path: UploadPaths,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str | None = None,
        content_type: str | None = None,
    ) -> DataportalAssetInfo | list[DataportalAssetInfo]: ...

    def upload(
        self,
        dataset: str | DataportalDatasetInfo,
        path: UploadPaths,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str | None = None,
        content_type: str | None = None,
    ) -> DataportalAssetInfo | list[DataportalAssetInfo]:
        """Upload one or more local files as Dataportal assets.

        Every path is checked to be a file before the first request, so a
        wrong path anywhere in a sequence uploads nothing. The files are then
        uploaded one at a time in the given order. If an upload fails, the
        assets uploaded before it remain and the error propagates.

        Parameters
        ----------
        dataset
            Dataset id, name, or model.
        path
            One file path, or a sequence of file paths.
        name
            Asset name, for a single file only. Defaults to the file name.
        description
            Asset description, for a single file only.
        format
            Asset format, applied to every file.
        content_type
            MIME type sent with every file and stored as its ``mimetype``.

        Returns
        -------
        asset
            The uploaded asset for a single path, or a list of assets in the
            given order for a sequence of paths.

        Raises
        ------
        ValidationError
            If a path is not a file, an option is blank, or `name` or
            `description` is given for other than exactly one file.
        """
        upload_paths = normalize_upload_paths(path)
        if len(upload_paths) != 1:
            for option, value in (("name", name), ("description", description)):
                if value is not None:
                    raise ValidationError(
                        f"{option} is only supported for single-file uploads"
                    )
        check_upload_files(upload_paths)

        options: dict[str, Any] = {}
        _add_if_present(options, "description", description)
        _add_if_present(options, "format", format)
        if content_type is not None:
            options["mimetype"] = _required_string(content_type, "content_type")
        asset_names = [
            (
                _required_string(name, "name")
                if name is not None
                else default_asset_name(upload_path)
            )
            for upload_path in upload_paths
        ]
        if not upload_paths:
            return []

        package_id = _dataset_id(dataset)
        assets = [
            self._upload_one(package_id, upload_path, name=asset_name, options=options)
            for upload_path, asset_name in zip(upload_paths, asset_names, strict=True)
        ]
        if isinstance(path, (str, os.PathLike)):
            return assets[0]
        return assets

    def _upload_one(
        self,
        package_id: str,
        path: Path,
        *,
        name: str,
        options: Mapping[str, Any],
    ) -> DataportalAssetInfo:
        payload: dict[str, Any] = {"package_id": package_id, "name": name, **options}
        resource = self.client.resources.create(
            payload,
            upload=path,
            content_type=options.get("mimetype"),
        )
        return DataportalAssetInfo.from_ckan(resource)

    def create_url(
        self,
        dataset: str | DataportalDatasetInfo,
        *,
        url: str,
        name: str | None = None,
        description: str | None = None,
        format: str | None = None,
    ) -> DataportalAssetInfo:
        """Create an asset that references an external HTTP(S) URL."""
        payload: dict[str, Any] = {
            "package_id": _dataset_id(dataset),
            "url": _absolute_http_url(url),
        }
        _add_if_present(payload, "name", name)
        _add_if_present(payload, "description", description)
        _add_if_present(payload, "format", format)
        return DataportalAssetInfo.from_ckan(self.client.resources.create(payload))

    @overload
    def upload_rdf(
        self,
        dataset: str | DataportalDatasetInfo,
        path: UploadPath,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str = "ttl",
        content_type: str = "text/turtle",
    ) -> DataportalAssetInfo: ...

    @overload
    def upload_rdf(
        self,
        dataset: str | DataportalDatasetInfo,
        path: list[UploadPathT] | tuple[UploadPathT, ...],
        *,
        name: str | None = None,
        description: str | None = None,
        format: str = "ttl",
        content_type: str = "text/turtle",
    ) -> list[DataportalAssetInfo]: ...

    @overload
    def upload_rdf(
        self,
        dataset: str | DataportalDatasetInfo,
        path: UploadPaths,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str = "ttl",
        content_type: str = "text/turtle",
    ) -> DataportalAssetInfo | list[DataportalAssetInfo]: ...

    def upload_rdf(
        self,
        dataset: str | DataportalDatasetInfo,
        path: UploadPaths,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str = "ttl",
        content_type: str = "text/turtle",
    ) -> DataportalAssetInfo | list[DataportalAssetInfo]:
        """Upload one or more RDF files with conservative Turtle defaults.

        Accepts the same paths and follows the same rules as `upload`;
        `format` and `content_type` apply to every file.
        """
        return self.upload(
            dataset,
            path,
            name=name,
            description=description,
            format=format,
            content_type=content_type,
        )

    def show(self, asset: str | DataportalAssetInfo) -> DataportalAssetInfo:
        """Retrieve an asset by id or asset model."""
        return DataportalAssetInfo.from_ckan(
            self.client.resources.show(_asset_id(asset))
        )

    def patch(
        self,
        asset: str | DataportalAssetInfo,
        payload: Mapping[str, Any],
    ) -> DataportalAssetInfo:
        """Partially update asset metadata."""
        return DataportalAssetInfo.from_ckan(
            self.client.resources.patch(_asset_id(asset), payload)
        )

    def delete(self, asset: str | DataportalAssetInfo) -> None:
        """Delete an asset."""
        self.client.resources.delete(_asset_id(asset))

    def download(
        self,
        asset: str | DataportalAssetInfo,
        *,
        directory: str | Path = ".",
        filename: str | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Download an asset's content into `directory` and return its path.

        See `CkanClient.resources.download` for naming, token, and overwrite
        rules.
        """
        return self.client.resources.download(
            _asset_id(asset),
            directory=directory,
            filename=filename,
            overwrite=overwrite,
        )

    def download_all(
        self,
        dataset: str | DataportalDatasetInfo,
        *,
        directory: str | Path = ".",
        overwrite: bool = False,
    ) -> list[Path]:
        """Download every uploaded asset of a dataset into `directory`.

        Link assets are skipped. See `CkanClient.resources.download_all`.
        """
        return self.client.resources.download_all(
            _dataset_id(dataset),
            directory=directory,
            overwrite=overwrite,
        )


def _dataset_id(dataset: str | DataportalDatasetInfo) -> str:
    if isinstance(dataset, DataportalDatasetInfo):
        return dataset.id
    return _required_string(dataset, "dataset id")


def _asset_id(asset: str | DataportalAssetInfo) -> str:
    if isinstance(asset, DataportalAssetInfo):
        return asset.id
    return _required_string(asset, "asset id")


def _absolute_http_url(value: str) -> str:
    url = _required_string(value, "url")
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValidationError("url must be an absolute HTTP(S) URL")
    return url


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be non-empty")
    return value.strip()


def _add_if_present(data: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        data[key] = _required_string(value, key)
