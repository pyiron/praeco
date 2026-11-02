import unittest
from dataclasses import FrozenInstanceError

from rdflib import BNode, Graph, URIRef

from praeco.exceptions import ValidationError
from praeco.rdf_metadata import Evidence
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest

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
