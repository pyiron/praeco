"""Dataportal asset operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from praeco.exceptions import ValidationError
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

    def upload(
        self,
        dataset: str | DataportalDatasetInfo,
        path: str | Path,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str | None = None,
        content_type: str | None = None,
    ) -> DataportalAssetInfo:
        """Upload a local file as a Dataportal asset."""
        upload_path = Path(path)
        if not upload_path.is_file():
            raise ValidationError(f"upload path must be a file: {upload_path}")

        filename = _required_string(upload_path.name, "upload filename")
        normalized_content_type = (
            _required_string(content_type, "content_type")
            if content_type is not None
            else None
        )
        payload: dict[str, Any] = {
            "package_id": _dataset_id(dataset),
            "name": _required_string(name, "name") if name is not None else filename,
        }
        _add_if_present(payload, "description", description)
        _add_if_present(payload, "format", format)
        _add_if_present(payload, "mimetype", normalized_content_type)

        resource = self.client.resources.create(
            payload,
            upload=upload_path,
            content_type=normalized_content_type,
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

    def upload_rdf(
        self,
        dataset: str | DataportalDatasetInfo,
        path: str | Path,
        *,
        name: str | None = None,
        description: str | None = None,
        format: str = "ttl",
        content_type: str = "text/turtle",
    ) -> DataportalAssetInfo:
        """Upload an RDF file with conservative Turtle defaults."""
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
