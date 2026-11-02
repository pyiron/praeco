import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from rdflib import BNode, Graph, URIRef

import praeco
import praeco.rdf_metadata
from praeco import Organization, Person
from praeco.exceptions import ValidationError
from praeco.rdf_metadata import Evidence, IncompleteHarvestError, SubjectCandidate
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest

EXAMPLE = Path(__file__).parents[2] / "resources/rdf_metadata/review-example.ttl"

PREFIXES = """
@prefix csvw: <http://www.w3.org/ns/csvw#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""
TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
TITLE = "<http://purl.org/dc/terms/title>"
DATASET = "<http://www.w3.org/ns/dcat#Dataset>"
ONTOLOGY = "<http://www.w3.org/2002/07/owl#Ontology>"
ENTITY = "<http://www.w3.org/ns/prov#Entity>"
PUBLICATION_TYPES = (
    "http://www.w3.org/ns/dcat#Dataset",
    "http://schema.org/Dataset",
    "https://schema.org/Dataset",
    "http://rdfs.org/ns/void#Dataset",
    "http://www.w3.org/2002/07/owl#Ontology",
)
STRUCTURAL_TYPES = tuple(
    "http://www.w3.org/ns/csvw#" + name
    for name in (
        "Cell",
        "Column",
        "Datatype",
        "Dialect",
        "Direction",
        "ForeignKey",
        "NumericFormat",
        "Row",
        "Schema",
        "Table",
        "TableGroup",
        "TableReference",
        "Transformation",
    )
) + (
    "http://www.w3.org/ns/dcat#Distribution",
    "http://schema.org/DataDownload",
    "https://schema.org/DataDownload",
)
AGENT_LINKS = (
    "http://purl.org/dc/elements/1.1/creator",
    "http://purl.org/dc/terms/creator",
    "http://schema.org/creator",
    "https://schema.org/creator",
    "http://www.w3.org/ns/prov#wasAttributedTo",
)


def titled_dataset(term="<urn:s>"):
    return (
        Evidence("publication_type", ((term, TYPE, DATASET),)),
        Evidence("publication_title", ((term, TITLE, '"Title"'),)),
    )


class TestCandidateEligibility(unittest.TestCase):
    def test_titled_publication_types_are_eligible_candidates(self):
        for rdf_type in PUBLICATION_TYPES:
            with self.subTest(rdf_type=rdf_type):
                result = harvest(f'<urn:s> a <{rdf_type}>; {TITLE} "Title" .')
                (candidate,) = result.subject_candidates
                self.assertIs(candidate.subject, result.subjects[0])
                self.assertTrue(candidate.eligible)
                self.assertEqual(
                    candidate.evidence,
                    (
                        Evidence(
                            "publication_type", (("<urn:s>", TYPE, f"<{rdf_type}>"),)
                        ),
                        Evidence("publication_title", (("<urn:s>", TITLE, '"Title"'),)),
                    ),
                )

    def test_title_aliases_satisfy_the_title_rule(self):
        for predicate in (
            "http://purl.org/dc/elements/1.1/title",
            "http://purl.org/dc/terms/title",
            "http://schema.org/name",
            "https://schema.org/name",
        ):
            with self.subTest(predicate=predicate):
                result = harvest(f'<urn:s> a {DATASET}; <{predicate}> "Title"@en .')
                (candidate,) = result.subject_candidates
                self.assertTrue(candidate.eligible)
                self.assertEqual(
                    candidate.evidence[1],
                    Evidence(
                        "publication_title",
                        (("<urn:s>", f"<{predicate}>", '"Title"@en'),),
                    ),
                )

    def test_untitled_publication_types_are_listed_but_not_eligible(self):
        for statement in (
            "",
            f'; {TITLE} " "',
            f"; {TITLE} <urn:title>",
            f"; {TITLE} []",
            '; rdfs:label "Label"',
        ):
            with self.subTest(statement=statement):
                result = harvest(PREFIXES + f"<urn:s> a dcat:Dataset {statement} .")
                (candidate,) = result.subject_candidates
                self.assertFalse(candidate.eligible)
                self.assertEqual(
                    candidate.evidence,
                    (Evidence("publication_type", (("<urn:s>", TYPE, DATASET),)),),
                )

    def test_resources_without_a_publication_type_are_not_candidates(self):
        for text in (
            '<urn:s> dct:title "Title" .',
            '<urn:s> dct:title "Title"; dct:creator <urn:agent> .',
            '<urn:s> a <urn:Document>; dct:title "Title" .',
            '<urn:s> dct:type dcat:Dataset; dct:title "Title" .',
            '<urn:s> a csvw:Table; dct:title "Title"; csvw:url <urn:data.csv> .',
        ):
            with self.subTest(text=text):
                self.assertEqual(harvest(PREFIXES + text).subject_candidates, ())

    def test_only_explicitly_asserted_types_count(self):
        text = PREFIXES + """
            <urn:Publication> rdfs:subClassOf dcat:Dataset .
            <urn:catalog> dcat:dataset <urn:s> .
            <urn:s> a <urn:Publication>; dct:title "Title" .
            """
        self.assertEqual(harvest(text).subject_candidates, ())

    def test_attributed_entities_are_listed_but_never_eligible(self):
        for link in AGENT_LINKS:
            with self.subTest(link=link):
                result = harvest(
                    f'<urn:s> a {ENTITY}; {TITLE} "Title"; <{link}> <urn:agent> .'
                )
                (candidate,) = result.subject_candidates
                self.assertFalse(candidate.eligible)
                self.assertEqual(
                    candidate.evidence,
                    (
                        Evidence("publication_title", (("<urn:s>", TITLE, '"Title"'),)),
                        Evidence("entity_type", (("<urn:s>", TYPE, ENTITY),)),
                        Evidence(
                            "entity_agent", (("<urn:s>", f"<{link}>", "<urn:agent>"),)
                        ),
                    ),
                )

    def test_entities_without_title_and_agent_are_not_candidates(self):
        for text in (
            '<urn:s> a prov:Entity; dct:title "Title" .',
            "<urn:s> a prov:Entity; dct:creator <urn:agent> .",
            '<urn:s> a prov:Entity; dct:title " "; prov:wasAttributedTo <urn:agent> .',
        ):
            with self.subTest(text=text):
                self.assertEqual(harvest(PREFIXES + text).subject_candidates, ())

    def test_publication_typed_entities_keep_publication_eligibility(self):
        result = harvest(
            PREFIXES
            + '<urn:s> a dcat:Dataset, prov:Entity; dct:title "Title"; dct:creator "Jane" .'
        )
        (candidate,) = result.subject_candidates
        self.assertTrue(candidate.eligible)
        self.assertEqual(
            candidate.evidence,
            (
                *titled_dataset(),
                Evidence("entity_type", (("<urn:s>", TYPE, ENTITY),)),
                Evidence(
                    "entity_agent",
                    (("<urn:s>", "<http://purl.org/dc/terms/creator>", '"Jane"'),),
                ),
            ),
        )

    def test_structural_types_override_publication_types(self):
        for rdf_type in STRUCTURAL_TYPES:
            with self.subTest(rdf_type=rdf_type):
                result = harvest(
                    f'<urn:s> a {DATASET}, <{rdf_type}>; {TITLE} "Title" .'
                )
                (candidate,) = result.subject_candidates
                self.assertFalse(candidate.eligible)
                self.assertEqual(
                    candidate.evidence,
                    (
                        *titled_dataset(),
                        Evidence(
                            "structural_type", (("<urn:s>", TYPE, f"<{rdf_type}>"),)
                        ),
                    ),
                )

    def test_structural_properties_override_publication_types(self):
        for predicate in (
            "http://www.w3.org/ns/csvw#url",
            "http://www.w3.org/ns/csvw#tableSchema",
        ):
            with self.subTest(predicate=predicate):
                result = harvest(
                    f'<urn:s> a {DATASET}; {TITLE} "Title"; <{predicate}> <urn:o> .'
                )
                (candidate,) = result.subject_candidates
                self.assertFalse(candidate.eligible)
                self.assertEqual(
                    candidate.evidence,
                    (
                        *titled_dataset(),
                        Evidence(
                            "structural_property",
                            (("<urn:s>", f"<{predicate}>", "<urn:o>"),),
                        ),
                    ),
                )

    def test_structural_rules_override_attributed_entities(self):
        result = harvest(
            PREFIXES
            + '<urn:s> a prov:Entity, csvw:Column; dct:title "Title"; dct:creator <urn:a> .'
        )
        (candidate,) = result.subject_candidates
        self.assertFalse(candidate.eligible)
        self.assertEqual(
            candidate.evidence[-1],
            Evidence(
                "structural_type",
                (("<urn:s>", TYPE, "<http://www.w3.org/ns/csvw#Column>"),),
            ),
        )

    def test_mixed_type_table_is_listed_but_not_eligible(self):
        text = PREFIXES + """
            <urn:ontology> a owl:Ontology; dct:title "Ontology" .
            <urn:table> a csvw:Table, dcat:Dataset, obo:IAO_0000100;
                dct:title "Table"; csvw:url <urn:table.csv>; csvw:tableSchema <urn:schema> .
            <urn:data> a csvw:Table, obo:IAO_0000100; dct:title "Data" .
            """
        result = harvest(text)
        self.assertEqual(
            [(c.subject.term, c.eligible) for c in result.subject_candidates],
            [(URIRef("urn:ontology"), True), (URIRef("urn:table"), False)],
        )
        self.assertEqual(
            result.subject_candidates[1].evidence,
            (
                Evidence("publication_type", (("<urn:table>", TYPE, DATASET),)),
                Evidence("publication_title", (("<urn:table>", TITLE, '"Table"'),)),
                Evidence(
                    "structural_type",
                    (("<urn:table>", TYPE, "<http://www.w3.org/ns/csvw#Table>"),),
                ),
                Evidence(
                    "structural_property",
                    (
                        (
                            "<urn:table>",
                            "<http://www.w3.org/ns/csvw#tableSchema>",
                            "<urn:schema>",
                        ),
                        (
                            "<urn:table>",
                            "<http://www.w3.org/ns/csvw#url>",
                            "<urn:table.csv>",
                        ),
                    ),
                ),
            ),
        )


class TestCandidateRecords(unittest.TestCase):
    def test_repeated_types_aliases_and_translations_are_kept_as_evidence(self):
        text = f"""<urn:s> a {DATASET}, {ONTOLOGY};
            {TITLE} "Title"@en, "Titel"@de;
            <http://purl.org/dc/elements/1.1/title> "Title" ."""
        (candidate,) = harvest(text).subject_candidates
        self.assertTrue(candidate.eligible)
        self.assertEqual(
            candidate.evidence,
            (
                Evidence(
                    "publication_type",
                    (("<urn:s>", TYPE, ONTOLOGY), ("<urn:s>", TYPE, DATASET)),
                ),
                Evidence(
                    "publication_title",
                    (
                        (
                            "<urn:s>",
                            "<http://purl.org/dc/elements/1.1/title>",
                            '"Title"',
                        ),
                        ("<urn:s>", TITLE, '"Titel"@de'),
                        ("<urn:s>", TITLE, '"Title"@en'),
                    ),
                ),
            ),
        )

    def test_candidates_follow_subject_order_and_ignore_triple_order(self):
        text = PREFIXES + """
            <urn:c> a prov:Entity; dct:title "C"; prov:wasAttributedTo <urn:agent> .
            <urn:b> a owl:Ontology .
            <urn:a> a dcat:Dataset, csvw:Table; dct:title "A", "Alias"@de .
            <urn:agent> dct:title "Agent" .
            """
        graph = Graph().parse(data=text, format="turtle")
        reversed_graph = Graph()
        for triple in sorted(graph, key=str, reverse=True):
            reversed_graph.add(triple)
        result = harvest(text)
        self.assertEqual(
            [c.subject.term for c in result.subject_candidates],
            [URIRef("urn:a"), URIRef("urn:b"), URIRef("urn:c")],
        )
        self.assertEqual(
            [c.subject for c in result.subject_candidates],
            [s for s in result.subjects if s.term != URIRef("urn:agent")],
        )
        for name, source in (("parsed", graph), ("reversed", reversed_graph)):
            with self.subTest(source=name):
                self.assertEqual(
                    harvest(source).subject_candidates, result.subject_candidates
                )

    def test_candidates_are_available_on_every_harvest(self):
        text = f'<urn:s> a {DATASET}; {TITLE} "Title" .'
        expected = harvest(text).subject_candidates
        self.assertEqual(len(expected), 1)
        for result in (
            harvest(text, subject="urn:s"),
            harvest(text, subject="urn:absent"),
        ):
            with self.subTest(subject=result.subject):
                self.assertEqual(result.subject_candidates, expected)

    def test_blank_node_candidates_are_selectable_in_their_source(self):
        result = harvest(f'[] a {DATASET}; {TITLE} "Title" .')
        (candidate,) = result.subject_candidates
        term = result.subjects[0].term
        self.assertIsInstance(term, BNode)
        self.assertIs(candidate.subject, result.subjects[0])
        self.assertTrue(candidate.eligible)
        self.assertEqual(candidate.evidence, titled_dataset(term.n3()))
        selected = result.select_subject(candidate.subject)
        self.assertEqual(selected.subject.term, term)
        self.assertEqual(selected.title.value, "Title")

    def test_candidates_are_frozen_and_bound_to_their_source(self):
        text = f'<urn:s> a {DATASET}; {TITLE} "Title" .'
        (candidate,) = harvest(text).subject_candidates
        with self.assertRaises(FrozenInstanceError):
            candidate.eligible = False
        with self.assertRaisesRegex(ValidationError, "another source"):
            harvest(text).select_subject(candidate.subject)


FIELDS = (
    "title",
    "description",
    "creators",
    "publication_date",
    "contributors",
    "keywords",
    "license",
    "doi",
    "version",
    "language",
    "related_identifiers",
)


def subject_diagnostics(result):
    return [
        (item.code, item.field, item.subject, item.blocking)
        for item in result.diagnostics
    ]


class TestAutomaticSelection(unittest.TestCase):
    def test_omitted_subject_is_not_selected_before_an_attempt(self):
        result = harvest(f'<urn:s> a {DATASET}; {TITLE} "Title" .')
        self.assertIsNone(result.subject)
        self.assertIsNone(result.subject_origin)
        self.assertEqual(
            subject_diagnostics(result), [("subject_required", None, None, True)]
        )

    def test_single_dataset_beside_titled_csvw_structure_is_selected(self):
        text = PREFIXES + """
            <urn:dataset> a dcat:Dataset; dct:title "Measurements" .
            <urn:table> a csvw:Table, dcat:Dataset; dct:title "Table", "Tabelle"@de;
                csvw:url <urn:table.csv>; csvw:tableSchema <urn:schema> .
            <urn:schema> a csvw:Schema, dcat:Dataset; dct:title "Schema" .
            <urn:column> a csvw:Column, owl:Ontology; dct:title "Column" .
            <urn:file> a dcat:Distribution, dcat:Dataset; dct:title "File" .
            """
        loaded = harvest(text)
        result = loaded.select_subject_automatically()
        self.assertEqual(result.subject.term, URIRef("urn:dataset"))
        self.assertEqual(result.subject_origin, "automatic")
        self.assertEqual(result.title.value, "Measurements")
        self.assertFalse(
            any(item.code.startswith("subject_") for item in result.diagnostics)
        )
        self.assertEqual(
            [c.subject.term for c in loaded.subject_candidates if not c.eligible],
            [
                URIRef("urn:column"),
                URIRef("urn:file"),
                URIRef("urn:schema"),
                URIRef("urn:table"),
            ],
        )
        self.assertIsNone(loaded.subject)
        self.assertIsNone(loaded.subject_origin)

    def test_attributed_entity_does_not_block_a_single_dataset(self):
        text = PREFIXES + """
            <urn:dataset> a dcat:Dataset; dct:title "Dataset" .
            <urn:entity> a prov:Entity; dct:title "Entity"; dct:creator <urn:a> .
            """
        result = harvest(text).select_subject_automatically()
        self.assertEqual(result.subject.term, URIRef("urn:dataset"))

    def test_automatic_selection_extracts_like_explicit_selection(self):
        text = PREFIXES + """
            @prefix foaf: <http://xmlns.com/foaf/0.1/> .
            <urn:dataset> a dcat:Dataset; dct:title "A", "B";
                dct:description "Description"; dct:creator <urn:jane>, <urn:lab>;
                dct:issued "2020-01-01"; dct:created "2019-12-01";
                dcat:keyword "steel"; dct:identifier "not a DOI" .
            <urn:jane> a foaf:Person; foaf:name "Jane Doe" .
            """
        loaded = harvest(text)
        automatic = loaded.select_subject_automatically()
        explicit = loaded.select_subject("urn:dataset")
        self.assertEqual(automatic.subject, explicit.subject)
        for name in FIELDS:
            with self.subTest(name=name):
                self.assertEqual(getattr(automatic, name), getattr(explicit, name))
        self.assertEqual(automatic.diagnostics, explicit.diagnostics)
        self.assertEqual(
            (automatic.subject_origin, explicit.subject_origin),
            ("automatic", "selection"),
        )
        reviewed = automatic.select_candidate(automatic.title.candidates[0])
        self.assertEqual(reviewed.subject_origin, "automatic")
        self.assertIs(reviewed.select_subject("urn:dataset"), reviewed)

    def test_competing_publications_stay_unresolved(self):
        ontology = (
            Evidence("publication_type", (("<urn:b>", TYPE, ONTOLOGY),)),
            Evidence("publication_title", (("<urn:b>", TITLE, '"Title"'),)),
        )
        for case, second_type, second_evidence in (
            ("dataset and ontology", ONTOLOGY, ontology),
            ("two datasets", DATASET, titled_dataset("<urn:b>")),
        ):
            with self.subTest(case=case):
                text = f"""<urn:a> a {DATASET}; {TITLE} "Title" .
                    <urn:b> a {second_type}; {TITLE} "Title" ."""
                loaded = harvest(text)
                result = loaded.select_subject_automatically()
                self.assertIsNone(result.subject)
                self.assertIsNone(result.subject_origin)
                self.assertEqual(
                    subject_diagnostics(result),
                    [("subject_ambiguous", None, None, True)],
                )
                self.assertEqual(
                    result.diagnostics[0].evidence,
                    (*titled_dataset("<urn:a>"), *second_evidence),
                )
                self.assertEqual(
                    [(c.subject.term, c.eligible) for c in result.subject_candidates],
                    [(URIRef("urn:a"), True), (URIRef("urn:b"), True)],
                )
                self.assertEqual(
                    subject_diagnostics(loaded),
                    [("subject_required", None, None, True)],
                )

    def test_richer_metadata_does_not_resolve_competing_publications(self):
        text = PREFIXES + """
            <urn:rich> a dcat:Dataset, owl:Ontology, <https://schema.org/Dataset>;
                dct:title "Title"@en, "Titel"@de; <https://schema.org/name> "Title";
                dct:description "Description"; dct:creator <urn:agent> .
            <urn:plain> a dcat:Dataset; dct:title "Plain" .
            """
        result = harvest(text).select_subject_automatically()
        self.assertIsNone(result.subject)
        self.assertEqual(result.diagnostics[0].code, "subject_ambiguous")

    def test_blank_node_candidates_are_counted_by_term(self):
        block = f'[] a {DATASET}; {TITLE} "T" .\n'
        single = harvest(block).select_subject_automatically()
        (candidate,) = single.subject_candidates
        self.assertEqual(single.subject_origin, "automatic")
        self.assertIsInstance(single.subject.term, BNode)
        self.assertEqual(single.subject.term, candidate.subject.term)
        twice = harvest(block + block).select_subject_automatically()
        self.assertIsNone(twice.subject)
        self.assertEqual(
            subject_diagnostics(twice), [("subject_ambiguous", None, None, True)]
        )
        self.assertEqual([c.eligible for c in twice.subject_candidates], [True, True])
        first, second = (c.subject.term for c in twice.subject_candidates)
        self.assertNotEqual(first, second)

    def test_no_eligible_candidate_is_reported_as_missing(self):
        for text in (
            "",
            '<urn:s> dct:title "Title" .',
            "<urn:s> a dcat:Dataset .",
            '<urn:s> a dcat:Dataset, csvw:Table; dct:title "Title" .',
            '<urn:s> a prov:Entity; dct:title "Title"; dct:creator <urn:agent> .',
        ):
            with self.subTest(text=text):
                result = harvest(PREFIXES + text).select_subject_automatically()
                self.assertIsNone(result.subject)
                self.assertIsNone(result.subject_origin)
                self.assertEqual(
                    subject_diagnostics(result),
                    [("subject_candidate_missing", None, None, True)],
                )
                self.assertEqual(result.diagnostics[0].evidence, ())

    def test_selected_subject_is_fixed_against_automatic_selection(self):
        text = f'<urn:a> a {DATASET}; {TITLE} "Title" . <urn:b> <urn:p> 1 .'
        for origin, selected in (
            ("selection", harvest(text, subject="urn:b")),
            ("automatic", harvest(text).select_subject_automatically()),
        ):
            with self.subTest(origin=origin):
                before = (selected.subject, selected.title, selected.diagnostics)
                with self.assertRaisesRegex(ValidationError, "fixed"):
                    selected.select_subject_automatically()
                self.assertEqual(
                    (selected.subject, selected.title, selected.diagnostics), before
                )
                self.assertEqual(selected.subject_origin, origin)

    def test_absent_requested_subject_can_be_resolved_automatically(self):
        text = f'<urn:s> a {DATASET}; {TITLE} "Title" .'
        loaded = harvest(text, subject="urn:absent")
        result = loaded.select_subject_automatically()
        self.assertEqual(result.subject.term, URIRef("urn:s"))
        self.assertEqual(result.subject_origin, "automatic")
        self.assertFalse(
            any(item.code.startswith("subject_") for item in result.diagnostics)
        )
        self.assertEqual(
            subject_diagnostics(loaded),
            [("subject_not_found", None, URIRef("urn:absent"), True)],
        )

    def test_failed_attempt_keeps_the_absent_subject_diagnostic(self):
        for code, text in (
            ("subject_candidate_missing", "<urn:s> <urn:p> 1 ."),
            (
                "subject_ambiguous",
                f'<urn:a> a {DATASET}; {TITLE} "A" . <urn:b> a {DATASET}; {TITLE} "B" .',
            ),
        ):
            with self.subTest(code=code):
                result = harvest(
                    text, subject="urn:absent"
                ).select_subject_automatically()
                self.assertEqual(
                    subject_diagnostics(result),
                    [
                        ("subject_not_found", None, URIRef("urn:absent"), True),
                        (code, None, None, True),
                    ],
                )

    def test_explicit_selection_resolves_a_failed_attempt(self):
        text = f'<urn:a> a {DATASET}; {TITLE} "A" . <urn:b> a {DATASET}; {TITLE} "B" .'
        loaded = harvest(text)
        failed = loaded.select_subject_automatically()
        candidate = failed.subject_candidates[1]
        result = failed.select_subject(candidate.subject)
        self.assertEqual(result.subject.term, URIRef("urn:b"))
        self.assertEqual(result.subject_origin, "selection")
        self.assertEqual(result.diagnostics, loaded.select_subject("urn:b").diagnostics)
        self.assertEqual(failed.diagnostics[0].code, "subject_ambiguous")

    def test_explicit_selection_after_a_failed_attempt(self):
        text = f'<urn:a> a {DATASET}; {TITLE} "A" . <urn:b> a {DATASET}; {TITLE} "B" .'
        loaded = harvest(text)
        failed = loaded.select_subject_automatically()
        absent = failed.select_subject("urn:absent")
        expected = [
            ("subject_not_found", None, URIRef("urn:absent"), True),
            ("subject_ambiguous", None, None, True),
        ]
        self.assertIsNone(absent.subject)
        self.assertIsNone(absent.subject_origin)
        self.assertEqual(subject_diagnostics(absent), expected)
        repeated = absent.select_subject_automatically()
        self.assertEqual(subject_diagnostics(repeated), expected)
        # A successful explicit selection leaves no trace of the failed attempt.
        self.assertEqual(failed.select_subject("urn:a"), loaded.select_subject("urn:a"))

    def test_excluded_resources_remain_explicitly_selectable(self):
        text = PREFIXES + """
            <urn:dataset> a dcat:Dataset; dct:title "Dataset" .
            <urn:table> a csvw:Table, dcat:Dataset; dct:title "Table" .
            """
        loaded = harvest(text)
        table = next(c for c in loaded.subject_candidates if not c.eligible)
        result = loaded.select_subject(table.subject)
        self.assertEqual(result.subject.term, URIRef("urn:table"))
        self.assertEqual(result.subject_origin, "selection")
        self.assertEqual(result.title.value, "Table")

    def test_review_example_converts_after_automatic_selection(self):
        harvest_ = harvest(EXAMPLE).select_subject_automatically()
        self.assertEqual(str(harvest_.subject.term), "https://example.org/dataset")
        self.assertEqual(harvest_.subject_origin, "automatic")
        self.assertEqual(
            [candidate.value for candidate in harvest_.title.candidates],
            ["Tensile measurements", "Tensile test data"],
        )
        harvest_ = harvest_.select_candidate(harvest_.title.candidates[0])
        harvest_ = harvest_.with_overrides(
            description="Measurements from tensile tests.",
            creators=(Person(name="Jane Doe"), Organization(name="Materials Lab")),
        )
        with self.assertRaises(IncompleteHarvestError) as caught:
            harvest_.to_publication_metadata()
        self.assertEqual(
            [item.field for item in caught.exception.diagnostics], ["publication_date"]
        )
        metadata = harvest_.clear("publication_date").to_publication_metadata()
        self.assertEqual(metadata.title, "Tensile measurements")
        self.assertEqual(metadata.description, "Measurements from tensile tests.")
        self.assertEqual(
            metadata.creators,
            (Person(name="Jane Doe"), Organization(name="Materials Lab")),
        )
        self.assertIsNone(metadata.publication_date)
        self.assertEqual(metadata.keywords, ("steel", "tensile testing"))
        self.assertEqual(metadata.license, "CC-BY-4.0")

    def test_subject_candidate_is_exported_from_the_rdf_package_only(self):
        (candidate,) = harvest(f"<urn:s> a {DATASET} .").subject_candidates
        self.assertIsInstance(candidate, SubjectCandidate)
        self.assertIn("SubjectCandidate", praeco.rdf_metadata.__all__)
        self.assertFalse(hasattr(praeco, "SubjectCandidate"))
        self.assertNotIn("SubjectCandidate", praeco.__all__)
