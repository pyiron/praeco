"""Stream HTTP response bodies to local files."""

from __future__ import annotations

import contextlib
import hashlib
import os
import uuid
from pathlib import Path

import requests

from praeco.exceptions import ValidationError


def write_response_to_path(
    response: requests.Response,
    path: str | Path,
    *,
    overwrite: bool = False,
    md5: str | None = None,
    size: int | None = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Stream a response body to `path`, verify it, and move it into place.

    The body is written in chunks to a temporary file next to the target. The
    temporary file replaces the target only after the optional size and MD5
    checks pass, so a failed download never leaves a partial target behind.
    The caller is responsible for checking the response status beforehand.

    Parameters
    ----------
    response
        Response opened with ``stream=True``. It is always closed.
    path
        Target file path. Missing parent directories are created.
    overwrite
        Replace an existing target instead of raising `FileExistsError`.
    md5
        Expected MD5 digest as bare lowercase hex, or None to skip the check.
    size
        Expected body size in bytes, or None to skip the check.
    chunk_size
        Number of bytes requested per `iter_content` chunk.

    Returns
    -------
    path
        The target path as given.

    Raises
    ------
    FileExistsError
        If the target exists and `overwrite` is False.
    ValidationError
        If the written size or MD5 digest differs from the expected value.
    """
    target = Path(path)
    try:
        if not overwrite and target.exists():
            raise FileExistsError(f"target file already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        try:
            digest = hashlib.md5(usedforsecurity=False)
            written = 0
            with temporary.open("xb") as file:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    file.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
            if size is not None and written != size:
                raise ValidationError(
                    f"size mismatch for {target}: expected {size} bytes, "
                    f"received {written}"
                )
            if md5 is not None and digest.hexdigest() != md5.lower():
                raise ValidationError(
                    f"MD5 mismatch for {target}: expected {md5.lower()}, "
                    f"received {digest.hexdigest()}"
                )
            os.replace(temporary, target)
        except BaseException:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise
    finally:
        response.close()
    return target
