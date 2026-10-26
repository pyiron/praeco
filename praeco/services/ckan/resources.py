"""CKAN resource skeleton."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from praeco.exceptions import ValidationError
from praeco.services.ckan._download import (
    check_file_name,
    check_unique_names,
    content_url,
    default_file_name,
    expected_size,
    open_content,
    target_paths,
)
from praeco.services.ckan.models import CkanPackageInfo, CkanResourceInfo
from praeco.transport.download import write_response_to_path

if TYPE_CHECKING:
    from praeco.services.ckan.client import CkanClient

UploadPath = str | Path


@dataclass
class ResourcesResource:
    """CKAN resource actions."""

    client: CkanClient

    def create(
        self,
        payload: Mapping[str, Any],
        *,
        upload: UploadPath | None = None,
        content_type: str | None = None,
    ) -> CkanResourceInfo:
        """Create a CKAN resource."""
        if upload is not None:
            return self._create_with_upload(
                payload,
                upload,
                content_type=content_type,
            )
        if content_type is not None:
            raise ValidationError("content_type requires an upload path")
        return CkanResourceInfo.from_dict(
            self.client.action.call("resource_create", payload)
        )

    def show(self, resource: str | CkanResourceInfo) -> CkanResourceInfo:
        """Show a CKAN resource by id or resource model."""
        result = self.client.action.call(
            "resource_show", {"id": _resource_id(resource)}
        )
        return CkanResourceInfo.from_dict(result)

    def patch(
        self,
        resource: str | CkanResourceInfo,
        payload: Mapping[str, Any],
    ) -> CkanResourceInfo:
        """Partially update a CKAN resource."""
        data = dict(payload)
        data["id"] = _resource_id(resource)
        return CkanResourceInfo.from_dict(
            self.client.action.call("resource_patch", data)
        )

    def delete(self, resource: str | CkanResourceInfo) -> None:
        """Delete a CKAN resource."""
        _ = self.client.action.call("resource_delete", {"id": _resource_id(resource)})

    def download(
        self,
        resource: str | CkanResourceInfo,
        *,
        directory: str | Path = ".",
        filename: str | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Download the content of a CKAN resource into `directory`.

        The resource metadata is fetched first, also for a resource model. The
        file is named `filename` if given, else after the last segment of the
        content URL's path, else after the resource id. The session's
        ``Authorization`` header is sent only if the content URL has the
        client's own origin. Returns ``Path(directory) / name``.
        """
        if filename is not None:
            check_file_name(filename)
        info = self.show(resource)
        url = content_url(info)
        name = filename if filename is not None else default_file_name(info, url)
        [target] = target_paths(directory, [name], overwrite=overwrite)
        return self._write_content(info, url, target, overwrite=overwrite)

    def download_all(
        self,
        package: str | CkanPackageInfo,
        *,
        directory: str | Path = ".",
        overwrite: bool = False,
    ) -> list[Path]:
        """Download every uploaded resource of a CKAN package into `directory`.

        Only resources with ``url_type == "upload"`` are downloaded, one at a
        time in the server's order; link resources are skipped. Files are
        named as in `download` without `filename`. Returns the written paths;
        files completed before a failure are kept.
        """
        uploads = [
            resource
            for resource in self.client.packages.show(package).resources
            if resource.raw.get("url_type") == "upload"
        ]
        urls = [content_url(resource) for resource in uploads]
        names = [
            default_file_name(resource, url)
            for resource, url in zip(uploads, urls, strict=True)
        ]
        check_unique_names(uploads, names)
        targets = target_paths(directory, names, overwrite=overwrite)
        return [
            self._write_content(resource, url, target, overwrite=overwrite)
            for resource, url, target in zip(uploads, urls, targets, strict=True)
        ]

    def _write_content(
        self,
        resource: CkanResourceInfo,
        url: str,
        target: Path,
        *,
        overwrite: bool,
    ) -> Path:
        # Read the size first, so nothing can fail while the response is open.
        size = expected_size(resource)
        return write_response_to_path(
            open_content(self.client, url),
            target,
            overwrite=overwrite,
            size=size,
        )

    def _create_with_upload(
        self,
        payload: Mapping[str, Any],
        upload: UploadPath,
        *,
        content_type: str | None,
    ) -> CkanResourceInfo:
        data = dict(payload)
        if "upload" in data:
            raise ValidationError(
                "payload must not include an upload field when upload is provided"
            )

        path = Path(upload)
        filename = path.name.strip()
        if not filename:
            raise ValidationError("upload filename must be non-empty")
        if not path.is_file():
            raise ValidationError(f"upload path must be a file: {path}")
        normalized_content_type = _optional_string(content_type, "content_type")

        with path.open("rb") as file:
            upload_file: tuple[str, Any] | tuple[str, Any, str]
            if normalized_content_type is None:
                upload_file = (filename, file)
            else:
                upload_file = (filename, file, normalized_content_type)
            result = self.client.action.call(
                "resource_create",
                data,
                files={"upload": upload_file},
            )
        return CkanResourceInfo.from_dict(result)


def _resource_id(resource: str | CkanResourceInfo) -> str:
    value = resource.id if isinstance(resource, CkanResourceInfo) else resource
    text = str(value).strip()
    if not text:
        raise ValidationError("resource id must be non-empty")
    return text


def _optional_string(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        raise ValidationError(f"{field_name} must be non-empty")
    return text
