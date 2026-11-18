"""CKAN action response handling."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

import requests

from praeco.services.ckan.exceptions import CkanApiError
from praeco.transport.request import shorten_error_text


def read_ckan_result(resp: requests.Response) -> Any:
    """Decode and unwrap a CKAN action response."""
    if resp.status_code >= 400:
        raise_ckan_error(resp)

    payload = _response_payload(resp)
    if not isinstance(payload, Mapping):
        raise CkanApiError(
            method=_response_method(resp),
            url=resp.url,
            status_code=resp.status_code,
            message="CKAN action response must be a JSON object.",
            response_text=getattr(resp, "text", None),
            payload=payload,
        )

    if payload.get("success") is not True:
        raise CkanApiError(
            method=_response_method(resp),
            url=resp.url,
            status_code=resp.status_code,
            message=_error_message(payload, resp),
            response_text=getattr(resp, "text", None),
            payload=dict(payload),
        )

    if "result" not in payload:
        raise CkanApiError(
            method=_response_method(resp),
            url=resp.url,
            status_code=resp.status_code,
            message="CKAN action response must include a result field.",
            response_text=getattr(resp, "text", None),
            payload=dict(payload),
        )

    return payload["result"]


def raise_ckan_error(resp: requests.Response) -> NoReturn:
    """Raise an exception that preserves CKAN's structured error payload."""
    payload = _response_payload(resp)
    raise CkanApiError(
        method=_response_method(resp),
        url=resp.url,
        status_code=resp.status_code,
        message=_error_message(payload, resp),
        response_text=getattr(resp, "text", None),
        payload=payload,
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
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("__type")
            if isinstance(message, str) and message.strip():
                return message.strip()
        elif isinstance(error, str) and error.strip():
            return error.strip()

        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

        if payload.get("success") is not True:
            return "CKAN action failed."

    text = getattr(resp, "text", None)
    if isinstance(text, str) and text.strip():
        return shorten_error_text(text)
    return "CKAN API request failed."
