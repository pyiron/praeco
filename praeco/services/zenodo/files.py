"""Zenodo deposition file operations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from praeco.exceptions import ValidationError
from praeco.services.zenodo._response import read_zenodo_json, read_zenodo_text
from praeco.services.zenodo._urls import (
    bucket_file_url,
    deposition_file_url,
    deposition_files_url,
)
from praeco.services.zenodo.models import DepositionInfo, UploadedFileInfo

if TYPE_CHECKING:
    from praeco.services.zenodo.client import ZenodoClient

UploadPath: TypeAlias = str | Path
UploadPaths: TypeAlias = UploadPath | Sequence[UploadPath]
UploadedFiles: TypeAlias = list[UploadedFileInfo]


@dataclass
class FilesResource:
    """Zenodo draft file operations."""

    client: ZenodoClient

    def list(self, deposition: int | str | DepositionInfo) -> UploadedFiles:
        """List files attached to a deposition."""
        url = deposition_files_url(self.client.base_url, _deposition_id(deposition))
        payload = read_zenodo_json(self.client.request("GET", url))
        if not isinstance(payload, list):
            raise ValidationError("Zenodo file list response must be a list")
        return [UploadedFileInfo.from_dict(item) for item in payload]

    def upload(
        self,
        deposition: int | str | DepositionInfo,
        paths: UploadPaths,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> UploadedFiles:
        """Upload one or more files through the deposition bucket link.

        Every path is checked to be a file before the first request, so a
        wrong path anywhere in `paths` uploads nothing.
        """
        upload_paths = _upload_paths(paths)
        single_file = len(upload_paths) == 1
        if not single_file:
            if filename is not None:
                raise ValidationError(
                    "filename is only supported for single-file uploads"
                )
            if content_type is not None:
                raise ValidationError(
                    "content_type is only supported for single-file uploads"
                )
        if not upload_paths:
            return []
        filenames = [
            _upload_filename(path, filename=filename if single_file else None)
            for path in upload_paths
        ]
        for path in upload_paths:
            if not path.is_file():
                raise ValidationError(f"upload path must be a file: {path}")

        deposition_info = self._ensure_deposition(deposition)
        bucket_url = deposition_info.links.bucket
        if not bucket_url:
            raise ValidationError("deposition does not include a bucket upload link")

        return [
            self._upload_one(
                bucket_url,
                path,
                filename=file_name,
                content_type=content_type,
            )
            for path, file_name in zip(upload_paths, filenames, strict=True)
        ]

    def _upload_one(
        self,
        bucket_url: str,
        path: Path,
        *,
        filename: str,
        content_type: str | None = None,
    ) -> UploadedFileInfo:
        headers = {"Content-Type": content_type} if content_type else None
        with path.open("rb") as file:
            resp = self.client.request(
                "PUT",
                bucket_file_url(bucket_url, filename),
                data=file,
                headers=headers,
            )
        return UploadedFileInfo.from_dict(read_zenodo_json(resp))

    def rename(
        self,
        deposition: int | str | DepositionInfo,
        file_id: str,
        name: str,
    ) -> UploadedFileInfo:
        """Rename an uploaded deposition file."""
        name = name.strip()
        if not name:
            raise ValidationError("name must be non-empty")

        url = deposition_file_url(
            self.client.base_url, _deposition_id(deposition), file_id
        )
        resp = self.client.request("PUT", url, json={"filename": name})
        return UploadedFileInfo.from_dict(read_zenodo_json(resp))

    def delete(self, deposition: int | str | DepositionInfo, file_id: str) -> None:
        """Delete a file from an unpublished deposition."""
        url = deposition_file_url(
            self.client.base_url, _deposition_id(deposition), file_id
        )
        _ = read_zenodo_text(self.client.request("DELETE", url))

    def _ensure_deposition(
        self,
        deposition: int | str | DepositionInfo,
    ) -> DepositionInfo:
        if isinstance(deposition, DepositionInfo):
            if deposition.links.bucket:
                return deposition
            return self.client.depositions.get(deposition.id)
        return self.client.depositions.get(deposition)


def _deposition_id(deposition: int | str | DepositionInfo) -> int | str:
    if isinstance(deposition, DepositionInfo):
        return deposition.id
    return deposition


def _upload_paths(paths: UploadPaths) -> list[Path]:
    if isinstance(paths, (str, Path)):
        return [Path(paths)]
    return [Path(path) for path in paths]


def _upload_filename(path: Path, *, filename: str | None = None) -> str:
    file_name = (filename or path.name).strip()
    if not file_name:
        raise ValidationError("filename must be non-empty")
    return file_name
