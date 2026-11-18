"""Zenodo-aware response handling."""

from __future__ import annotations

from typing import Any, NoReturn

import requests

from praeco.services.zenodo.exceptions import (
    ZenodoApiError,
    ZenodoAuthenticationError,
    ZenodoNotFoundError,
    ZenodoPermissionError,
    ZenodoValidationError,
)
from praeco.services.zenodo.models import ZenodoFieldError
from praeco.transport.request import shorten_error_text


def read_zenodo_json(resp: requests.Response) -> Any:
    """Decode a Zenodo JSON response or raise a Zenodo-specific error."""
    if resp.status_code >= 400:
        raise_zenodo_error(resp)

    try:
        return resp.json()
    except ValueError as exc:
        raise ZenodoApiError(
            method=_response_method(resp),
            url=resp.url,
            status_code=resp.status_code,
            message="Failed to decode Zenodo JSON response.",
            response_text=getattr(resp, "text", None),
        ) from exc


def read_zenodo_text(resp: requests.Response) -> str:
    """Decode a Zenodo text response or raise a Zenodo-specific error."""
    if resp.status_code >= 400:
        raise_zenodo_error(resp)
    return resp.text


def raise_zenodo_error(resp: requests.Response) -> NoReturn:
    """Raise an exception that preserves Zenodo's structured error payload."""
    payload = _response_payload(resp)
    message = _error_message(payload, resp)
    errors = _field_errors(payload)
    error_cls = _error_class(resp.status_code, errors)

    raise error_cls(
        method=_response_method(resp),
        url=resp.url,
        status_code=resp.status_code,
        message=message,
        response_text=getattr(resp, "text", None),
        payload=payload,
        errors=errors or None,
    )


def _response_method(resp: requests.Response) -> str:
    request = getattr(resp, "request", None)
    method = getattr(request, "method", None)
    return method or "HTTP"


def _response_payload(resp: requests.Response) -> Any | None:
    try:
        return resp.json()
    except ValueError:
        return None


def _error_message(payload: Any | None, resp: requests.Response) -> str:
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    text = getattr(resp, "text", None)
    if isinstance(text, str) and text.strip():
        return shorten_error_text(text)
    return "Zenodo API request failed."


def _field_errors(payload: Any | None) -> list[ZenodoFieldError]:
    if not isinstance(payload, dict):
        return []

    raw_errors = payload.get("errors")
    if not isinstance(raw_errors, list):
        return []

    out: list[ZenodoFieldError] = []
    for item in raw_errors:
        if not isinstance(item, dict):
            continue
        message = item.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        field = item.get("field")
        out.append(
            ZenodoFieldError(
                field=field if isinstance(field, str) and field.strip() else None,
                message=message.strip(),
            )
        )
    return out


def _error_class(
    status_code: int,
    errors: list[ZenodoFieldError],
) -> type[ZenodoApiError]:
    if status_code == 400 and errors:
        return ZenodoValidationError
    if status_code == 401:
        return ZenodoAuthenticationError
    if status_code == 403:
        return ZenodoPermissionError
    if status_code == 404:
        return ZenodoNotFoundError
    return ZenodoApiError
