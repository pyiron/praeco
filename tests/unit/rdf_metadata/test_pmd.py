import unittest
from dataclasses import replace
from pathlib import Path

from rdflib import BNode, Graph

from praeco import Person
from praeco.exceptions import ValidationError
from praeco.rdf_metadata import Evidence, Suggestion
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest

REVIEW_EXAMPLE = Path(__file__).parents[2] / "resources/rdf_metadata/review-example.ttl"
PREFIXES = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix csvw: <http://www.w3.org/ns/csvw#> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix pmd: <https://w3id.org/pmd/co/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix tto: <https://w3id.org/pmd/tto/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""
PUBLICATION = '<urn:publication> a owl:Ontology ; dct:title "Title" .\n'
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
TENSILE_TEST_2 = "<urn:test> a tto:TensileTest ; pmd:input <urn:piece> .\n"
TEST_EVIDENCE_2 = Evidence(
    "pmdco2_tensile_test",
    (
        ("<urn:test>", RDF_TYPE, "<https://w3id.org/pmd/tto/TensileTest>"),
        ("<urn:test>", "<https://w3id.org/pmd/co/input>", "<urn:piece>"),
    ),
)
MATERIAL_2 = '<urn:c> a pmd:MaterialDesignation ; pmd:value "S355" .\n'
STANDARD_2 = """
<urn:test> pmd:characteristic <urn:norm> .
<urn:norm> a pmd:Norm ; pmd:value "DIN EN ISO 6892-1" .
"""


TENSILE_TEST_3 = "<urn:test> a pmd:PMD_0000974 ; obo:OBI_0000293 <urn:piece> .\n"
TEST_EVIDENCE_3 = Evidence(
    "pmdco3_tensile_test",
    (
        ("<urn:test>", "<http://purl.obolibrary.org/obo/OBI_0000293>", "<urn:piece>"),
        ("<urn:test>", RDF_TYPE, "<https://w3id.org/pmd/co/PMD_0000974>"),
    ),
)
MATERIAL_3 = """
<urn:id> obo:IAO_0000219 <urn:steel> .
<urn:steel> a pmd:PMD_0020096 .
<urn:id> obo:OBI_0001938 <urn:spec> .
<urn:spec> pmd:PMD_0000006 "S355" .
"""
STANDARD_3 = """
<urn:test> obo:BFO_0000055 <urn:method> .
<urn:method> a tto:TTO_0000054 .
<urn:method-id> obo:IAO_0000219 <urn:method> .
<urn:method-id> obo:OBI_0001938 <urn:method-spec> .
<urn:method-spec> pmd:PMD_0000006 "DIN EN ISO 6892-1" .
"""
# For behavior that does not depend on the generation: test, its evidence, facts.
GENERATIONS = (
    ("pmdco2", TENSILE_TEST_2, TEST_EVIDENCE_2, MATERIAL_2 + STANDARD_2),
    ("pmdco3", TENSILE_TEST_3, TEST_EVIDENCE_3, MATERIAL_3 + STANDARD_3),
)


def selected(turtle: str):
    """Select automatically, with PUBLICATION as the file's own publication."""
    return harvest(PREFIXES + PUBLICATION + turtle).select_subject_automatically()


def offered(result) -> tuple[list[str], list[tuple[str, ...]]]:
    return (
        [item.value for item in result.description.suggestions],
        [item.value for item in result.keywords.suggestions],
    )


def codes(result) -> list[str]:
    return [item.code for item in result.diagnostics]


class TestPmdco2TensileTestRule(unittest.TestCase):
    def test_each_test_class_iri_gives_a_test_with_exact_evidence(self):
        for rdf_type in (
            "https://w3id.org/pmd/tto/TensileTest",
            "https://w3id.org/pmd/co/TensileTest",
        ):
            with self.subTest(rdf_type=rdf_type):
                result = selected(
                    f"<urn:test> a <{rdf_type}> ; pmd:input <urn:piece> ."
                )
                self.assertEqual(
                    offered(result),
                    (["Data from 1 tensile test."], [("tensile test",)]),
                )
                expected = (
                    Evidence(
                        "pmdco2_tensile_test",
                        (
                            ("<urn:test>", RDF_TYPE, f"<{rdf_type}>"),
                            (
                                "<urn:test>",
                                "<https://w3id.org/pmd/co/input>",
                                "<urn:piece>",
                            ),
                        ),
                    ),
                )
                self.assertEqual(result.description.suggestions[0].evidence, expected)
                self.assertEqual(result.keywords.suggestions[0].evidence, expected)

    def test_similar_test_class_iris_do_not_match(self):
        for rdf_type in (
            "https://w3id.org/pmd/co/tensileTest",
            "https://w3id.org/pmd/tto/tensiletest",
            "https://w3id.org/pmd/other/TensileTest",
            "http://w3id.org/pmd/co/TensileTest",
            "https://w3id.org/pmd/co/PMD_0000974",
        ):
            with self.subTest(rdf_type=rdf_type):
                result = selected(
                    f"<urn:test> a <{rdf_type}> ; pmd:input <urn:piece> ."
                )
                self.assertEqual(offered(result), ([], []))
                self.assertEqual(result.diagnostics, selected("").diagnostics)

    def test_similar_input_predicates_do_not_match(self):
        for predicate in (
            "https://w3id.org/pmd/co/Input",
            "https://w3id.org/pmd/tto/input",
            "http://purl.obolibrary.org/obo/OBI_0000293",
        ):
            with self.subTest(predicate=predicate):
                result = selected(
                    f"<urn:test> a tto:TensileTest ; <{predicate}> <urn:piece> ."
                )
                self.assertEqual(offered(result), ([], []))

    def test_test_without_an_input_is_not_a_signature(self):
        result = selected("<urn:step> a tto:TensileTest ." + MATERIAL_2)
        self.assertEqual(offered(result), ([], []))
        self.assertEqual(result.diagnostics, selected("").diagnostics)

    def test_sub_step_without_an_input_is_not_counted(self):
        result = selected(TENSILE_TEST_2 + "<urn:step> a tto:TensileTest .")
        self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])
        self.assertEqual(result.description.suggestions[0].evidence, (TEST_EVIDENCE_2,))

    def test_count_is_plural_for_several_tests(self):
        result = selected(
            TENSILE_TEST_2 + "<urn:other> a pmd:TensileTest ; pmd:input <urn:piece> ."
        )
        self.assertEqual(offered(result)[0], ["Data from 2 tensile tests."])

    def test_resource_with_both_classes_and_two_inputs_is_one_test(self):
        result = selected(
            "<urn:test> a tto:TensileTest, pmd:TensileTest ;"
            " pmd:input <urn:a>, <urn:b> ."
        )
        self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])
        self.assertEqual(
            result.description.suggestions[0].evidence,
            (
                Evidence(
                    "pmdco2_tensile_test",
                    (
                        (
                            "<urn:test>",
                            RDF_TYPE,
                            "<https://w3id.org/pmd/co/TensileTest>",
                        ),
                        (
                            "<urn:test>",
                            RDF_TYPE,
                            "<https://w3id.org/pmd/tto/TensileTest>",
                        ),
                        ("<urn:test>", "<https://w3id.org/pmd/co/input>", "<urn:a>"),
                        ("<urn:test>", "<https://w3id.org/pmd/co/input>", "<urn:b>"),
                    ),
                ),
            ),
        )

    def test_anonymous_test_and_input_are_counted(self):
        result = selected("[] a tto:TensileTest ; pmd:input [] .")
        self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])


class TestPmdco2MaterialRule(unittest.TestCase):
    def test_each_material_class_iri_gives_the_fact_with_exact_evidence(self):
        for rdf_type in (
            "https://w3id.org/pmd/co/MaterialDesignation",
            "https://w3id.org/pmd/co/materialDesignation",
        ):
            with self.subTest(rdf_type=rdf_type):
                result = selected(
                    TENSILE_TEST_2 + f'<urn:c> a <{rdf_type}> ; pmd:value "S355" .'
                )
                self.assertEqual(
                    offered(result),
                    (
                        ["Data from 1 tensile test. Material: S355."],
                        [("S355", "tensile test")],
                    ),
                )
                expected = (
                    TEST_EVIDENCE_2,
                    Evidence(
                        "pmdco2_material",
                        (
                            ("<urn:c>", RDF_TYPE, f"<{rdf_type}>"),
                            ("<urn:c>", "<https://w3id.org/pmd/co/value>", '"S355"'),
                        ),
                    ),
                )
                self.assertEqual(result.description.suggestions[0].evidence, expected)
                self.assertEqual(result.keywords.suggestions[0].evidence, expected)

    def test_material_is_file_wide_and_needs_no_link_to_a_test(self):
        for link in ("", "<urn:test> pmd:characteristic <urn:c> ."):
            with self.subTest(link=link):
                result = selected(TENSILE_TEST_2 + MATERIAL_2 + link)
                self.assertEqual(
                    offered(result)[0], ["Data from 1 tensile test. Material: S355."]
                )

    def test_similar_material_class_iris_do_not_match(self):
        for rdf_type in (
            "https://w3id.org/pmd/co/materialdesignation",
            "https://w3id.org/pmd/tto/MaterialDesignation",
            "http://w3id.org/pmd/co/MaterialDesignation",
        ):
            with self.subTest(rdf_type=rdf_type):
                result = selected(
                    TENSILE_TEST_2 + f'<urn:c> a <{rdf_type}> ; pmd:value "S355" .'
                )
                self.assertEqual(
                    offered(result),
                    (["Data from 1 tensile test."], [("tensile test",)]),
                )

    def test_removing_the_type_or_value_drops_the_sentence(self):
        for triples in (
            '<urn:c> pmd:value "S355" .',
            "<urn:c> a pmd:MaterialDesignation .",
            '<urn:c> a pmd:MaterialDesignation ; pmd:Value "S355" .',
            '<urn:c> a pmd:MaterialDesignation ; tto:value "S355" .',
        ):
            with self.subTest(triples=triples):
                result = selected(TENSILE_TEST_2 + triples)
                self.assertEqual(
                    offered(result),
                    (["Data from 1 tensile test."], [("tensile test",)]),
                )
                self.assertEqual(
                    result.description.suggestions[0].evidence, (TEST_EVIDENCE_2,)
                )

    def test_label_or_identifier_saying_material_is_not_a_fact(self):
        result = selected(
            TENSILE_TEST_2
            + """<urn:material> rdfs:label "material" ; pmd:value "S355" ;
                a <https://w3id.org/pmd/co/Thing> .
            <urn:c> rdfs:label "S355" ; a pmd:MaterialDesignation ."""
        )
        self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])


class TestPmdco2TestStandardRule(unittest.TestCase):
    def test_norm_of_a_test_gives_the_fact_with_exact_evidence(self):
        result = selected(TENSILE_TEST_2 + STANDARD_2)
        suggestion = result.description.suggestions[0]
        self.assertEqual(
            suggestion.value,
            "Data from 1 tensile test. Test standard: DIN EN ISO 6892-1.",
        )
        self.assertEqual(
            suggestion.evidence,
            (
                TEST_EVIDENCE_2,
                Evidence(
                    "pmdco2_test_standard",
                    (
                        ("<urn:norm>", RDF_TYPE, "<https://w3id.org/pmd/co/Norm>"),
                        (
                            "<urn:norm>",
                            "<https://w3id.org/pmd/co/value>",
                            '"DIN EN ISO 6892-1"',
                        ),
                        (
                            "<urn:test>",
                            "<https://w3id.org/pmd/co/characteristic>",
                            "<urn:norm>",
                        ),
                    ),
                ),
            ),
        )

    def test_standard_is_not_a_keyword(self):
        result = selected(TENSILE_TEST_2 + STANDARD_2)
        self.assertEqual(offered(result)[1], [("tensile test",)])
        self.assertEqual(result.keywords.suggestions[0].evidence, (TEST_EVIDENCE_2,))

    def test_removing_a_required_path_drops_the_sentence(self):
        for triples in (
            '<urn:norm> a pmd:Norm ; pmd:value "DIN" .',
            '<urn:test> pmd:characteristic <urn:norm> . <urn:norm> pmd:value "DIN" .',
            "<urn:test> pmd:characteristic <urn:norm> . <urn:norm> a pmd:Norm .",
        ):
            with self.subTest(triples=triples):
                result = selected(TENSILE_TEST_2 + triples)
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])
                self.assertEqual(
                    result.description.suggestions[0].evidence, (TEST_EVIDENCE_2,)
                )

    def test_similar_norm_terms_do_not_match(self):
        for triples in (
            '<urn:test> pmd:characteristic <urn:n> . <urn:n> a pmd:norm ; pmd:value "D" .',
            '<urn:test> pmd:characteristic <urn:n> . <urn:n> a tto:Norm ; pmd:value "D" .',
            '<urn:test> pmd:Characteristic <urn:n> . <urn:n> a pmd:Norm ; pmd:value "D" .',
            '<urn:test> tto:characteristic <urn:n> . <urn:n> a pmd:Norm ; pmd:value "D" .',
            '<urn:test> pmd:characteristic <urn:n> . <urn:n> a pmd:Norm ; pmd:Value "D" .',
            '<urn:test> pmd:characteristic <urn:n> . <urn:n> a pmd:Norm ; tto:value "D" .',
            '<urn:test> pmd:characteristic <urn:n> . <urn:n> a pmd:Norm ; rdfs:label "D" .',
        ):
            with self.subTest(triples=triples):
                result = selected(TENSILE_TEST_2 + triples)
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_norms_outside_a_counted_test_do_not_match(self):
        for owner in (
            "<urn:machine> a <https://w3id.org/pmd/co/TestingMachine> ;",
            "<urn:extensometer> a <https://w3id.org/pmd/co/Extensometer> ;",
            "<urn:step> a tto:TensileTest ;",
        ):
            with self.subTest(owner=owner):
                result = selected(
                    TENSILE_TEST_2 + owner + """ pmd:characteristic <urn:n> .
                    <urn:n> a pmd:Norm ; pmd:value "DIN EN ISO 7500-1" ."""
                )
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_shared_norm_is_listed_once_with_every_link(self):
        result = selected(
            TENSILE_TEST_2
            + "<urn:other> a tto:TensileTest ; pmd:input <urn:piece> ;"
            + " pmd:characteristic <urn:norm> ."
            + STANDARD_2
        )
        suggestion = result.description.suggestions[0]
        self.assertEqual(
            suggestion.value,
            "Data from 2 tensile tests. Test standard: DIN EN ISO 6892-1.",
        )
        self.assertEqual(
            [triple[0] for triple in suggestion.evidence[1].triples],
            ["<urn:norm>", "<urn:norm>", "<urn:other>", "<urn:test>"],
        )


class TestPmdValueHandling(unittest.TestCase):
    def test_invalid_values_are_not_facts(self):
        for value in ('""', '"  "', "<urn:value>", "[]"):
            with self.subTest(value=value):
                result = selected(
                    TENSILE_TEST_2
                    + f"<urn:c> a pmd:MaterialDesignation ; pmd:value {value} ."
                    + "<urn:test> pmd:characteristic <urn:n> ."
                    + f"<urn:n> a pmd:Norm ; pmd:value {value} ."
                )
                self.assertEqual(
                    offered(result),
                    (["Data from 1 tensile test."], [("tensile test",)]),
                )
                self.assertEqual(
                    result.description.suggestions[0].evidence, (TEST_EVIDENCE_2,)
                )

    def test_invalid_value_beside_a_valid_one_leaves_no_evidence(self):
        result = selected(
            TENSILE_TEST_2
            + '<urn:c> a pmd:MaterialDesignation ; pmd:value "S355", " ", <urn:v> .'
        )
        self.assertEqual(
            result.description.suggestions[0].evidence[1],
            Evidence(
                "pmdco2_material",
                (
                    (
                        "<urn:c>",
                        RDF_TYPE,
                        "<https://w3id.org/pmd/co/MaterialDesignation>",
                    ),
                    ("<urn:c>", "<https://w3id.org/pmd/co/value>", '"S355"'),
                ),
            ),
        )

    def test_values_are_trimmed_and_merged_keeping_every_triple(self):
        result = selected(
            TENSILE_TEST_2
            + """<urn:c> a pmd:MaterialDesignation ; pmd:value " S355 ", "S355", "S355"@en .
            <urn:d> a pmd:materialDesignation ; pmd:value "S355 " ."""
        )
        self.assertEqual(
            offered(result),
            (
                ["Data from 1 tensile test. Material: S355."],
                [("S355", "tensile test")],
            ),
        )
        self.assertEqual(
            result.keywords.suggestions[0].evidence[1],
            Evidence(
                "pmdco2_material",
                (
                    (
                        "<urn:c>",
                        RDF_TYPE,
                        "<https://w3id.org/pmd/co/MaterialDesignation>",
                    ),
                    ("<urn:c>", "<https://w3id.org/pmd/co/value>", '" S355 "'),
                    ("<urn:c>", "<https://w3id.org/pmd/co/value>", '"S355"'),
                    ("<urn:c>", "<https://w3id.org/pmd/co/value>", '"S355"@en'),
                    (
                        "<urn:d>",
                        RDF_TYPE,
                        "<https://w3id.org/pmd/co/materialDesignation>",
                    ),
                    ("<urn:d>", "<https://w3id.org/pmd/co/value>", '"S355 "'),
                ),
            ),
        )

    def test_several_values_are_listed_sorted_by_case_folded_text(self):
        result = selected(
            TENSILE_TEST_2
            + """<urn:c> a pmd:MaterialDesignation ; pmd:value "b-steel", "Zinc", "A-steel" .
            <urn:test> pmd:characteristic <urn:n>, <urn:m> .
            <urn:n> a pmd:Norm ; pmd:value "iso 2" .
            <urn:m> a pmd:Norm ; pmd:value "DIN 1" ."""
        )
        self.assertEqual(
            offered(result),
            (
                [
                    "Data from 1 tensile test. Materials: A-steel, b-steel, Zinc."
                    " Test standards: DIN 1, iso 2."
                ],
                [("A-steel", "b-steel", "tensile test", "Zinc")],
            ),
        )

    def test_values_differing_only_in_case_stay_distinct_in_stable_order(self):
        result = selected(
            TENSILE_TEST_2
            + '<urn:c> a pmd:MaterialDesignation ; pmd:value "s355", "S355" .'
        )
        self.assertEqual(
            offered(result),
            (
                ["Data from 1 tensile test. Materials: S355, s355."],
                [("S355", "s355", "tensile test")],
            ),
        )

    def test_non_string_typed_literals_are_values(self):
        xsd = "http://www.w3.org/2001/XMLSchema#"
        for obj, text, keywords, term in (
            (
                '"355"^^xsd:integer',
                "355",
                ("355", "tensile test"),
                f'"355"^^<{xsd}integer>',
            ),
            ("355", "355", ("355", "tensile test"), f'"355"^^<{xsd}integer>'),
            ("true", "true", ("tensile test", "true"), f'"true"^^<{xsd}boolean>'),
            (
                '"2021-01-01"^^xsd:date',
                "2021-01-01",
                ("2021-01-01", "tensile test"),
                f'"2021-01-01"^^<{xsd}date>',
            ),
        ):
            for turtle in (
                TENSILE_TEST_2
                + f"<urn:c> a pmd:MaterialDesignation ; pmd:value {obj} .",
                TENSILE_TEST_3 + MATERIAL_3.replace('"S355"', obj),
            ):
                with self.subTest(turtle=turtle):
                    result = selected(turtle)
                    self.assertEqual(
                        offered(result),
                        ([f"Data from 1 tensile test. Material: {text}."], [keywords]),
                    )
                    self.assertIn(
                        term,
                        [
                            triple[2]
                            for triple in result.keywords.suggestions[0]
                            .evidence[1]
                            .triples
                        ],
                    )

    def test_material_equal_to_the_process_keyword_is_deduplicated(self):
        result = selected(
            TENSILE_TEST_2
            + '<urn:c> a pmd:MaterialDesignation ; pmd:value "tensile test" .'
        )
        self.assertEqual(offered(result)[1], [("tensile test",)])


class TestPmdSuggestionBoundary(unittest.TestCase):
    OBSERVED = """<urn:publication> dct:description "Observed" ;
        dcat:keyword "steel" ; dct:created "2020-01-02" ; dct:creator "Jane Doe" .
    """

    def test_suggestions_leave_every_review_field_unchanged(self):
        without = selected(self.OBSERVED)
        result = selected(self.OBSERVED + TENSILE_TEST_2 + MATERIAL_2 + STANDARD_2)
        for name in ("title", "description", "publication_date", "keywords"):
            with self.subTest(name=name):
                before, after = getattr(without, name), getattr(result, name)
                self.assertEqual(after.value, before.value)
                self.assertEqual(after.status, before.status)
                self.assertEqual(after.origin, before.origin)
                self.assertEqual(after.candidates, before.candidates)
                self.assertEqual(after.selection, before.selection)
                self.assertEqual(after.observations, before.observations)
        self.assertEqual(
            result.publication_date.suggestions, without.publication_date.suggestions
        )
        self.assertEqual(result.creators, without.creators)
        self.assertEqual(result.diagnostics, without.diagnostics)

    def test_observed_values_stay_active_beside_the_suggestions(self):
        result = selected(self.OBSERVED + TENSILE_TEST_2)
        self.assertEqual(result.description.value, "Observed")
        self.assertEqual(result.keywords.value, ("steel",))
        self.assertEqual(
            offered(result),
            (["Data from 1 tensile test."], [("tensile test",)]),
        )
        metadata = result.to_publication_metadata()
        self.assertEqual(metadata.description, "Observed")
        self.assertEqual(metadata.keywords, ("steel",))

    def test_unaccepted_suggestions_are_neither_published_nor_blocking(self):
        result = selected(TENSILE_TEST_2 + MATERIAL_2)
        self.assertEqual(
            [(item.code, item.field) for item in result.diagnostics if item.blocking],
            [("missing_required", "description"), ("missing_required", "creators")],
        )
        reviewed = result.with_overrides(
            description="Reviewed", creators=(Person(name="Jane Doe"),)
        )
        self.assertEqual(reviewed.diagnostics, ())
        metadata = reviewed.to_publication_metadata()
        self.assertEqual(metadata.description, "Reviewed")
        self.assertEqual(metadata.keywords, ())
        self.assertEqual(
            offered(reviewed),
            (
                ["Data from 1 tensile test. Material: S355."],
                [("S355", "tensile test")],
            ),
        )

    def test_candidate_selection_leaves_the_description_suggestion_available(self):
        result = selected(
            '<urn:publication> dct:description "X", "Y" .' + TENSILE_TEST_2
        )
        review = result.description
        self.assertEqual(review.status, "unresolved")

        chosen = result.select_candidate(review.candidates[0]).description

        self.assertEqual(chosen.value, "X")
        self.assertEqual(chosen.origin, "selection")
        self.assertIs(chosen.selection, review.candidates[0])
        self.assertEqual(chosen.suggestions, review.suggestions)

    def test_candidate_selection_replaces_an_accepted_description_suggestion(self):
        result = selected(
            '<urn:publication> dct:description "X", "Y" .' + TENSILE_TEST_2
        )
        review = result.description
        suggestion = review.suggestions[0]

        accepted = result.accept_suggestion(suggestion)

        self.assertEqual(accepted.description.value, "Data from 1 tensile test.")
        self.assertEqual(accepted.description.status, "resolved")
        self.assertEqual(accepted.description.origin, "acceptance")
        self.assertIs(accepted.description.selection, suggestion)
        self.assertEqual(accepted.description.candidates, review.candidates)

        chosen = accepted.select_candidate(review.candidates[1]).description

        self.assertEqual(chosen.value, "Y")
        self.assertEqual(chosen.origin, "selection")
        self.assertIs(chosen.selection, review.candidates[1])
        self.assertEqual(chosen.suggestions, (suggestion,))

    def test_rules_do_not_synthesize_a_date_title_or_creator(self):
        result = selected(
            TENSILE_TEST_2 + '<urn:test> pmd:date "2021-02-22" ; pmd:operator "M." .'
        )
        self.assertEqual(result.title.value, "Title")
        self.assertEqual(result.title.suggestions, ())
        self.assertEqual(result.publication_date.status, "missing")
        self.assertEqual(result.publication_date.suggestions, ())
        self.assertEqual(result.creators.status, "missing")
        self.assertEqual(result.creators.observations, ())


class TestPmdNoSignature(unittest.TestCase):
    def test_material_or_norm_without_a_test_changes_nothing(self):
        for triples in (MATERIAL_2, STANDARD_2, MATERIAL_3, STANDARD_3):
            with self.subTest(triples=triples):
                result = selected(triples)
                self.assertEqual(offered(result), ([], []))
                self.assertEqual(result.diagnostics, selected("").diagnostics)

    def test_typed_resource_without_an_input_gives_a_non_sole_subject_no_diagnostic(
        self,
    ):
        for step, facts in (
            ("<urn:step> a tto:TensileTest .", MATERIAL_2 + STANDARD_2),
            ("<urn:step> a pmd:TensileTest .", MATERIAL_2 + STANDARD_2),
            ("<urn:step> a pmd:PMD_0000974 .", MATERIAL_3 + STANDARD_3),
        ):
            turtle = (
                PREFIXES
                + PUBLICATION
                + step
                + facts
                + '<urn:table> a csvw:Table ; dct:title "Table" .'
            )
            for term in ("urn:step", "urn:table"):
                with self.subTest(step=step, term=term):
                    result = harvest(turtle, subject=term)
                    self.assertEqual(str(result.subject.term), term)
                    self.assertEqual(offered(result), ([], []))
                    self.assertEqual(
                        [code for code in codes(result) if code.startswith("pmd_")], []
                    )

    def test_review_example_has_no_suggestions_or_new_diagnostics(self):
        source = harvest(REVIEW_EXAMPLE)
        result = source.select_subject(source.subjects[0])
        self.assertEqual(offered(result), ([], []))
        self.assertCountEqual(
            codes(result),
            [
                "unresolved_field",
                "unresolved_field",
                "missing_required",
                "unresolved_creator",
            ],
        )


class TestPmdSubjectGuard(unittest.TestCase):
    def assert_refused(self, result, term: str, evidence: Evidence) -> None:
        self.assertEqual(offered(result), ([], []))
        refusal = result.diagnostics[-1]
        self.assertEqual(refusal.code, "pmd_subject_not_sole_candidate")
        self.assertEqual(codes(result).count(refusal.code), 1)
        self.assertIsNone(refusal.field)
        self.assertEqual(str(refusal.subject), term)
        self.assertFalse(refusal.blocking)
        self.assertEqual(refusal.evidence, (evidence,))

    def test_two_eligible_subjects_refuse_explicit_selection_of_either(self):
        for generation, test, evidence, _ in GENERATIONS:
            turtle = (
                PREFIXES
                + PUBLICATION
                + test
                + '<urn:other> a dcat:Dataset ; dct:title "Other" .'
            )
            for term in ("urn:publication", "urn:other"):
                with self.subTest(generation=generation, term=term):
                    self.assert_refused(harvest(turtle, subject=term), term, evidence)
                    self.assert_refused(
                        harvest(turtle).select_subject(term), term, evidence
                    )

    def test_two_eligible_subjects_leave_automatic_selection_unselected(self):
        result = harvest(
            PREFIXES
            + PUBLICATION
            + TENSILE_TEST_2
            + '<urn:other> a dcat:Dataset ; dct:title "Other" .'
        ).select_subject_automatically()
        self.assertIsNone(result.subject)
        self.assertEqual(codes(result), ["subject_ambiguous"])
        self.assertEqual(offered(result), ([], []))

    def test_explicitly_selected_non_eligible_subjects_are_refused(self):
        for generation, test, evidence, _ in GENERATIONS:
            turtle = (
                PREFIXES
                + PUBLICATION
                + test
                + """<urn:table> a csvw:Table ; dct:title "Table" .
                <urn:resource> rdfs:label "Resource" ."""
            )
            for term in ("urn:table", "urn:resource", "urn:test"):
                with self.subTest(generation=generation, term=term):
                    self.assert_refused(harvest(turtle, subject=term), term, evidence)

    def test_subject_is_refused_when_no_subject_is_eligible(self):
        for generation, test, evidence, _ in GENERATIONS:
            with self.subTest(generation=generation):
                result = harvest(
                    PREFIXES + test + '<urn:resource> rdfs:label "Resource" .',
                    subject="urn:resource",
                )
                self.assert_refused(result, "urn:resource", evidence)

    def test_explicit_selection_of_the_sole_subject_equals_automatic(self):
        for generation, test, _, facts in GENERATIONS:
            turtle = (
                PREFIXES
                + PUBLICATION
                + test
                + facts
                + '<urn:table> a csvw:Table ; dct:title "Table" .'
            )
            automatic = harvest(turtle).select_subject_automatically()
            for route, explicit in (
                ("entry function", harvest(turtle, subject="urn:publication")),
                ("string", harvest(turtle).select_subject("urn:publication")),
                ("term", harvest(turtle).select_subject(automatic.subject.term)),
            ):
                with self.subTest(generation=generation, route=route):
                    self.assertEqual(
                        explicit.description.suggestions,
                        automatic.description.suggestions,
                    )
                    self.assertEqual(
                        explicit.keywords.suggestions, automatic.keywords.suggestions
                    )
                    self.assertEqual(len(explicit.description.suggestions), 1)
                    self.assertEqual(explicit.diagnostics, automatic.diagnostics)

    def test_refusal_does_not_block_conversion(self):
        result = harvest(
            PREFIXES
            + PUBLICATION
            + TENSILE_TEST_2
            + '<urn:table> a csvw:Table ; dct:title "Table" .',
            subject="urn:table",
        )
        reviewed = result.with_overrides(
            description="Reviewed", creators=(Person(name="Jane Doe"),)
        )
        self.assertEqual(codes(reviewed), ["pmd_subject_not_sole_candidate"])
        self.assertEqual(reviewed.to_publication_metadata().title, "Table")

    def test_same_subject_reselection_keeps_suggestions_and_review(self):
        result = selected(TENSILE_TEST_2 + MATERIAL_2)
        accepted = result.accept_suggestion(result.keywords.suggestions[0])
        for subject in ("urn:publication", accepted.subject):
            with self.subTest(subject=subject):
                again = accepted.select_subject(subject)
                self.assertEqual(offered(again), offered(result))
                self.assertEqual(again.keywords.value, ("S355", "tensile test"))
                self.assertEqual(again.keywords.origin, "acceptance")
                self.assertEqual(again.diagnostics, accepted.diagnostics)
        with self.assertRaises(ValidationError):
            accepted.select_subject("urn:test")

    def test_same_subject_reselection_keeps_a_refusal(self):
        refused = harvest(
            PREFIXES
            + PUBLICATION
            + TENSILE_TEST_2
            + '<urn:table> a csvw:Table ; dct:title "Table" .',
            subject="urn:table",
        )
        self.assert_refused(
            refused.select_subject("urn:table"), "urn:table", TEST_EVIDENCE_2
        )

    def test_anonymous_sole_subject_gets_suggestions_that_can_be_accepted(self):
        source = harvest(
            PREFIXES
            + '[] a owl:Ontology ; dct:title "Title" .'
            + TENSILE_TEST_2
            + MATERIAL_2
        )
        for route, result in (
            ("automatic", source.select_subject_automatically()),
            ("explicit", source.select_subject(source.subject_candidates[0].subject)),
        ):
            with self.subTest(route=route):
                self.assertIsInstance(result.subject.term, BNode)
                metadata = (
                    result.accept_suggestion(result.description.suggestions[0])
                    .accept_suggestion(result.keywords.suggestions[0])
                    .with_overrides(creators=(Person(name="Jane Doe"),))
                    .to_publication_metadata()
                )
                self.assertEqual(
                    metadata.description, "Data from 1 tensile test. Material: S355."
                )
                self.assertEqual(metadata.keywords, ("S355", "tensile test"))

    def test_anonymous_subject_beside_another_eligible_subject_is_refused(self):
        source = harvest(
            PREFIXES
            + PUBLICATION
            + '[] a owl:Ontology ; dct:title "Anonymous" .'
            + TENSILE_TEST_2
        )
        record = next(
            item.subject
            for item in source.subject_candidates
            if isinstance(item.subject.term, BNode)
        )
        self.assert_refused(
            source.select_subject(record), str(record.term), TEST_EVIDENCE_2
        )

    def test_explicit_selection_after_a_failed_automatic_attempt_is_refused(self):
        for generation, test, evidence, _ in GENERATIONS:
            for failure, turtle, term in (
                (
                    "subject_ambiguous",
                    PUBLICATION + '<urn:other> a dcat:Dataset ; dct:title "Other" .',
                    "urn:publication",
                ),
                (
                    "subject_candidate_missing",
                    '<urn:resource> rdfs:label "Resource" .',
                    "urn:resource",
                ),
            ):
                with self.subTest(generation=generation, failure=failure):
                    failed = harvest(
                        PREFIXES + turtle + test
                    ).select_subject_automatically()
                    self.assertEqual(codes(failed), [failure])
                    result = failed.select_subject(term)
                    self.assert_refused(result, term, evidence)
                    self.assertEqual(result.subject_origin, "selection")
                    self.assertNotIn(failure, codes(result))

    def test_absent_subject_runs_no_rule_and_stays_selectable(self):
        result = harvest(PREFIXES + PUBLICATION + TENSILE_TEST_2, subject="urn:absent")
        self.assertEqual(codes(result), ["subject_not_found"])
        self.assertEqual(
            offered(result.select_subject("urn:publication")),
            (["Data from 1 tensile test."], [("tensile test",)]),
        )


class TestPmdStableIdentity(unittest.TestCase):
    # Generation, turtle, the description it gives, and its misleading renames.
    CASES = (
        (
            "pmdco2",
            """<urn:a> a tto:TensileTest ; pmd:input <urn:piece-a> ;
                pmd:characteristic <urn:n1>, <urn:n2> .
            <urn:b> a pmd:TensileTest ; pmd:input <urn:piece-b>, <urn:piece-c> ;
                pmd:characteristic <urn:n1> .
            <urn:n1> a pmd:Norm ; pmd:value "ISO 2", " ISO 2" .
            <urn:n2> a pmd:Norm ; pmd:value "DIN 1" .
            <urn:c1> a pmd:MaterialDesignation ; pmd:value "S355", " S355 " .
            <urn:c2> a pmd:materialDesignation ; pmd:value "b-steel", "S355" .
            """,
            "Data from 2 tensile tests. Materials: b-steel, S355."
            " Test standards: DIN 1, ISO 2.",
            (
                ("urn:a>", "urn:material>"),
                ("urn:b>", "urn:norm>"),
                ("urn:n1>", "urn:tensile-test>"),
                ("urn:c1>", "urn:S420>"),
                ("urn:piece-a>", "urn:machine>"),
            ),
        ),
        (
            "pmdco3",
            TENSILE_TEST_3
            + MATERIAL_3
            + STANDARD_3
            + """<urn:other> a pmd:PMD_0000974 ; obo:OBI_0000293 <urn:piece> ;
                obo:BFO_0000055 <urn:method> .
            <urn:id> obo:OBI_0001938 <urn:spec2> .
            <urn:spec2> pmd:PMD_0000006 " S355 ", "b-steel" .
            """,
            "Data from 2 tensile tests. Materials: b-steel, S355."
            " Test standard: DIN EN ISO 6892-1.",
            (
                ("urn:test>", "urn:machine>"),
                ("urn:steel>", "urn:aluminium>"),
                ("urn:id>", "urn:label>"),
                ("urn:method>", "urn:material>"),
            ),
        ),
    )

    def test_results_are_invariant_under_triple_reordering(self):
        for generation, turtle, description, _ in self.CASES:
            with self.subTest(generation=generation):
                graph = Graph().parse(
                    data=PREFIXES + PUBLICATION + turtle, format="turtle"
                )
                reversed_graph = Graph()
                for triple in reversed(sorted(graph, key=str)):
                    reversed_graph.add(triple)
                first, second = (
                    harvest(item).select_subject_automatically()
                    for item in (graph, reversed_graph)
                )
                self.assertEqual(
                    first.description.suggestions, second.description.suggestions
                )
                self.assertEqual(
                    first.keywords.suggestions, second.keywords.suggestions
                )
                self.assertEqual(first.diagnostics, second.diagnostics)
                self.assertEqual(first.description.suggestions[0].value, description)

    def test_changing_instance_identifiers_changes_no_value(self):
        for generation, turtle, description, renames in self.CASES:
            with self.subTest(generation=generation):
                renamed = turtle
                for old, new in renames:
                    self.assertIn(old, renamed)
                    renamed = renamed.replace(old, new)
                first, second = selected(turtle), selected(renamed)
                self.assertEqual(offered(first), offered(second))
                self.assertEqual(offered(second)[0], [description])
                self.assertEqual(
                    [item.rule for item in first.description.suggestions[0].evidence],
                    [item.rule for item in second.description.suggestions[0].evidence],
                )


class TestPmdKeywordAcceptance(unittest.TestCase):
    OBSERVED = '<urn:publication> dcat:keyword "steel" .'

    def test_accepting_replaces_active_keywords_and_keeps_observed_candidates(self):
        result = selected(self.OBSERVED + TENSILE_TEST_2 + MATERIAL_2)
        before = result.keywords
        suggestion = before.suggestions[0]

        accepted = result.accept_suggestion(suggestion).keywords

        self.assertEqual(accepted.value, ("S355", "tensile test"))
        self.assertEqual(accepted.status, "resolved")
        self.assertEqual(accepted.origin, "acceptance")
        self.assertIs(accepted.selection, suggestion)
        self.assertEqual(accepted.candidates, before.candidates)
        self.assertEqual(accepted.observations, before.observations)
        self.assertEqual(accepted.suggestions, before.suggestions)

    def test_acceptance_leaves_the_original_harvest_unchanged(self):
        result = selected(self.OBSERVED + TENSILE_TEST_2)
        before = result.keywords
        result.accept_suggestion(before.suggestions[0])
        self.assertEqual(result.keywords, before)
        self.assertEqual(result.keywords.value, ("steel",))
        self.assertEqual(result.keywords.origin, "automatic")

    def test_accepting_resolves_keywords_that_block_conversion(self):
        result = selected(
            '<urn:publication> dcat:keyword "steel", <urn:concept> ;'
            ' dct:description "Observed" ; dct:creator "Jane Doe" .' + TENSILE_TEST_2
        )
        self.assertEqual(result.keywords.status, "unresolved")
        self.assertEqual(
            [(item.code, item.field) for item in result.diagnostics if item.blocking],
            [("unresolved_field", "keywords")],
        )
        accepted = result.accept_suggestion(result.keywords.suggestions[0])
        self.assertEqual(accepted.to_publication_metadata().keywords, ("tensile test",))

    def test_clearing_accepted_keywords_allows_re_acceptance(self):
        result = selected(self.OBSERVED + TENSILE_TEST_2 + MATERIAL_2)
        before = result.keywords
        suggestion = before.suggestions[0]

        cleared = result.accept_suggestion(suggestion).clear("keywords")

        self.assertEqual(cleared.keywords.value, ())
        self.assertEqual(cleared.keywords.status, "excluded")
        self.assertEqual(cleared.keywords.origin, "exclusion")
        self.assertIsNone(cleared.keywords.selection)
        self.assertEqual(cleared.keywords.suggestions, (suggestion,))
        self.assertEqual(cleared.keywords.candidates, before.candidates)
        self.assertEqual(cleared.keywords.observations, before.observations)
        reviewed = cleared.with_overrides(
            description="Reviewed", creators=(Person(name="Jane Doe"),)
        )
        self.assertEqual(reviewed.to_publication_metadata().keywords, ())

        again = cleared.accept_suggestion(suggestion).keywords

        self.assertEqual(again.value, ("S355", "tensile test"))
        self.assertEqual(again.status, "resolved")
        self.assertEqual(again.origin, "acceptance")
        self.assertIs(again.selection, suggestion)

    def test_reviewed_copy_accepts_and_a_later_override_replaces(self):
        result = selected(TENSILE_TEST_2)
        suggestion = result.keywords.suggestions[0]
        accepted = result.with_overrides(version="1").accept_suggestion(suggestion)
        self.assertEqual(accepted.keywords.origin, "acceptance")
        overridden = accepted.with_overrides(keywords=("reviewed",))
        self.assertEqual(overridden.keywords.origin, "override")
        self.assertIsNone(overridden.keywords.selection)
        self.assertEqual(overridden.keywords.suggestions, (suggestion,))

    def test_other_collection_fields_stay_rejected(self):
        result = selected(TENSILE_TEST_2)
        suggestion = result.keywords.suggestions[0]
        for name in ("creators", "contributors", "related_identifiers"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                result.accept_suggestion(replace(suggestion, field=name))
        self.assertEqual(result.keywords.status, "missing")

    def test_records_not_offered_by_this_harvest_are_rejected(self):
        result = selected(TENSILE_TEST_2)
        suggestion = result.keywords.suggestions[0]
        for item in (
            selected(TENSILE_TEST_2).keywords.suggestions[0],
            replace(suggestion),
            Suggestion("keywords", ("invented",), ()),
            ("tensile test",),
        ):
            with self.subTest(item=item), self.assertRaises(ValidationError):
                result.accept_suggestion(item)
        self.assertEqual(result.keywords.status, "missing")

    def test_record_of_another_subject_is_rejected(self):
        source = harvest(PREFIXES + PUBLICATION + TENSILE_TEST_2)
        suggestion = source.select_subject("urn:publication").keywords.suggestions[0]
        other = source.select_subject("urn:test")
        with self.assertRaises(ValidationError):
            other.accept_suggestion(suggestion)
        self.assertEqual(other.keywords.status, "missing")

    def test_unselected_harvest_rejects_a_record(self):
        source = harvest(PREFIXES + PUBLICATION + TENSILE_TEST_2)
        suggestion = source.select_subject_automatically().keywords.suggestions[0]
        with self.assertRaises(ValidationError):
            source.accept_suggestion(suggestion)


class TestPmdco3TensileTestRule(unittest.TestCase):
    def test_typed_resource_with_an_input_gives_a_test_with_exact_evidence(self):
        result = selected(TENSILE_TEST_3)
        self.assertEqual(
            offered(result),
            (["Data from 1 tensile test."], [("tensile test",)]),
        )
        self.assertEqual(result.description.suggestions[0].evidence, (TEST_EVIDENCE_3,))
        self.assertEqual(result.keywords.suggestions[0].evidence, (TEST_EVIDENCE_3,))

    def test_similar_test_class_iris_do_not_match(self):
        for rdf_type in (
            "https://w3id.org/pmd/co/pmd_0000974",
            "https://w3id.org/pmd/tto/PMD_0000974",
            "http://purl.obolibrary.org/obo/PMD_0000974",
            "https://w3id.org/pmd/co/PMD_0000975",
            "https://w3id.org/pmd/co/TensileTest",
        ):
            with self.subTest(rdf_type=rdf_type):
                result = selected(
                    f"<urn:test> a <{rdf_type}> ; obo:OBI_0000293 <urn:piece> ."
                )
                self.assertEqual(offered(result), ([], []))
                self.assertEqual(result.diagnostics, selected("").diagnostics)

    def test_similar_input_predicates_do_not_match(self):
        for predicate in (
            "http://purl.obolibrary.org/obo/obi_0000293",
            "http://purl.obolibrary.org/obo/OBI_0000299",
            "https://w3id.org/pmd/co/OBI_0000293",
            "https://w3id.org/pmd/co/input",
        ):
            with self.subTest(predicate=predicate):
                result = selected(
                    f"<urn:test> a pmd:PMD_0000974 ; <{predicate}> <urn:piece> ."
                )
                self.assertEqual(offered(result), ([], []))

    def test_test_without_an_input_is_not_a_signature(self):
        result = selected("<urn:step> a pmd:PMD_0000974 ." + MATERIAL_3)
        self.assertEqual(offered(result), ([], []))
        self.assertEqual(result.diagnostics, selected("").diagnostics)

    def test_count_excludes_sub_steps_and_is_plural_for_several_tests(self):
        result = selected(
            TENSILE_TEST_3
            + """<urn:other> a pmd:PMD_0000974 ; obo:OBI_0000293 <urn:piece> .
            <urn:step> a pmd:PMD_0000974 ."""
        )
        self.assertEqual(offered(result)[0], ["Data from 2 tensile tests."])


class TestPmdco3MaterialRule(unittest.TestCase):
    def test_identifier_of_a_steel_individual_gives_the_fact_with_exact_evidence(self):
        result = selected(TENSILE_TEST_3 + MATERIAL_3)
        self.assertEqual(
            offered(result),
            (
                ["Data from 1 tensile test. Material: S355."],
                [("S355", "tensile test")],
            ),
        )
        expected = (
            TEST_EVIDENCE_3,
            Evidence(
                "pmdco3_material",
                (
                    (
                        "<urn:id>",
                        "<http://purl.obolibrary.org/obo/IAO_0000219>",
                        "<urn:steel>",
                    ),
                    (
                        "<urn:id>",
                        "<http://purl.obolibrary.org/obo/OBI_0001938>",
                        "<urn:spec>",
                    ),
                    (
                        "<urn:spec>",
                        "<https://w3id.org/pmd/co/PMD_0000006>",
                        '"S355"',
                    ),
                    ("<urn:steel>", RDF_TYPE, "<https://w3id.org/pmd/co/PMD_0020096>"),
                ),
            ),
        )
        self.assertEqual(result.description.suggestions[0].evidence, expected)
        self.assertEqual(result.keywords.suggestions[0].evidence, expected)

    def test_removing_a_required_triple_drops_the_sentence(self):
        for removed in (
            "<urn:id> obo:IAO_0000219 <urn:steel> .",
            "<urn:steel> a pmd:PMD_0020096 .",
            "<urn:id> obo:OBI_0001938 <urn:spec> .",
            '<urn:spec> pmd:PMD_0000006 "S355" .',
        ):
            with self.subTest(removed=removed):
                self.assertIn(removed, MATERIAL_3)
                result = selected(TENSILE_TEST_3 + MATERIAL_3.replace(removed, ""))
                self.assertEqual(
                    offered(result),
                    (["Data from 1 tensile test."], [("tensile test",)]),
                )
                self.assertEqual(
                    result.description.suggestions[0].evidence, (TEST_EVIDENCE_3,)
                )

    def test_similar_terms_do_not_match(self):
        for old, new in (
            ("pmd:PMD_0020096", "<https://w3id.org/pmd/co/pmd_0020096>"),
            ("pmd:PMD_0020096", "<https://w3id.org/pmd/tto/PMD_0020096>"),
            ("obo:IAO_0000219", "<http://purl.obolibrary.org/obo/iao_0000219>"),
            ("obo:IAO_0000219", "<https://w3id.org/pmd/co/IAO_0000219>"),
            ("obo:OBI_0001938", "<http://purl.obolibrary.org/obo/obi_0001938>"),
            ("obo:OBI_0001938", "<https://w3id.org/pmd/co/OBI_0001938>"),
            ("pmd:PMD_0000006", "<https://w3id.org/pmd/co/pmd_0000006>"),
            ("pmd:PMD_0000006", "<https://w3id.org/pmd/tto/PMD_0000006>"),
            ("pmd:PMD_0000006", "<https://w3id.org/pmd/co/value>"),
        ):
            with self.subTest(old=old, new=new):
                self.assertIn(old, MATERIAL_3)
                result = selected(TENSILE_TEST_3 + MATERIAL_3.replace(old, new))
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_value_on_an_identifier_of_a_non_steel_individual_does_not_match(self):
        result = selected(
            TENSILE_TEST_3
            + MATERIAL_3.replace(
                "<urn:steel> a pmd:PMD_0020096 .",
                "<urn:steel> a <https://w3id.org/pmd/co/PMD_0020097> ;"
                ' rdfs:label "steel" .',
            )
        )
        self.assertEqual(
            offered(result), (["Data from 1 tensile test."], [("tensile test",)])
        )

    def test_porosity_link_from_a_test_piece_does_not_make_a_material(self):
        result = selected(TENSILE_TEST_3 + """<urn:piece> pmd:PMD_0020005 <urn:other> .
            <urn:id> obo:IAO_0000219 <urn:other> ; obo:OBI_0001938 <urn:spec> .
            <urn:spec> pmd:PMD_0000006 "S355" .""")
        self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_label_or_identifier_saying_material_is_not_a_fact(self):
        result = selected(
            TENSILE_TEST_3
            + """<urn:material> rdfs:label "material" ; pmd:PMD_0000006 "S355" ;
                a <https://w3id.org/pmd/co/PMD_0000000> ."""
        )
        self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_material_values_are_trimmed_merged_and_sorted(self):
        result = selected(
            TENSILE_TEST_3 + MATERIAL_3 + """<urn:id> obo:OBI_0001938 <urn:spec2> .
            <urn:spec2> pmd:PMD_0000006 " S355 ", "b-steel", "  ", <urn:v>, [] ."""
        )
        self.assertEqual(
            offered(result),
            (
                ["Data from 1 tensile test. Materials: b-steel, S355."],
                [("b-steel", "S355", "tensile test")],
            ),
        )
        triples = result.keywords.suggestions[0].evidence[1].triples
        self.assertEqual(
            [item[2] for item in triples if item[0] == "<urn:spec2>"],
            ['" S355 "', '"b-steel"'],
        )


class TestPmdco3TestStandardRule(unittest.TestCase):
    def test_method_realized_by_a_test_gives_the_fact_with_exact_evidence(self):
        result = selected(TENSILE_TEST_3 + STANDARD_3)
        suggestion = result.description.suggestions[0]
        self.assertEqual(
            suggestion.value,
            "Data from 1 tensile test. Test standard: DIN EN ISO 6892-1.",
        )
        self.assertEqual(
            suggestion.evidence,
            (
                TEST_EVIDENCE_3,
                Evidence(
                    "pmdco3_test_standard",
                    (
                        (
                            "<urn:method-id>",
                            "<http://purl.obolibrary.org/obo/IAO_0000219>",
                            "<urn:method>",
                        ),
                        (
                            "<urn:method-id>",
                            "<http://purl.obolibrary.org/obo/OBI_0001938>",
                            "<urn:method-spec>",
                        ),
                        (
                            "<urn:method-spec>",
                            "<https://w3id.org/pmd/co/PMD_0000006>",
                            '"DIN EN ISO 6892-1"',
                        ),
                        (
                            "<urn:method>",
                            RDF_TYPE,
                            "<https://w3id.org/pmd/tto/TTO_0000054>",
                        ),
                        (
                            "<urn:test>",
                            "<http://purl.obolibrary.org/obo/BFO_0000055>",
                            "<urn:method>",
                        ),
                    ),
                ),
            ),
        )

    def test_standard_is_not_a_keyword(self):
        result = selected(TENSILE_TEST_3 + STANDARD_3)
        self.assertEqual(offered(result)[1], [("tensile test",)])
        self.assertEqual(result.keywords.suggestions[0].evidence, (TEST_EVIDENCE_3,))

    def test_removing_a_required_triple_drops_the_sentence(self):
        for removed in (
            "<urn:test> obo:BFO_0000055 <urn:method> .",
            "<urn:method> a tto:TTO_0000054 .",
            "<urn:method-id> obo:IAO_0000219 <urn:method> .",
            "<urn:method-id> obo:OBI_0001938 <urn:method-spec> .",
            '<urn:method-spec> pmd:PMD_0000006 "DIN EN ISO 6892-1" .',
        ):
            with self.subTest(removed=removed):
                self.assertIn(removed, STANDARD_3)
                result = selected(TENSILE_TEST_3 + STANDARD_3.replace(removed, ""))
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])
                self.assertEqual(
                    result.description.suggestions[0].evidence, (TEST_EVIDENCE_3,)
                )

    def test_similar_terms_do_not_match(self):
        for old, new in (
            ("obo:BFO_0000055", "<http://purl.obolibrary.org/obo/bfo_0000055>"),
            ("obo:BFO_0000055", "<https://w3id.org/pmd/co/BFO_0000055>"),
            ("tto:TTO_0000054", "<https://w3id.org/pmd/tto/tto_0000054>"),
            ("tto:TTO_0000054", "<https://w3id.org/pmd/co/TTO_0000054>"),
            ("tto:TTO_0000054", "pmd:Norm"),
            ("obo:IAO_0000219", "<http://purl.obolibrary.org/obo/iao_0000219>"),
            ("obo:IAO_0000219", "<https://w3id.org/pmd/co/IAO_0000219>"),
            ("obo:OBI_0001938", "<http://purl.obolibrary.org/obo/obi_0001938>"),
            ("obo:OBI_0001938", "<https://w3id.org/pmd/co/OBI_0001938>"),
            ("pmd:PMD_0000006", "<https://w3id.org/pmd/co/pmd_0000006>"),
            ("pmd:PMD_0000006", "<https://w3id.org/pmd/tto/PMD_0000006>"),
            ("pmd:PMD_0000006", "<https://w3id.org/pmd/co/value>"),
        ):
            with self.subTest(old=old, new=new):
                self.assertIn(old, STANDARD_3)
                result = selected(TENSILE_TEST_3 + STANDARD_3.replace(old, new))
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_methods_outside_a_counted_test_do_not_match(self):
        for owner in (
            "<urn:machine> a <https://w3id.org/pmd/co/PMD_0000001> ;",
            "<urn:extensometer> a <https://w3id.org/pmd/co/PMD_0000002> ;",
            "<urn:step> a pmd:PMD_0000974 ;",
        ):
            with self.subTest(owner=owner):
                result = selected(
                    TENSILE_TEST_3
                    + owner
                    + " obo:BFO_0000055 <urn:method> ."
                    + STANDARD_3.replace(
                        "<urn:test> obo:BFO_0000055 <urn:method> .", ""
                    )
                )
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_invalid_values_drop_the_sentence(self):
        for value in ('""', '"  "', "<urn:value>", "[]"):
            with self.subTest(value=value):
                result = selected(
                    TENSILE_TEST_3 + STANDARD_3.replace('"DIN EN ISO 6892-1"', value)
                )
                self.assertEqual(offered(result)[0], ["Data from 1 tensile test."])

    def test_several_standards_are_listed_sorted(self):
        result = selected(
            TENSILE_TEST_3
            + STANDARD_3
            + """<urn:other-id> obo:IAO_0000219 <urn:method> ;
                obo:OBI_0001938 <urn:other-spec> .
            <urn:other-spec> pmd:PMD_0000006 "ASTM E8" ."""
        )
        self.assertEqual(
            offered(result)[0],
            [
                "Data from 1 tensile test."
                " Test standards: ASTM E8, DIN EN ISO 6892-1."
            ],
        )


class TestPmdGenerations(unittest.TestCase):
    def test_both_generations_give_a_non_blocking_conflict(self):
        result = selected(
            TENSILE_TEST_2 + MATERIAL_2 + STANDARD_2 + TENSILE_TEST_3 + MATERIAL_3
        )
        self.assertEqual(offered(result), ([], []))
        conflict = result.diagnostics[-1]
        self.assertEqual(conflict.code, "pmd_generation_conflict")
        self.assertIsNone(conflict.field)
        self.assertEqual(str(conflict.subject), "urn:publication")
        self.assertFalse(conflict.blocking)
        self.assertEqual(
            [item.rule for item in conflict.evidence],
            ["pmdco2_tensile_test", "pmdco3_tensile_test"],
        )
        self.assertNotIn("pmd_subject_not_sole_candidate", codes(result))

    def test_conflict_leaves_generic_extraction_and_conversion_usable(self):
        result = selected(
            '<urn:publication> dct:description "Observed" ; dct:creator "Jane Doe" .'
            + TENSILE_TEST_2
            + TENSILE_TEST_3
        )
        self.assertEqual(result.title.value, "Title")
        self.assertEqual(result.description.value, "Observed")
        self.assertEqual(codes(result), ["pmd_generation_conflict"])
        self.assertEqual(result.to_publication_metadata().description, "Observed")

    def test_conflict_on_a_non_sole_subject_reports_both_conditions(self):
        result = harvest(
            PREFIXES
            + PUBLICATION
            + TENSILE_TEST_2
            + TENSILE_TEST_3
            + '<urn:table> a csvw:Table ; dct:title "Table" .',
            subject="urn:table",
        )
        self.assertEqual(offered(result), ([], []))
        pmd = [item for item in result.diagnostics if item.code.startswith("pmd_")]
        self.assertEqual(
            [item.code for item in pmd],
            ["pmd_generation_conflict", "pmd_subject_not_sole_candidate"],
        )
        for item in pmd:
            with self.subTest(code=item.code):
                self.assertEqual(
                    [evidence.rule for evidence in item.evidence],
                    ["pmdco2_tensile_test", "pmdco3_tensile_test"],
                )

    def test_other_generations_facts_do_not_apply_without_its_test(self):
        for turtle, rule in (
            (TENSILE_TEST_3 + MATERIAL_2, "pmdco3_tensile_test"),
            (TENSILE_TEST_2 + MATERIAL_3, "pmdco2_tensile_test"),
        ):
            with self.subTest(rule=rule):
                result = selected(turtle)
                self.assertEqual(
                    offered(result),
                    (["Data from 1 tensile test."], [("tensile test",)]),
                )
                self.assertEqual(
                    [item.rule for item in result.description.suggestions[0].evidence],
                    [rule],
                )
                self.assertEqual(result.diagnostics, selected("").diagnostics)
