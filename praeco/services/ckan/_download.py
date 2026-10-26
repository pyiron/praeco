"""Private helpers for downloading CKAN resource content."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

import requests

from praeco.exceptions import ValidationError
from praeco.services.ckan.models import CkanResourceInfo
from praeco.services.ckan.response import raise_ckan_error

if TYPE_CHECKING:
    from praeco.services.ckan.client import CkanClient

_DEFAULT_PORTS = {"http": 80, "https": 443}
_UNSAFE_CHARACTERS = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')
_UNSAFE_URL_CHARACTERS = re.compile(r"[\\\x00-\x1f\x7f]")
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{digit}" for digit in range(1, 10)]
    + [f"LPT{digit}" for digit in range(1, 10)]
)
_MAX_NAME_BYTES = 255
_DECIMAL_DIGITS = re.compile(r"[0-9]+")


def content_url(resource: CkanResourceInfo) -> str:
    """Return the resource's content URL if it is an absolute HTTP(S) URL.

    The URL must not contain a backslash or control characters, and as
    `requests` prepares it, it needs an HTTP(S) scheme, a host and a valid
    port; otherwise `ValidationError` is raised. The URL is returned as given.
    """
    url = resource.url
    if url is None:
        raise ValidationError(f"resource {resource.id!r} has no content URL")
    if _UNSAFE_URL_CHARACTERS.search(url):
        raise ValidationError(
            f"resource {resource.id!r} content URL must not contain a backslash "
            f"or control characters: {url!r}"
        )
    if _origin(url) is None:
        raise ValidationError(
            f"resource {resource.id!r} content URL must be an absolute HTTP(S) "
            f"URL: {url!r}"
        )
    return url


def sends_token(url: str, base_url: str) -> bool:
    """Return whether `url` has the same origin as `base_url`.

    Both origins are taken from the URLs as `requests` prepares them, which is
    what it connects to. Scheme and host are compared lower-case, and a
    missing port means the scheme's default port. A URL whose origin cannot
    be determined never matches.
    """
    url_origin = _origin(url)
    return url_origin is not None and url_origin == _origin(base_url)


def _origin(url: str) -> tuple[str, str, int] | None:
    """Return the scheme, host and port of `url` as `requests` prepares it.

    `urlsplit` alone can disagree with the host `requests` connects to, for
    example on a backslash before an ``@``. The netloc of the prepared URL is
    rebuilt from urllib3's own components, so both agree on it. None means
    the origin cannot be determined.
    """
    prepared = requests.PreparedRequest()
    try:
        prepared.prepare_url(url, None)
        # A successful prepare_url always sets url; "" only satisfies typing.
        parts = urlsplit(prepared.url or "")
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except (requests.exceptions.RequestException, ValueError):
        return None
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    return scheme, host.lower(), _DEFAULT_PORTS[scheme] if port is None else port


def is_safe_file_name(name: str) -> bool:
    """Return whether `name` is a single portable path component.

    Rejected are empty names, ``.`` and ``..``, the characters
    ``/ \\ : * ? " < > |`` and control characters, a trailing dot or space,
    Windows reserved device names (case-insensitive, before the first dot),
    and names longer than 255 bytes in UTF-8 or not encodable in UTF-8.
    """
    if name in {"", ".", ".."}:
        return False
    if _UNSAFE_CHARACTERS.search(name) or name.endswith((".", " ")):
        return False
    if name.split(".", 1)[0].upper() in _RESERVED_NAMES:
        return False
    try:
        encoded = name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= _MAX_NAME_BYTES


def check_file_name(name: str) -> str:
    """Return `name` unchanged, or raise `ValidationError` if it is unsafe."""
    if not is_safe_file_name(name):
        raise ValidationError(f"filename must be a safe single file name: {name!r}")
    return name


def default_file_name(resource: CkanResourceInfo, url: str) -> str:
    """Return the local file name for a resource downloaded from `url`.

    This is the percent-decoded last segment of the URL path, or the resource
    id if that segment is empty or unsafe. `ValidationError` is raised if the
    id is unsafe too.
    """
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    if is_safe_file_name(name):
        return name
    if is_safe_file_name(resource.id):
        return resource.id
    raise ValidationError(
        f"resource {resource.id!r} has no safe local file name; download it "
        f"with download(..., filename=...)"
    )


def check_unique_names(
    resources: Sequence[CkanResourceInfo], names: Sequence[str]
) -> None:
    """Raise `ValidationError` if several resources map to the same name."""
    ids_by_name: dict[str, list[str]] = {}
    for resource, name in zip(resources, names, strict=True):
        ids_by_name.setdefault(name, []).append(resource.id)
    duplicates = {name: ids for name, ids in ids_by_name.items() if len(ids) > 1}
    if duplicates:
        raise ValidationError(
            f"resources map to the same local file names: {duplicates}"
        )


def safe_target_path(directory: str | Path, name: str) -> Path:
    """Return ``Path(directory) / name`` if it resolves inside `directory`.

    A target that resolves outside `directory` or to `directory` itself, for
    example through a symlink at the target, raises `ValidationError`.
    """
    base = Path(directory)
    target = base / name
    # On Windows, resolve() returns a dangling symlink's stored target without
    # canonicalizing it; a second resolve() canonicalizes its existing prefix
    # (for example 8.3 short names) so both sides compare alike. On POSIX the
    # second call is a no-op.
    resolved_base = base.resolve().resolve()
    resolved_target = target.resolve().resolve()
    if resolved_target == resolved_base or not resolved_target.is_relative_to(
        resolved_base
    ):
        raise ValidationError(
            f"file name must name a path inside the directory: {name!r}"
        )
    return target


def check_local_conflicts(
    directory: str | Path,
    targets: Sequence[Path],
    *,
    overwrite: bool,
) -> None:
    """Reject local paths that would prevent writing the targets.

    `FileExistsError` is raised first for local paths that block a target
    regardless of `overwrite` (`directory` is not a directory, or a target is
    a directory), then for existing targets when `overwrite` is False.
    """
    base = Path(directory)
    blocking: list[Path] = []
    if os.path.lexists(base) and not base.is_dir():
        blocking.append(base)
    blocking.extend(target for target in targets if target.is_dir())
    if blocking:
        raise FileExistsError(
            f"local paths block target files: {[str(path) for path in blocking]}"
        )
    if not overwrite:
        existing = [target for target in targets if os.path.lexists(target)]
        if existing:
            raise FileExistsError(
                f"target files already exist: {[str(path) for path in existing]}"
            )


def expected_size(resource: CkanResourceInfo) -> int | None:
    """Return the size to verify for an uploaded resource, or None to skip.

    Only resources with ``url_type == "upload"`` are checked, and only if
    their ``size`` is a non-negative int (not a bool) or a string of ASCII
    decimal digits that `int` accepts (Python limits the number of digits).
    """
    if resource.raw.get("url_type") != "upload":
        return None
    size = resource.raw.get("size")
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        return size
    if isinstance(size, str) and _DECIMAL_DIGITS.fullmatch(size):
        try:
            return int(size)
        except ValueError:
            return None
    return None


def open_content(client: CkanClient, url: str) -> requests.Response:
    """Send a streamed GET for `url` and return the successful response.

    The session's ``Authorization`` header is sent only to the client's own
    origin; for other URLs it is dropped for this request. A status of 400 or
    higher raises `CkanApiError`, and the response is closed.
    """
    headers = None if sends_token(url, client.base_url) else {"Authorization": None}
    resp = client.session.request(
        method="GET",
        url=url,
        headers=headers,
        timeout=client.timeout,
        verify=client.verify,
        stream=True,
    )
    if resp.status_code >= 400:
        try:
            raise_ckan_error(resp)
        finally:
            resp.close()
    return resp
