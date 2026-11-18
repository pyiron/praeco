# request/response handling

from typing import Any

import requests

from praeco.exceptions import HttpError

ERROR_TEXT_LIMIT = 200


def shorten_error_text(text: str, *, limit: int = ERROR_TEXT_LIMIT) -> str:
    """
    Shorten a response body for use in an exception message.

    Whitespace runs, such as the line breaks and indentation of an HTML error
    page, are collapsed to single spaces. Text that is still longer than
    `limit` is cut, and a note gives the length of the full body, which stays
    available as `HttpError.response_text`.

    Parameters
    ----------
    text
        Response body.
    limit
        Maximum number of characters kept from the body.

    Returns
    -------
    message
        The collapsed body, shortened if necessary.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    excerpt = collapsed[:limit].rstrip()
    return f"{excerpt}... ({len(text)} characters; see response_text)"


def raise_for_status(resp: requests.Response) -> None:
    """
    Raise `HttpError` if the response indicates an HTTP error.

    Only an error response's body is read, so a successful streamed response
    can be checked before its body is consumed.

    Parameters
    ----------
    resp
        Response object.

    Raises
    ------
    HttpError
        If status code is 4xx/5xx. Includes response text where available.
    """
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        text = getattr(resp, "text", None)
        raise HttpError(
            method=(resp.request.method or "HTTP") if resp.request else "HTTP",
            url=resp.url,
            status_code=resp.status_code,
            message=str(e),
            response_text=text,
        ) from e


def read_json(resp: requests.Response) -> Any:
    """
    Decode JSON response after checking status.

    Parameters
    ----------
    resp
        Response object.

    Returns
    -------
    payload
        Parsed JSON payload.

    Raises
    ------
    HttpError
        If status indicates error or JSON decoding fails.
    """
    raise_for_status(resp)
    try:
        return resp.json()
    except ValueError as e:
        raise HttpError(
            method=(resp.request.method or "HTTP") if resp.request else "HTTP",
            url=resp.url,
            status_code=resp.status_code,
            message="Failed to decode JSON response.",
            response_text=getattr(resp, "text", None),
        ) from e


def read_text(resp: requests.Response) -> str:
    """
    Decode text response after checking status.

    Parameters
    ----------
    resp
        Response object.

    Returns
    -------
    text
        Response body as text.

    Raises
    ------
    HttpError
        If status indicates error.
    """
    raise_for_status(resp)
    return resp.text
