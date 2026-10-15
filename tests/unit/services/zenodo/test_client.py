import unittest
from typing import Any, cast

import praeco
from praeco.exceptions import InvalidAddressError
from praeco.services.zenodo import ZenodoClient

from ._helpers import FakeSession


class TestZenodoClientInit(unittest.TestCase):
    def test_is_exported_from_top_level_package(self):
        self.assertIs(praeco.ZenodoClient, ZenodoClient)

    def test_default_address_is_production_zenodo(self):
        c = ZenodoClient(session=cast(Any, FakeSession()))
        self.assertEqual(c.base_url, "https://zenodo.org")
        self.assertIs(c.depositions.client, c)
        self.assertIs(c.files.client, c)
        self.assertIs(c.licenses.client, c)
        self.assertIs(c.records.client, c)
        self.assertIs(c.records.files.client, c)

    def test_sandbox_address_is_used_when_requested(self):
        c = ZenodoClient(sandbox=True, session=cast(Any, FakeSession()))
        self.assertEqual(c.base_url, "https://sandbox.zenodo.org")

    def test_http_address_is_rejected(self):
        with self.assertRaises(InvalidAddressError):
            _ = ZenodoClient("http://zenodo.org", session=cast(Any, FakeSession()))

    def test_bearer_token_header_is_set(self):
        session = FakeSession()
        _ = ZenodoClient(token="abc", session=cast(Any, session))
        self.assertEqual(session.headers["Authorization"], "Bearer abc")


if __name__ == "__main__":
    unittest.main()
