import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd
import rdflib
import requests

from praeco.exceptions import HttpError, ValidationError
from praeco.services.ontodocker import OntodockerClient
from praeco.services.ontodocker.models import EndpointInfo


class _FakeRequest:
    def __init__(self, method: str):
        self.method = method


class _FakeResponse:
    def __init__(
        self,
        *,
        url: str = "https://example.test/api",
        status_code: int = 200,
        text: str = "ok",
        request: _FakeRequest | None = None,
        raise_for_status_exc: Exception | None = None,
        json_value=None,
        json_exc: Exception | None = None,
        content: bytes | None = None,
    ):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.request = request
        self._raise_for_status_exc = raise_for_status_exc
        self._json_value = json_value
        self._json_exc = json_exc
        self.content = text.encode("utf-8") if content is None else content
        self.closed = False

    def iter_content(self, chunk_size: int = 1):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self._raise_for_status_exc is not None:
            raise self._raise_for_status_exc
        return None

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_value


class _FakeSession:
    def __init__(self):
        self.headers: dict[str, str] = {}
        self.calls: list[dict] = []
        self.response: _FakeResponse = _FakeResponse()

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class TestOntodockerClientInit(unittest.TestCase):
    def test_resources_are_initialized(self):
        s = _FakeSession()
        c = OntodockerClient("example.org", session=s)

        self.assertIs(c.endpoints.client, c)
        self.assertIs(c.datasets.client, c)
        self.assertIs(c.sparql.client, c)


class TestEndpointsResource(unittest.TestCase):
    def test_list_raw_uses_endpoints_api_and_rectifies_legacy(self):
        s = _FakeSession()
        s.response = _FakeResponse(
            text="['http://example.org:None/api/jena/ds/sparql']",
            request=_FakeRequest("GET"),
        )
        c = OntodockerClient("https://example.org", session=s)

        out = c.endpoints.list_raw()

        self.assertEqual(out, ["https://example.org/api/v1/jena/ds/sparql"])
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(s.calls[0]["method"], "GET")
        self.assertEqual(s.calls[0]["url"], "https://example.org/api/v1/endpoints")

    def test_list_parses_dataset_names(self):
        s = _FakeSession()
        s.response = _FakeResponse(
            text=(
                "['https://example.org/api/v1/jena/a/sparql',"
                " 'https://example.org/api/v1/jena/b/sparql']"
            ),
            request=_FakeRequest("GET"),
        )
        c = OntodockerClient("https://example.org", session=s)

        out = c.endpoints.list()

        self.assertEqual(
            out,
            [
                EndpointInfo(
                    dataset="a",
                    sparql_endpoint="https://example.org/api/v1/jena/a/sparql",
                ),
                EndpointInfo(
                    dataset="b",
                    sparql_endpoint="https://example.org/api/v1/jena/b/sparql",
                ),
            ],
        )


class TestDatasetsResource(unittest.TestCase):
    def test_list_returns_unique_sorted_datasets(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        c.endpoints.list = mock.Mock(
            return_value=[
                EndpointInfo(dataset="b", sparql_endpoint="x"),
                EndpointInfo(dataset="a", sparql_endpoint="y"),
                EndpointInfo(dataset="b", sparql_endpoint="z"),
            ]
        )

        self.assertEqual(c.datasets.list(), ["a", "b"])

    def test_create_validates_name(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)
        with self.assertRaises(ValidationError):
            _ = c.datasets.create("")
        with self.assertRaises(ValidationError):
            _ = c.datasets.create("   ")

    def test_create_uses_put(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="created", request=_FakeRequest("PUT"))
        c = OntodockerClient("https://example.org", session=s)

        out = c.datasets.create(" ds ")

        self.assertEqual(out, "created")
        self.assertEqual(s.calls[0]["method"], "PUT")
        self.assertEqual(s.calls[0]["url"], "https://example.org/api/v1/jena/ds")

    def test_delete_validates_name(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)
        with self.assertRaises(ValidationError):
            _ = c.datasets.delete("")
        with self.assertRaises(ValidationError):
            _ = c.datasets.delete("   ")

    def test_delete_uses_delete(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="deleted", request=_FakeRequest("DELETE"))
        c = OntodockerClient("https://example.org", session=s)

        out = c.datasets.delete(" ds ")

        self.assertEqual(out, "deleted")
        self.assertEqual(s.calls[0]["method"], "DELETE")
        self.assertEqual(s.calls[0]["url"], "https://example.org/api/v1/jena/ds")

    def test_fetch_turtle_validates_name(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with self.assertRaises(ValidationError):
            _ = c.datasets.fetch_turtle("")

    def test_fetch_turtle_uses_get(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="@prefix : <x> .", request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        out = c.datasets.fetch_turtle(" ds ")

        self.assertEqual(out, "@prefix : <x> .")
        self.assertEqual(s.calls[0]["method"], "GET")
        self.assertEqual(s.calls[0]["url"], "https://example.org/api/v1/jena/ds")

    def test_download_turtle_validates_name_and_filename(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with self.assertRaisesRegex(ValidationError, "dataset name must be non-empty"):
            _ = c.datasets.download_turtle("", Path("out.ttl"))
        with self.assertRaisesRegex(
            ValidationError, "filename must be a non-empty path"
        ):
            _ = c.datasets.download_turtle("ds", "   ")

    def test_download_turtle_writes_file_when_requested(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="@prefix : <x> .", request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.ttl"
            out = c.datasets.download_turtle("ds", path)

            self.assertEqual(out, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "@prefix : <x> .")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["out.ttl"])
        self.assertEqual(s.calls[0]["method"], "GET")
        self.assertEqual(s.calls[0]["url"], "https://example.org/api/v1/jena/ds")
        self.assertTrue(s.calls[0]["stream"], msg="the body must be streamed")
        self.assertTrue(s.response.closed)

    def test_download_turtle_accepts_str_filename(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="@prefix : <x> .", request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            out = c.datasets.download_turtle("ds", str(Path(tmp) / "out.ttl"))

            self.assertEqual(out, Path(tmp) / "out.ttl")
            self.assertTrue(out.is_file())

    def test_download_turtle_writes_response_bytes_unchanged(self):
        # Not valid UTF-8: decoding and re-encoding the text would change it.
        body = b"@prefix : <x> .\r\n# caf\xe9\r\n"
        s = _FakeSession()
        s.response = _FakeResponse(content=body, request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            path = c.datasets.download_turtle("ds", Path(tmp) / "out.ttl")

            self.assertEqual(path.read_bytes(), body)

    def test_download_turtle_creates_missing_parent_directories(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="@prefix : <x> .", request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b" / "out.ttl"
            out = c.datasets.download_turtle("ds", path)

            self.assertEqual(out, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "@prefix : <x> .")

    def test_download_turtle_existing_file_raises_before_the_request(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.ttl"
            path.write_text("old", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                _ = c.datasets.download_turtle("ds", path)

            self.assertEqual(path.read_text(encoding="utf-8"), "old")
        self.assertEqual(s.calls, [])

    def test_download_turtle_overwrite_replaces_existing_file(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="new", request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.ttl"
            path.write_text("old", encoding="utf-8")

            out = c.datasets.download_turtle("ds", path, overwrite=True)

            self.assertEqual(out, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "new")

    def test_download_turtle_blocked_target_raises_before_the_request(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            directory = Path(tmp) / "dir.ttl"
            directory.mkdir()
            file = Path(tmp) / "file"
            file.write_text("keep", encoding="utf-8")
            targets = {
                "target is a directory": directory,
                "parent is a file": file / "out.ttl",
                "ancestor is a file": file / "sub" / "out.ttl",
            }
            for label, target in targets.items():
                for overwrite in (False, True):
                    with (
                        self.subTest(case=label, overwrite=overwrite),
                        self.assertRaisesRegex(
                            FileExistsError, "local path blocks target file"
                        ),
                    ):
                        _ = c.datasets.download_turtle(
                            "ds", target, overwrite=overwrite
                        )

            self.assertTrue(directory.is_dir())
            self.assertEqual(file.read_text(encoding="utf-8"), "keep")
        self.assertEqual(s.calls, [])

    def test_download_turtle_http_error_leaves_no_file_and_closes_response(self):
        s = _FakeSession()
        s.response = _FakeResponse(
            status_code=404,
            text="Not Found",
            request=_FakeRequest("GET"),
            raise_for_status_exc=requests.HTTPError("404 Client Error"),
        )
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            with self.assertRaises(HttpError) as caught:
                _ = c.datasets.download_turtle("ds", Path(tmp) / "out.ttl")

            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(caught.exception.status_code, 404)
        self.assertTrue(s.response.closed)

    def test_upload_turtlefile_validates_inputs(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with self.assertRaisesRegex(ValidationError, "dataset name must be non-empty"):
            _ = c.datasets.upload_turtlefile("", "x.ttl")

        with self.assertRaisesRegex(
            ValidationError, "turtlefile must be a non-empty path"
        ):
            _ = c.datasets.upload_turtlefile("ds", "")

    def test_upload_turtlefile_missing_file_raises_file_not_found(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.ttl"

            with self.assertRaises(FileNotFoundError):
                _ = c.datasets.upload_turtlefile("ds", str(missing))

    def test_upload_turtlefile_uses_post_with_file_field_for_str_and_path(self):
        with TemporaryDirectory() as tmp:
            turtlefile = Path(tmp) / "in.ttl"
            turtlefile.write_text("@prefix : <x> .", encoding="utf-8")

            cases = (
                ("str", str(turtlefile)),
                ("padded str", f" {turtlefile} "),
                ("Path", turtlefile),
            )

            for label, value in cases:
                s = _FakeSession()
                s.response = _FakeResponse(text="ok", request=_FakeRequest("POST"))
                c = OntodockerClient("https://example.org", session=s)

                with self.subTest(path_type=label):
                    out = c.datasets.upload_turtlefile("ds", value)

                    self.assertEqual(out, "ok")
                    self.assertEqual(s.calls[0]["method"], "POST")
                    self.assertEqual(
                        s.calls[0]["url"], "https://example.org/api/v1/jena/ds"
                    )
                    self.assertIn("file", s.calls[0]["files"])

    def test_upload_graph_validates_name(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        graph = rdflib.Graph()

        with self.assertRaises(ValidationError):
            _ = c.datasets.upload_graph("", graph)

    def test_upload_graph_validates_graph_type(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with self.assertRaisesRegex(ValidationError, "rdflib.Graph instance"):
            _ = c.datasets.upload_graph("ds", object())

    def test_upload_graph_propagates_serialize_errors(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        class _FakeGraph(rdflib.Graph):
            def serialize(self, *, format: str):
                raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            _ = c.datasets.upload_graph("ds", _FakeGraph())

    def test_upload_graph_serializes_bytes_and_posts(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="ok", request=_FakeRequest("POST"))
        c = OntodockerClient("https://example.org", session=s)

        class _FakeGraph(rdflib.Graph):
            def serialize(self, *, format: str):
                self.format = format
                return b"@prefix : <x> ."

        out = c.datasets.upload_graph("ds", _FakeGraph())

        self.assertEqual(out, "ok")
        self.assertEqual(s.calls[0]["method"], "POST")
        self.assertEqual(s.calls[0]["url"], "https://example.org/api/v1/jena/ds")
        posted = s.calls[0]["files"]["file"]
        self.assertEqual(posted[0], "graph.ttl")
        self.assertEqual(posted[2], "text/turtle")

    def test_upload_graph_serializes_text_and_posts(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="ok", request=_FakeRequest("POST"))
        c = OntodockerClient("https://example.org", session=s)

        class _FakeGraph(rdflib.Graph):
            def serialize(self, *, format: str):
                self.format = format
                return "@prefix : <x> ."

        out = c.datasets.upload_graph("ds", _FakeGraph())

        self.assertEqual(out, "ok")

        self.assertEqual(s.calls[0]["method"], "POST")
        self.assertEqual(s.calls[0]["url"], "https://example.org/api/v1/jena/ds")
        posted = s.calls[0]["files"]["file"]
        self.assertEqual(posted[0], "graph.ttl")
        self.assertEqual(posted[2], "text/turtle")


class TestSparqlResource(unittest.TestCase):
    def test_endpoint_validates_dataset(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)
        with self.assertRaisesRegex(ValidationError, "dataset must be non-empty"):
            _ = c.sparql.endpoint("")

    def test_endpoint_builds_url(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)
        self.assertEqual(
            c.sparql.endpoint(" ds "),
            "https://example.org/api/v1/jena/ds/sparql",
        )

    def test_query_raw_validates_dataset_and_query(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with self.assertRaisesRegex(ValidationError, "dataset must be non-empty"):
            _ = c.sparql.query_raw("", "SELECT * WHERE {}")

        with self.assertRaisesRegex(ValidationError, "query must be non-empty"):
            _ = c.sparql.query_raw("ds", "")

    def test_query_raw_uses_get_with_query_param_and_accept_header(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="{}", request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        out = c.sparql.query_raw("ds", "SELECT * WHERE { ?s ?p ?o }")

        self.assertEqual(out, "{}")
        self.assertEqual(s.calls[0]["method"], "GET")
        self.assertEqual(
            s.calls[0]["url"],
            "https://example.org/api/v1/jena/ds/sparql",
        )
        self.assertEqual(
            s.calls[0]["params"],
            {"query": "SELECT * WHERE { ?s ?p ?o }"},
        )
        self.assertEqual(
            s.calls[0]["headers"],
            {"Accept": "application/sparql-results+json"},
        )

    def test_query_df_validates_query_and_columns(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with self.assertRaisesRegex(ValidationError, "dataset must be non-empty"):
            _ = c.sparql.query_df("", "SELECT ?a WHERE {}", columns=["a"])

        with self.assertRaisesRegex(ValidationError, "query must be non-empty"):
            _ = c.sparql.query_df("ds", "", columns=["a"])

        with self.assertRaisesRegex(
            ValidationError, "columns must be a non-empty list of strings"
        ):
            _ = c.sparql.query_df("ds", "SELECT ?a WHERE {}", columns=[])

        with self.assertRaisesRegex(
            ValidationError, "columns must be a non-empty list of strings"
        ):
            _ = c.sparql.query_df("ds", "SELECT ?a WHERE {}", columns=["a", " "])

        with self.assertRaisesRegex(
            ValidationError, "columns must be a non-empty list of strings"
        ):
            _ = c.sparql.query_df("ds", "SELECT ?a WHERE {}", columns=["a", 1])

        with self.assertRaisesRegex(
            ValidationError, "columns must be a non-empty list of strings"
        ):
            _ = c.sparql.query_df("ds", "SELECT ?a WHERE {}", columns=("a",))

    def test_query_df_raises_json_decode_error_on_invalid_json(self):
        s = _FakeSession()
        s.response = _FakeResponse(text="not json", request=_FakeRequest("GET"))
        c = OntodockerClient("https://example.org", session=s)

        with self.assertRaises(json.JSONDecodeError):
            _ = c.sparql.query_df("ds", "SELECT ?a WHERE {}", columns=["a"])

    def test_query_df_delegates_to_query_raw_with_accept_header(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with mock.patch.object(
            c.sparql,
            "query_raw",
            return_value='{"results": {"bindings": [{"a": {"value": "1"}}]}}',
        ) as query_raw:
            df = c.sparql.query_df(" ds ", "SELECT ?a WHERE {}", columns=["a"])

        query_raw.assert_called_once_with(
            " ds ",
            "SELECT ?a WHERE {}",
            accept="application/sparql-results+json",
        )
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(list(df.columns), ["a"])
        self.assertEqual(df.iloc[0].tolist(), ["1"])

    def test_query_df_does_not_call_query_raw_when_columns_invalid(self):
        s = _FakeSession()
        c = OntodockerClient("https://example.org", session=s)

        with (
            mock.patch.object(c.sparql, "query_raw") as query_raw,
            self.assertRaises(ValidationError),
        ):
            _ = c.sparql.query_df("ds", "SELECT ?a WHERE {}", columns=("a",))

        query_raw.assert_not_called()

    def test_query_df_strips_dataset_and_maps_missing_bindings_to_none(self):
        s = _FakeSession()
        s.response = _FakeResponse(
            text=(
                '{"results": {"bindings": ['
                '{"a": {"value": "1"}}, '
                '{"b": {"value": "2"}}'
                "]}}"
            ),
            request=_FakeRequest("GET"),
        )
        c = OntodockerClient("https://example.org", session=s)

        df = c.sparql.query_df(" ds ", "SELECT ?a ?b WHERE {}", columns=["a", "b"])

        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(list(df.columns), ["a", "b"])
        self.assertEqual(df.iloc[0]["a"], "1")
        self.assertTrue(
            pd.isna(df.iloc[0]["b"]),
            msg="missing SPARQL bindings should map to None/NaN in the dataframe",
        )
        self.assertTrue(pd.isna(df.iloc[1]["a"]))
        self.assertEqual(df.iloc[1]["b"], "2")
        self.assertEqual(
            s.calls[0]["url"],
            "https://example.org/api/v1/jena/ds/sparql",
        )

    def test_query_df_uses_get_with_query_param_and_accept_header(self):
        s = _FakeSession()
        s.response = _FakeResponse(
            text=(
                '{"results": {"bindings": '
                '[{"a": {"value": "1"}, "b": {"value": "2"}}]}}'
            ),
            request=_FakeRequest("GET"),
        )
        c = OntodockerClient("https://example.org", token="abc", session=s)

        df = c.sparql.query_df("ds", "SELECT ?a ?b WHERE {}", columns=["a", "b"])

        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(list(df.columns), ["a", "b"])
        self.assertEqual(df.iloc[0].tolist(), ["1", "2"])
        self.assertEqual(s.calls[0]["method"], "GET")
        self.assertEqual(
            s.calls[0]["url"],
            "https://example.org/api/v1/jena/ds/sparql",
        )
        self.assertEqual(
            s.calls[0]["params"],
            {"query": "SELECT ?a ?b WHERE {}"},
        )
        self.assertEqual(
            s.calls[0]["headers"],
            {"Accept": "application/sparql-results+json"},
        )
        # token is handled by HttpClient via session headers, not per-request
        self.assertEqual(
            s.headers.get("Authorization"),
            "Bearer abc",
            msg="token-based auth should be stored on session headers for SPARQL requests",
        )


if __name__ == "__main__":
    unittest.main()
