"""Read-only access to Zenodo (InvenioRDM) record files."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from praeco.exceptions import ValidationError
from praeco.services.zenodo._response import raise_zenodo_error, read_zenodo_json
from praeco.services.zenodo._urls import record_draft_files_url, record_files_url
from praeco.services.zenodo.models import DepositionInfo
from praeco.transport.download import write_response_to_path

if TYPE_CHECKING:
    from praeco.services.zenodo.client import ZenodoClient

_RecordRef: TypeAlias = int | str | DepositionInfo
_FileNames: TypeAlias = list[str]
_DownloadedPaths: TypeAlias = list[Path]

_MD5_HEX = re.compile(r"[0-9a-fA-F]{32}")


@dataclass(frozen=True)
class _RecordFileEntry:
    """One downloadable file entry from a record's file listing."""

    key: str
    md5: str | None
    size: int | None
    content_url: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _RecordFileEntry:
        key = data.get("key")
        if not isinstance(key, str) or not key:
            raise ValidationError("Zenodo file entry must include a non-empty key")
        raw_links = data.get("links")
        links = cast(dict[str, Any], raw_links) if isinstance(raw_links, dict) else {}
        content_url = links.get("content")
        raw_size = data.get("size")
        return cls(
            key=key,
            md5=_parse_md5(data.get("checksum")),
            size=(
                raw_size
                if isinstance(raw_size, int)
                and not isinstance(raw_size, bool)
                and raw_size >= 0
                else None
            ),
            content_url=(
                content_url
                if isinstance(content_url, str) and content_url.strip()
                else None
            ),
        )


_Entries: TypeAlias = list[_RecordFileEntry]


@dataclass
class RecordFilesResource:
    """Files of published Zenodo records and of the caller's drafts."""

    client: ZenodoClient

    def list(self, record: _RecordRef, *, draft: bool = False) -> _FileNames:
        """List the keys of the downloadable files of a record.

        Set `draft` to list the files of the record's draft instead of the
        published record; this requires a token with access to the draft.
        """
        return [entry.key for entry in self._entries(record, draft=draft)]

    def download(
        self,
        record: _RecordRef,
        files: str | Sequence[str],
        *,
        directory: str | Path = ".",
        overwrite: bool = False,
        draft: bool = False,
    ) -> _DownloadedPaths:
        """Download selected files of a record into `directory`.

        Names must match the keys returned by `list`. Keys containing ``/``
        are written to subdirectories of `directory`. Returns the written
        paths in the order requested.
        """
        names = [files] if isinstance(files, str) else [*files]
        if not names:
            return []
        _check_unique(names)
        targets = _target_paths(directory, names, overwrite=overwrite)

        available = {entry.key: entry for entry in self._entries(record, draft=draft)}
        unknown = [name for name in names if name not in available]
        if unknown:
            raise ValidationError(f"record has no downloadable files named {unknown}")
        return self._download_entries(
            [available[name] for name in names], targets, overwrite=overwrite
        )

    def download_all(
        self,
        record: _RecordRef,
        *,
        directory: str | Path = ".",
        overwrite: bool = False,
        draft: bool = False,
    ) -> _DownloadedPaths:
        """Download every file listed by `list` into `directory`.

        Keys containing ``/`` are written to subdirectories of `directory`.
        Returns the written paths in the server's order.
        """
        entries = self._entries(record, draft=draft)
        names = [entry.key for entry in entries]
        _check_unique(names)
        targets = _target_paths(directory, names, overwrite=overwrite)
        return self._download_entries(entries, targets, overwrite=overwrite)

    def _entries(self, record: _RecordRef, *, draft: bool) -> _Entries:
        url_for = record_draft_files_url if draft else record_files_url
        url = url_for(self.client.base_url, _record_id(record))
        payload = read_zenodo_json(self.client.request("GET", url))
        if not isinstance(payload, dict):
            raise ValidationError("Zenodo record file listing must be an object")
        listing = cast(dict[str, Any], payload)
        if listing.get("enabled") is False:
            return []
        raw_entries = listing.get("entries")
        if raw_entries is None:
            return []
        if not isinstance(raw_entries, list):
            raise ValidationError("Zenodo record file entries must be a list")

        entries: _Entries = []
        for raw_item in cast(list[object], raw_entries):
            if not isinstance(raw_item, dict):
                raise ValidationError("Zenodo record file entry must be an object")
            item = cast(dict[str, Any], raw_item)
            status = item.get("status")
            if status is not None and status != "completed":
                continue
            entries.append(_RecordFileEntry.from_dict(item))
        return entries

    def _download_entries(
        self,
        entries: Sequence[_RecordFileEntry],
        targets: Sequence[Path],
        *,
        overwrite: bool,
    ) -> _DownloadedPaths:
        content_urls: _FileNames = []
        for entry in entries:
            if entry.content_url is None:
                raise ValidationError(
                    f"Zenodo file entry {entry.key!r} has no content link"
                )
            content_urls.append(entry.content_url)

        written: _DownloadedPaths = []
        for entry, target, url in zip(entries, targets, content_urls, strict=True):
            resp = self.client.request("GET", url, stream=True)
            if resp.status_code >= 400:
                try:
                    raise_zenodo_error(resp)
                finally:
                    resp.close()
            written.append(
                write_response_to_path(
                    resp,
                    target,
                    overwrite=overwrite,
                    md5=entry.md5,
                    size=entry.size,
                )
            )
        return written


@dataclass
class RecordsResource:
    """Zenodo (InvenioRDM) record operations."""

    client: ZenodoClient
    files: RecordFilesResource = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.files = RecordFilesResource(self.client)


def _record_id(record: _RecordRef) -> int | str:
    if isinstance(record, DepositionInfo):
        return record.id
    return record


def _parse_md5(checksum: object) -> str | None:
    """Return the bare lowercase MD5 hex of a checksum, or None to skip checks.

    Accepts ``"md5:<hex>"`` and bare 32-character hex. Other algorithms,
    malformed values, and missing checksums yield None.
    """
    if not isinstance(checksum, str):
        return None
    algorithm, separator, value = checksum.strip().partition(":")
    if not separator:
        algorithm, value = "md5", algorithm
    if algorithm.lower() != "md5" or not _MD5_HEX.fullmatch(value):
        return None
    return value.lower()


def _check_unique(names: Sequence[str]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        raise ValidationError(f"duplicate file names: {duplicates}")


def _target_paths(
    directory: str | Path,
    keys: Sequence[str],
    *,
    overwrite: bool,
) -> _DownloadedPaths:
    """Map keys to target paths, rejecting unsafe keys and existing targets.

    Every key is checked for safety before any target is checked for
    existence, so that an unsafe key is reported first.
    """
    targets = [_safe_target_path(directory, key) for key in keys]
    if not overwrite:
        existing = [target for target in targets if target.exists()]
        if existing:
            raise FileExistsError(
                f"target files already exist: {[str(path) for path in existing]}"
            )
    return targets


def _safe_target_path(directory: str | Path, key: str) -> Path:
    """Return ``Path(directory) / key`` if `key` stays inside `directory`."""
    if not key:
        raise ValidationError("file key must be non-empty")
    if PurePosixPath(key).is_absolute() or PureWindowsPath(key).anchor:
        raise ValidationError(f"file key must be relative: {key!r}")
    if ".." in re.split(r"[\\/]", key):
        raise ValidationError(f"file key must not contain '..': {key!r}")

    base = Path(directory)
    target = base / key
    resolved_base = base.resolve()
    resolved_target = target.resolve()
    if resolved_target == resolved_base or not resolved_target.is_relative_to(
        resolved_base
    ):
        raise ValidationError(
            f"file key must name a path inside the directory: {key!r}"
        )
    return target
