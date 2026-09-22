import hashlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from unittest.mock import patch

import rdflib
from rdflib import XSD, BNode, Dataset, Graph, Literal, URIRef

from praeco.exceptions import ValidationError
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest


class TestLocalSources(unittest.TestCase):
    def test_dataset_containers_require_explicit_graph_selection(self):
        for location in ("empty", "default", "named"):
            with self.subTest(location=location):
                dataset = Dataset()
                if location != "empty":
                    graph = (
                        dataset.default_graph
                        if location == "default"
                        else dataset.graph(URIRef("urn:graph"))
                    )
                    graph.add((URIRef("urn:s"), URIRef("urn:p"), Literal("value")))
                before = set(dataset.quads())
                with self.assertRaisesRegex(
                    ValidationError, "Dataset input requires an explicit graph"
                ) as caught:
                    harvest(dataset)
                self.assertIn("dataset.default_graph", str(caught.exception))
                self.assertIn("dataset.graph(identifier)", str(caught.exception))
                self.assertEqual(set(dataset.quads()), before)

    def test_explicit_dataset_graphs_are_snapshotted_independently(self):
        dataset = Dataset()
        named = dataset.graph(URIRef("urn:graph"))
        subject, predicate = URIRef("urn:s"), URIRef("http://purl.org/dc/terms/title")
        dataset.default_graph.add((subject, predicate, Literal("Default title")))
        named.add((subject, predicate, Literal("Named title")))
        before = set(dataset.quads())
        for graph, title in (
            (dataset.default_graph, "Default title"),
            (named, "Named title"),
        ):
            with self.subTest(title=title):
                result = harvest(graph, subject=subject)
                self.assertEqual(result.title.value, title)
                self.assertEqual(result.source.triple_count, 1)
                self.assertEqual(len(result.title.candidates), 1)
                self.assertEqual(set(dataset.quads()), before)
        named.remove((None, None, None))
        self.assertEqual(result.title.value, "Named title")

    def test_typed_literal_spellings_survive_parsing_and_candidate_grouping(self):
        text = """@prefix dct: <http://purl.org/dc/terms/> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <urn:s> dct:issued "2021-02-03Z"^^xsd:date, "2021-02-03+02:00"^^xsd:date;
                dct:created "2020-01-01T00:00:00Z"^^xsd:dateTime,
                    "2020-01-01T00:00:00+00:00"^^xsd:dateTime;
                dct:title "01"^^xsd:integer, "1"^^xsd:integer;
                dct:description "Description"; dct:creator "Jane" ."""
        normalization = rdflib.NORMALIZE_LITERALS
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.ttl"
            path.write_bytes(text.encode())
            for source in (text, text.encode(), path):
                with self.subTest(kind=type(source).__name__):
                    result = harvest(source, subject="urn:s")
                    self.assertEqual(result.source.triple_count, 8)
                    self.assertEqual(len(result.publication_date.candidates), 1)
                    candidate = result.publication_date.candidates[0]
                    self.assertEqual(candidate.value, date(2021, 2, 3))
                    self.assertEqual(
                        {e.triples[0][2] for e in candidate.evidence},
                        {
                            f'"{value}"^^<{XSD.date}>'
                            for value in ("2021-02-03Z", "2021-02-03+02:00")
                        },
                    )
                    suggestion = result.publication_date.suggestions[0]
                    self.assertEqual(suggestion.value, date(2020, 1, 1))
                    self.assertEqual(
                        {e.triples[0][2] for e in suggestion.evidence},
                        {
                            f'"{value}"^^<{XSD.dateTime}>'
                            for value in (
                                "2020-01-01T00:00:00Z",
                                "2020-01-01T00:00:00+00:00",
                            )
                        },
                    )
                    self.assertEqual(
                        [c.value for c in result.title.candidates], ["01", "1"]
                    )
                    self.assertEqual(
                        result.with_overrides(title="Title")
                        .to_publication_metadata()
                        .publication_date,
                        date(2021, 2, 3),
                    )
                    self.assertEqual(rdflib.NORMALIZE_LITERALS, normalization)
        with self.assertRaises(ValidationError):
            harvest(text + "invalid Turtle")
        self.assertEqual(rdflib.NORMALIZE_LITERALS, normalization)
        # An independent RDFLib parse keeps its normal normalization behavior.
        self.assertEqual(len(Graph().parse(data=text, format="turtle")), 5)

    def test_graph_input_preserves_only_the_lexical_terms_supplied(self):
        subject, predicate = URIRef("urn:s"), URIRef("http://purl.org/dc/terms/issued")
        for normalize, count in ((False, 2), (True, 1)):
            with self.subTest(normalize=normalize):
                graph = Graph()
                for value in ("2021-02-03Z", "2021-02-03+02:00"):
                    graph.add(
                        (
                            subject,
                            predicate,
                            Literal(value, datatype=XSD.date, normalize=normalize),
                        )
                    )
                result = harvest(graph, subject=subject)
                self.assertEqual(result.source.triple_count, count)
                candidate = result.publication_date.candidates[0]
                self.assertEqual(candidate.value, date(2021, 2, 3))
                self.assertEqual(len(candidate.evidence), count)
                self.assertEqual(
                    {e.triples[0][2] for e in candidate.evidence},
                    {obj.n3() for obj in graph.objects(subject, predicate)},
                )

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
                    self.assertFalse(
                        any(d.code.startswith("subject_") for d in result.diagnostics)
                    )

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
        self.assertFalse(any(d.code.startswith("subject_") for d in result.diagnostics))
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
