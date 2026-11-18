import json
import unittest
from typing import Any, cast

from praeco.services.zenodo import (
    ZenodoApiError,
    ZenodoAuthenticationError,
    ZenodoNotFoundError,
    ZenodoPermissionError,
    ZenodoValidationError,
)
from praeco.services.zenodo._response import read_zenodo_json, read_zenodo_text
from praeco.transport.request import shorten_error_text

from ._helpers import FakeRequest, FakeResponse


class TestZenodoResponse(unittest.TestCase):
    def test_invalid_success_json_is_wrapped(self):
        response = FakeResponse(status_code=200, json_exc=ValueError("invalid json"))

        with self.assertRaises(ZenodoApiError) as ctx:
            read_zenodo_json(cast(Any, response))

        self.assertEqual(
            ctx.exception.message, "Failed to decode Zenodo JSON response."
        )
        self.assertEqual(ctx.exception.method, "HTTP")

    def test_text_response_is_returned(self):
        response = FakeResponse(status_code=204, text="deleted")

        self.assertEqual(read_zenodo_text(cast(Any, response)), "deleted")

    def test_structured_validation_error_is_preserved(self):
        response = FakeResponse(
            status_code=400,
            text=json.dumps(
                {
                    "message": "Validation error",
                    "status": 400,
                    "errors": [
                        {
                            "field": "metadata.creators.0.name",
                            "message": "Name is required.",
                        }
                    ],
                }
            ),
            json_value={
                "message": "Validation error",
                "status": 400,
                "errors": [
                    {
                        "field": "metadata.creators.0.name",
                        "message": "Name is required.",
                    }
                ],
            },
            request=FakeRequest("PUT"),
        )

        with self.assertRaises(ZenodoValidationError) as ctx:
            read_zenodo_json(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Validation error")
        assert ctx.exception.errors is not None
        self.assertEqual(ctx.exception.errors[0].field, "metadata.creators.0.name")

    def test_validation_error_skips_malformed_field_errors(self):
        response = FakeResponse(
            status_code=400,
            json_value={
                "message": "Validation error",
                "errors": [
                    "not a dict",
                    {"field": "ignored"},
                    {"field": " ", "message": " Missing field. "},
                ],
            },
            request=FakeRequest("POST"),
        )

        with self.assertRaises(ZenodoValidationError) as ctx:
            read_zenodo_json(cast(Any, response))

        assert ctx.exception.errors is not None
        self.assertEqual(len(ctx.exception.errors), 1)
        self.assertIsNone(ctx.exception.errors[0].field)
        self.assertEqual(ctx.exception.errors[0].message, "Missing field.")

    def test_status_codes_map_to_specific_exceptions(self):
        cases = [
            (401, ZenodoAuthenticationError),
            (403, ZenodoPermissionError),
            (404, ZenodoNotFoundError),
            (500, ZenodoApiError),
        ]

        for status_code, expected in cases:
            with self.subTest(status_code=status_code):
                response = FakeResponse(
                    status_code=status_code,
                    json_value={"message": " Request failed. ", "errors": "ignored"},
                    request=FakeRequest("GET"),
                )

                with self.assertRaises(expected) as ctx:
                    read_zenodo_json(cast(Any, response))

                self.assertEqual(ctx.exception.message, "Request failed.")
                self.assertIsNone(ctx.exception.errors)

    def test_non_json_error_uses_text_message(self):
        response = FakeResponse(
            status_code=500,
            text="Server unavailable",
            json_exc=ValueError("invalid json"),
        )

        with self.assertRaises(ZenodoApiError) as ctx:
            read_zenodo_text(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Server unavailable")
        self.assertIsNone(ctx.exception.payload)

    def test_long_non_json_error_body_is_shortened_in_the_message(self):
        body = "<html>\n<body>\n" + "Bad gateway. " * 100 + "\n</body>\n</html>"
        response = FakeResponse(
            status_code=502,
            text=body,
            json_exc=ValueError("invalid json"),
        )

        with self.assertRaises(ZenodoApiError) as ctx:
            read_zenodo_json(cast(Any, response))

        self.assertEqual(ctx.exception.message, shorten_error_text(body))
        self.assertLess(len(ctx.exception.message), len(body))
        self.assertEqual(
            ctx.exception.response_text,
            body,
            msg="the full body must stay available",
        )

    def test_error_without_payload_or_text_uses_default_message(self):
        response = FakeResponse(
            status_code=500,
            text=" ",
            json_exc=ValueError("invalid json"),
        )

        with self.assertRaises(ZenodoApiError) as ctx:
            read_zenodo_json(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Zenodo API request failed.")


if __name__ == "__main__":
    unittest.main()
