"""Dataportal-facing dataset models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from praeco.exceptions import ValidationError
from praeco.services.ckan.models import (
    CkanPackageInfo,
    CkanPackageSearchResult,
    CkanResourceInfo,
)


@dataclass(frozen=True)
class DataportalAssetInfo:
    """Important fields returned for a Dataportal asset."""

    id: str
    dataset_id: str | None
    name: str | None
    description: str | None
    url: str | None
    format: str | None
    content_type: str | None
    size: int | None
    raw: dict[str, Any]

    @classmethod
    def from_ckan(cls, resource: CkanResourceInfo) -> DataportalAssetInfo:
        """Build a Dataportal asset model from an internal CKAN model."""
        return cls(
            id=resource.id,
            dataset_id=resource.package_id,
            name=resource.name,
            description=_optional_string(resource.raw.get("description")),
            url=resource.url,
            format=resource.format,
            content_type=resource.mimetype,
            size=_optional_int(resource.raw.get("size", resource.raw.get("filesize"))),
            raw=dict(resource.raw),
        )


@dataclass(frozen=True)
class DataportalDatasetInfo:
    """Important fields returned for a Dataportal dataset."""

    id: str
    name: str
    title: str | None
    notes: str | None
    owner_org: str | None
    private: bool | None
    dataset_type: str | None
    raw: dict[str, Any]

    @classmethod
    def from_ckan(cls, package: CkanPackageInfo) -> DataportalDatasetInfo:
        """Build a Dataportal dataset model from an internal CKAN model."""
        return cls(
            id=package.id,
            name=package.name,
            title=package.title,
            notes=_optional_string(package.raw.get("notes")),
            owner_org=_optional_string(package.raw.get("owner_org")),
            private=_optional_bool(package.raw.get("private")),
            dataset_type=_optional_string(package.raw.get("type")),
            raw=dict(package.raw),
        )


@dataclass(frozen=True)
class DatasetWithAssets:
    """A dataset created by `create_with_assets` and its uploaded assets."""

    dataset: DataportalDatasetInfo
    assets: list[DataportalAssetInfo]


@dataclass(frozen=True)
class DataportalDatasetSearchResult:
    """Dataportal dataset search result."""

    count: int
    results: list[DataportalDatasetInfo]
    raw: dict[str, Any]

    @classmethod
    def from_ckan(
        cls,
        result: CkanPackageSearchResult,
    ) -> DataportalDatasetSearchResult:
        """Build a Dataportal search model from an internal CKAN result."""
        return cls(
            count=result.count,
            results=[
                DataportalDatasetInfo.from_ckan(package) for package in result.results
            ],
            raw=dict(result.raw),
        )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValidationError("private must be a boolean value")


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError("asset size must be an integer")
    if isinstance(value, int):
        size = value
    elif isinstance(value, str):
        try:
            size = int(value)
        except ValueError as exc:
            raise ValidationError("asset size must be an integer") from exc
    else:
        raise ValidationError("asset size must be an integer")
    if size < 0:
        raise ValidationError("asset size must be non-negative")
    return size
