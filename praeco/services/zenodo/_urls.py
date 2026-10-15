"""URL helpers for Zenodo REST endpoints."""

from __future__ import annotations

from praeco.exceptions import ValidationError
from praeco.transport.url import join_url, quote_path_segment


def depositions_url(base_url: str) -> str:
    return join_url(base_url, segments=["api", "deposit", "depositions"])


def deposition_url(base_url: str, deposition_id: int | str) -> str:
    return join_url(
        base_url,
        segments=[
            "api",
            "deposit",
            "depositions",
            quote_path_segment(deposition_id, field_name="id"),
        ],
    )


def deposition_action_url(
    base_url: str,
    deposition_id: int | str,
    action: str,
) -> str:
    allowed = {"discard", "edit", "newversion", "publish"}
    if action not in allowed:
        raise ValidationError(f"unsupported deposition action: {action!r}")
    return join_url(
        base_url,
        segments=[
            "api",
            "deposit",
            "depositions",
            quote_path_segment(deposition_id, field_name="id"),
            "actions",
            action,
        ],
    )


def deposition_files_url(base_url: str, deposition_id: int | str) -> str:
    return join_url(
        base_url,
        segments=[
            "api",
            "deposit",
            "depositions",
            quote_path_segment(deposition_id, field_name="id"),
            "files",
        ],
    )


def deposition_file_url(
    base_url: str,
    deposition_id: int | str,
    file_id: str,
) -> str:
    return join_url(
        base_url,
        segments=[
            "api",
            "deposit",
            "depositions",
            quote_path_segment(deposition_id, field_name="id"),
            "files",
            quote_path_segment(file_id, field_name="file_id"),
        ],
    )


def record_files_url(base_url: str, record_id: int | str) -> str:
    return join_url(
        base_url,
        segments=[
            "api",
            "records",
            quote_path_segment(record_id, field_name="id"),
            "files",
        ],
    )


def record_draft_files_url(base_url: str, record_id: int | str) -> str:
    return join_url(
        base_url,
        segments=[
            "api",
            "records",
            quote_path_segment(record_id, field_name="id"),
            "draft",
            "files",
        ],
    )


def licenses_url(base_url: str) -> str:
    return join_url(base_url, segments=["api", "vocabularies", "licenses"])


def license_url(base_url: str, license_id: str) -> str:
    return join_url(
        base_url,
        segments=[
            "api",
            "vocabularies",
            "licenses",
            quote_path_segment(license_id, field_name="id"),
        ],
    )


def bucket_file_url(bucket_url: str, filename: str) -> str:
    if not bucket_url or not bucket_url.strip():
        raise ValidationError("bucket URL must be non-empty")
    filename = quote_path_segment(filename, field_name="filename")
    return f"{bucket_url.strip().rstrip('/')}/{filename}"
