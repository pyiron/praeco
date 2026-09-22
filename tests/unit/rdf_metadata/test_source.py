import hashlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from rdflib import BNode, Graph, Literal, URIRef

from praeco.exceptions import ValidationError
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest


class TestLocalSources(unittest.TestCase):
    def test_inputs_preserve_triples_and_exact_byte_audit(self):
        text = '<urn:dataset> <http://purl.org/dc/terms/title> " Café "@fr .\n'
        raw = text.encode()
        graph = Graph().parse(data=text, format="turtle")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.ttl"
            path.write_bytes(raw)
            for source, kind in (
                (text, "text"),
                (raw, "bytes"),
                (path, "path"),
                (graph, "graph"),
            ):
                with self.subTest(kind=kind):
                    result = harvest(source)
                    self.assertEqual(result.subjects[0].term, URIRef("urn:dataset"))
                    self.assertEqual(
                        result.subjects[0].labels, (Literal(" Café ", lang="fr"),)
                    )
                    info = result.source
                    self.assertEqual((info.kind, info.triple_count), (kind, 1))
                    digest = hashlib.sha256(raw).hexdigest()
                    if kind == "graph":
                        self.assertIsNone(info.serialization)
                        self.assertIsNone(info.size_bytes)
                        self.assertIsNone(info.sha256)
                        self.assertIsNone(info.matches_checksum(digest))
                    else:
                        self.assertEqual(info.serialization, "turtle")
                        self.assertEqual(info.size_bytes, len(raw))
                        self.assertEqual(info.sha256, digest)
                        self.assertTrue(
                            info.matches_checksum(" " + digest.upper() + " ")
                        )
                        self.assertFalse(info.matches_checksum("0" * 64))
                    with self.assertRaises(FrozenInstanceError):
                        info.triple_count = 0

    def test_graph_is_snapshotted_without_mutation(self):
        graph = Graph()
        graph.bind("example", "urn:example:")
        node = BNode("dataset")
        graph.add((node, URIRef("urn:p"), Literal("original")))
        before = (set(graph), tuple(graph.namespaces()))
        loaded = harvest(graph)
        self.assertEqual((set(graph), tuple(graph.namespaces())), before)
        graph.remove((None, None, None))
        selected = loaded.select_subject(loaded.subjects[0])
        self.assertEqual(selected.subject.term, node)
        self.assertEqual(
            selected.subject.evidence[0].triples,
            ((node.n3(), "<urn:p>", '"original"'),),
        )
        self.assertIsNone(loaded.subject)

    def test_relative_iris_use_inline_file_and_explicit_bases(self):
        text = "<dataset> <urn:p> <value> ."
        for source in (text, text.encode()):
            with self.subTest(source=source):
                self.assertEqual(
                    harvest(source).subjects[0].term,
                    URIRef("https://praeco.invalid/rdf/inline/dataset"),
                )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.ttl"
            path.write_text(text)
            self.assertEqual(
                harvest(path).subjects[0].term,
                URIRef((path.parent / "dataset").as_uri()),
            )
            explicit = "@base <https://example.org/base/> . " + text
            path.write_text(explicit)
            for source in (path, explicit, explicit.encode()):
                with self.subTest(source=source):
                    self.assertEqual(
                        harvest(source).subjects[0].term,
                        URIRef("https://example.org/base/dataset"),
                    )

    def test_input_errors_are_public_and_chained(self):
        for source in (
            "not Turtle",
            b"\xff",
            "https://example.org/data.ttl",
            Path("/nonexistent/praeco-rdf.ttl"),
            "\ud800",
        ):
            with (
                self.subTest(source=repr(source)),
                self.assertRaises(ValidationError) as caught,
            ):
                harvest(source)
            self.assertIsNotNone(caught.exception.__cause__)
        with patch.object(Path, "read_bytes", side_effect=PermissionError("denied")):
            with self.assertRaises(ValidationError) as caught:
                harvest(Path("unreadable.ttl"))
            self.assertIsInstance(caught.exception.__cause__, PermissionError)
        for source in (None, 3, {}):
            with self.subTest(source=source), self.assertRaises(ValidationError):
                harvest(source)

    def test_sources_do_not_fetch_urls_or_imports(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            result = harvest(
                "<urn:data> <http://www.w3.org/2002/07/owl#imports> <https://example.org/ontology> ."
            )
            self.assertEqual(result.source.triple_count, 1)
            with self.assertRaises(ValidationError):
                harvest("https://example.org/file.ttl")

    def test_anonymous_subjects_can_be_selected_from_all_local_forms(self):
        text = '[] <urn:p> "value" .'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anonymous.ttl"
            path.write_text(text)
            for source in (text, text.encode(), path):
                with self.subTest(source=source):
                    loaded = harvest(source)
                    self.assertIsInstance(loaded.subjects[0].term, BNode)
                    result = loaded.select_subject(loaded.subjects[0])
                    self.assertEqual(result.subject, loaded.subjects[0])
                    self.assertEqual(result.diagnostics, ())

    def test_subject_inspection_does_not_filter_or_rank_resources(self):
        text = """
        <urn:z> a <http://www.w3.org/ns/dcat#Dataset> .
        <urn:a> a <http://www.w3.org/ns/csvw#Column>;
            <http://www.w3.org/2000/01/rdf-schema#label> "Column"@en .
        """
        result = harvest(text)
        self.assertIsNone(result.subject)
        self.assertEqual(result.diagnostics[0].code, "subject_required")
        self.assertEqual(
            tuple(s.term for s in result.subjects), (URIRef("urn:a"), URIRef("urn:z"))
        )
        self.assertEqual(
            result.subjects[0].types, (URIRef("http://www.w3.org/ns/csvw#Column"),)
        )
        self.assertEqual(result.select_subject("urn:a").subject.term, URIRef("urn:a"))

    def test_missing_subject_does_not_fall_back_and_can_be_resolved(self):
        loaded = harvest("<urn:a> <urn:p> 1 .", subject="urn:absent")
        self.assertIsNone(loaded.subject)
        self.assertEqual(loaded.diagnostics[0].code, "subject_not_found")
        result = loaded.select_subject(URIRef("urn:a"))
        self.assertEqual(result.subject.term, URIRef("urn:a"))
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(harvest("").subjects, ())

    def test_selected_subject_is_fixed_and_foreign_records_are_rejected(self):
        loaded = harvest("<urn:a> <urn:p> 1 . <urn:b> <urn:p> 2 .")
        selected = loaded.select_subject("urn:a")
        self.assertEqual(selected.select_subject("urn:a"), selected)
        with self.assertRaisesRegex(ValidationError, "fixed"):
            selected.select_subject("urn:b")
        self.assertEqual(loaded.select_subject("urn:b").subject.term, URIRef("urn:b"))
        foreign = harvest("<urn:a> <urn:p> 1 .")
        with self.assertRaisesRegex(ValidationError, "another source"):
            selected.select_subject(foreign.subjects[0])

    def test_invalid_subject_and_language_inputs_are_rejected(self):
        for subject in (
            "",
            "relative",
            "urn:has space",
            BNode("x"),
            Literal("urn:x"),
            3,
        ):
            with self.subTest(subject=subject), self.assertRaises(ValidationError):
                harvest("", subject=subject)
        for languages in ("en", ["en"], (1,), ("",)):
            with self.subTest(languages=languages), self.assertRaises(ValidationError):
                harvest("", preferred_languages=languages)
        self.assertEqual(
            harvest("", preferred_languages=("EN", None)).source.triple_count, 0
        )
