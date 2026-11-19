"""Path handling shared by the Dataportal upload methods."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TypeAlias, TypeVar

from praeco.exceptions import ValidationError

UploadPath: TypeAlias = str | Path
# A str is itself a Sequence[str], so the overload for several paths names
# lists and tuples instead of Sequence: an argument typed `str | list[str]`
# then resolves to the union return type, not to a list. The type variable
# lets lists of subtypes, such as list[PosixPath], select the list overload
# despite list's invariance. Other sequences are accepted too and resolve to
# the union.
UploadPathT = TypeVar("UploadPathT", bound=UploadPath)
UploadPaths: TypeAlias = UploadPath | Sequence[UploadPath]


def normalize_upload_paths(paths: UploadPaths) -> list[Path]:
    """Return one path or a sequence of paths as a list of `Path` objects."""
    if isinstance(paths, (str, Path)):
        return [Path(paths)]
    return [Path(path) for path in paths]


def check_upload_files(paths: Sequence[Path]) -> None:
    """Raise `ValidationError` for the first path that is not a file."""
    for path in paths:
        if not path.is_file():
            raise ValidationError(f"upload path must be a file: {path}")


def default_asset_name(path: Path) -> str:
    """Return the file name an asset gets without an explicit name."""
    name = path.name.strip()
    if not name:
        raise ValidationError("upload filename must be non-empty")
    return name
