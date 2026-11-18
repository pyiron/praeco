import json
import unittest
from typing import Any, cast

from praeco.services.ckan.exceptions import CkanApiError
from praeco.services.ckan.response import read_ckan_result
from praeco.transport.request import shorten_error_text

from ._helpers import FakeRequest, FakeResponse


class TestCkanResponse(unittest.TestCase):
    def test_successful_action_result_is_unwrapped(self):
        response = FakeResponse(
            json_value={"success": True, "result": {"name": "dataset"}}
        )

        result = read_ckan_result(cast(Any, response))

        self.assertEqual(result, {"name": "dataset"})

    def test_successful_none_result_is_preserved(self):
        response = FakeResponse(json_value={"success": True, "result": None})

        self.assertIsNone(read_ckan_result(cast(Any, response)))

    def test_invalid_json_is_wrapped(self):
        response = FakeResponse(json_exc=ValueError("invalid json"))

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(
            ctx.exception.message,
            "CKAN action response must be a JSON object.",
        )
        self.assertEqual(ctx.exception.method, "HTTP")

    def test_non_mapping_payload_is_rejected(self):
        response = FakeResponse(json_value=[{"success": True}])

        with self.assertRaisesRegex(CkanApiError, "JSON object"):
            read_ckan_result(cast(Any, response))

    def test_missing_success_is_rejected(self):
        response = FakeResponse(json_value={"result": {"name": "dataset"}})

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, "CKAN action failed.")

    def test_missing_result_is_rejected(self):
        response = FakeResponse(json_value={"success": True})

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(
            ctx.exception.message,
            "CKAN action response must include a result field.",
        )

    def test_failed_action_uses_structured_error_message(self):
        payload = {
            "success": False,
            "error": {"message": "Dataset not found", "__type": "Not Found Error"},
        }
        response = FakeResponse(
            text=json.dumps(payload),
            json_value=payload,
            request=FakeRequest("POST"),
        )

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Dataset not found")
        self.assertEqual(ctx.exception.method, "POST")
        self.assertEqual(ctx.exception.payload, payload)

    def test_failed_action_falls_back_to_error_type(self):
        response = FakeResponse(
            json_value={"success": False, "error": {"__type": "Validation Error"}}
        )

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Validation Error")

    def test_failed_action_uses_string_error(self):
        response = FakeResponse(
            json_value={"success": False, "error": "Dataset not found"}
        )

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Dataset not found")

    def test_failed_action_uses_top_level_message(self):
        response = FakeResponse(
            json_value={"success": False, "message": "Dataset not found"}
        )

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Dataset not found")

    def test_http_error_uses_response_text_when_payload_is_not_json(self):
        response = FakeResponse(
            status_code=500,
            text="Server unavailable",
            json_exc=ValueError("invalid json"),
            request=FakeRequest("GET"),
        )

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, "Server unavailable")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIsNone(ctx.exception.payload)

    def test_long_non_json_error_body_is_shortened_in_the_message(self):
        body = "<html>\n<body>\n" + "Bad gateway. " * 100 + "\n</body>\n</html>"
        response = FakeResponse(
            status_code=502,
            text=body,
            json_exc=ValueError("invalid json"),
            request=FakeRequest("GET"),
        )

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, shorten_error_text(body))
        self.assertLess(len(ctx.exception.message), len(body))
        self.assertEqual(
            ctx.exception.response_text,
            body,
            msg="the full body must stay available",
        )

    def test_http_error_without_payload_or_text_uses_default_message(self):
        response = FakeResponse(
            status_code=500,
            text=" ",
            json_exc=ValueError("invalid json"),
        )

        with self.assertRaises(CkanApiError) as ctx:
            read_ckan_result(cast(Any, response))

        self.assertEqual(ctx.exception.message, "CKAN API request failed.")


if __name__ == "__main__":
    unittest.main()
