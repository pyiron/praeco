import unittest
from dataclasses import replace
from datetime import date

from rdflib import XSD, Graph, Literal, URIRef

from praeco.exceptions import ValidationError
from praeco.rdf_metadata import IncompleteHarvestError, Suggestion
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest

PREFIXES = """
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix schema: <https://schema.org/> .
@prefix oldschema: <http://schema.org/> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<urn:s> dct:title "Title"; dct:description "Description"; dct:creator "Jane" .
"""


class TestGenericDates(unittest.TestCase):
    def test_direct_date_aliases_and_normalization_keep_all_support(self):
        result = harvest(
            PREFIXES + """
            <urn:s> dct:issued "2021-02-03"^^xsd:date;
                schema:datePublished "2021-02-03T23:00:00-05:00"^^xsd:dateTime;
                oldschema:datePublished "2021-02-03Z"^^xsd:date .
        """,
            subject="urn:s",
        )
        review = result.publication_date
        self.assertEqual(review.value, date(2021, 2, 3))
        self.assertEqual(len(review.candidates), 1)
        self.assertEqual(len(review.selection.evidence), 3)
        self.assertEqual(
            result.to_publication_metadata().publication_date, review.value
        )

    def test_complete_untyped_and_timezone_dates(self):
        for obj in (
            '"2021-02-03"',
            '"2021-02-03T23:15:00+02:00"',
            '"2021-02-03+02:00"^^xsd:date',
            '"2021-02-03"^^xsd:string',
        ):
            with self.subTest(obj=obj):
                result = harvest(
                    PREFIXES + f"<urn:s> dct:issued {obj}.", subject="urn:s"
                )
                self.assertEqual(
                    result.to_publication_metadata().publication_date, date(2021, 2, 3)
                )

    def test_creation_and_generic_dates_require_acceptance(self):
        for predicate in (
            "dct:created",
            "schema:dateCreated",
            "oldschema:dateCreated",
            "dc:date",
            "dct:date",
        ):
            with self.subTest(predicate=predicate):
                result = harvest(
                    PREFIXES + f'<urn:s> {predicate} "2020-01-02".', subject="urn:s"
                )
                self.assertEqual(result.publication_date.status, "missing")
                self.assertIsNone(result.to_publication_metadata().publication_date)
                suggestion = result.publication_date.suggestions[0]
                self.assertIn("2020-01-02", suggestion.evidence[0].triples[0][2])
                accepted = result.with_overrides(version="1").accept_suggestion(
                    suggestion
                )
                self.assertEqual(accepted.publication_date.origin, "acceptance")
                self.assertIs(accepted.publication_date.selection, suggestion)
                self.assertEqual(
                    accepted.to_publication_metadata().publication_date,
                    date(2020, 1, 2),
                )
                self.assertEqual(
                    accepted.publication_date.observations,
                    result.publication_date.observations,
                )
                overridden = accepted.with_overrides(publication_date=date(2020, 1, 2))
                self.assertEqual(overridden.publication_date.origin, "override")
                self.assertIsNone(overridden.publication_date.selection)

    def test_publication_date_does_not_erase_weaker_suggestions(self):
        result = harvest(
            PREFIXES + """<urn:s> dct:issued "2021-02-03";
            dct:created "2020-01-02"; schema:dateCreated "2020-01-02T12:00:00";
            dc:date "2019" .""",
            subject="urn:s",
        )
        self.assertEqual(result.publication_date.value, date(2021, 2, 3))
        self.assertEqual(len(result.publication_date.suggestions), 1)
        self.assertEqual(len(result.publication_date.suggestions[0].evidence), 2)
        self.assertEqual(len(result.publication_date.observations), 4)

    def test_conflicting_optional_date_requires_resolution_or_exclusion(self):
        result = harvest(
            PREFIXES + '<urn:s> dct:issued "2020-01-01", "2021-01-01".', subject="urn:s"
        )
        self.assertEqual(result.publication_date.status, "unresolved")
        with self.assertRaises(IncompleteHarvestError):
            result.to_publication_metadata()
        selected = result.select_candidate(result.publication_date.candidates[1])
        self.assertEqual(
            selected.to_publication_metadata().publication_date, date(2021, 1, 1)
        )
        excluded = result.clear("publication_date")
        self.assertIsNone(excluded.to_publication_metadata().publication_date)
        self.assertEqual(
            excluded.publication_date.observations, result.publication_date.observations
        )
        self.assertEqual(excluded.publication_date.origin, "exclusion")

    def test_invalid_and_year_only_dates_never_invent_calendar_dates(self):
        for obj in (
            '"2020"',
            '"2020"^^xsd:gYear',
            '"2020-02-30"',
            '"2020-W01-1"',
            "<urn:date>",
            "[]",
        ):
            with self.subTest(obj=obj):
                result = harvest(
                    PREFIXES + f"<urn:s> dct:issued {obj}; dct:created {obj}.",
                    subject="urn:s",
                )
                self.assertEqual(result.publication_date.status, "unresolved")
                self.assertEqual(result.publication_date.candidates, ())
                self.assertEqual(result.publication_date.suggestions, ())
                with self.assertRaises(IncompleteHarvestError):
                    result.to_publication_metadata()
                self.assertIsNone(
                    result.clear("publication_date")
                    .to_publication_metadata()
                    .publication_date
                )
        with self.assertLogs("rdflib.term", level="WARNING"):
            invalid = Literal("not-a-date", datatype=XSD.date, normalize=False)
        graph = Graph().parse(data=PREFIXES, format="turtle")
        graph.add((URIRef("urn:s"), URIRef("http://purl.org/dc/terms/issued"), invalid))
        result = harvest(graph, subject="urn:s")
        self.assertEqual(result.publication_date.status, "unresolved")
        self.assertIn(
            "not-a-date", result.publication_date.observations[0].triples[0][2]
        )

    def test_suggestions_are_bound_to_retained_source_and_subject(self):
        text = (
            PREFIXES
            + '<urn:s> dct:created "2020-01-01". <urn:other> dct:created "2020-01-01".'
        )
        source = harvest(text)
        result = source.select_subject("urn:s")
        suggestion = result.publication_date.suggestions[0]
        invalid = (
            harvest(text, subject="urn:s").publication_date.suggestions[0],
            source.select_subject("urn:other").publication_date.suggestions[0],
            replace(suggestion),
            replace(suggestion, field="keywords"),
            replace(suggestion, field="unknown"),
            Suggestion("title", "Invented", ()),
            "2020-01-01",
        )
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValidationError):
                result.accept_suggestion(item)
        with self.assertRaises(ValidationError):
            source.accept_suggestion(suggestion)
        with self.assertRaises(ValidationError):
            result.select_candidate(suggestion)
        self.assertEqual(result.publication_date.origin, None)


class TestOtherGenericFields(unittest.TestCase):
    def test_license_literal_and_resource_aliases_keep_neutral_values(self):
        result = harvest(
            PREFIXES + """<urn:s> dct:license <https://example.org/license>;
            schema:license " https://example.org/license ";
            oldschema:license "https://example.org/license".""",
            subject="urn:s",
        )
        self.assertEqual(
            result.to_publication_metadata().license, "https://example.org/license"
        )
        self.assertEqual(len(result.license.selection.evidence), 3)
        conflict = harvest(
            PREFIXES + '<urn:s> dct:license "CC-BY-4.0", "MIT".', subject="urn:s"
        )
        with self.assertRaises(IncompleteHarvestError):
            conflict.to_publication_metadata()
        self.assertEqual(
            conflict.select_candidate(conflict.license.candidates[0])
            .to_publication_metadata()
            .license,
            "CC-BY-4.0",
        )
        for obj in ("[]", '" "'):
            with self.subTest(obj=obj):
                invalid = harvest(
                    PREFIXES + f"<urn:s> dct:license {obj}.", subject="urn:s"
                )
                self.assertEqual(invalid.license.status, "unresolved")
                self.assertIsNone(
                    invalid.clear("license").to_publication_metadata().license
                )

    def test_recognized_doi_forms_merge_and_ordinary_identifiers_stay_visible(self):
        result = harvest(
            PREFIXES
            + """<urn:s> dct:identifier "10.1234/ABC", "doi:10.1234/abc", "internal-42";
            schema:identifier <https://doi.org/10.1234/abc>;
            oldschema:identifier <http://dx.doi.org/10.1234/abc>.""",
            subject="urn:s",
        )
        self.assertEqual(result.to_publication_metadata().doi, "10.1234/abc")
        self.assertEqual(len(result.doi.selection.evidence), 4)
        self.assertEqual(len(result.doi.observations), 5)
        self.assertEqual(
            [(d.code, d.blocking) for d in result.diagnostics],
            [("unmapped_identifier", False)],
        )
        for obj in (
            '"internal-42"',
            "<https://example.org/10.1234/abc>",
            "[]",
            '" "',
            '"10.1234/abc def"',
        ):
            with self.subTest(obj=obj):
                ordinary = harvest(
                    PREFIXES + f"<urn:s> dct:identifier {obj}.", subject="urn:s"
                )
                self.assertEqual(ordinary.doi.status, "missing")
                self.assertIsNone(ordinary.to_publication_metadata().doi)
                self.assertEqual(len(ordinary.doi.observations), 1)

    def test_keywords_collect_all_languages_without_splitting_strings(self):
        result = harvest(
            PREFIXES + """<urn:s> dct:subject " steel "@en;
            dcat:keyword "steel"; schema:keywords "steel"@de, "stress, strain";
            oldschema:keywords "testing".""",
            subject="urn:s",
            preferred_languages=("en",),
        )
        self.assertEqual(
            result.to_publication_metadata().keywords,
            ("steel", "stress, strain", "testing"),
        )
        self.assertEqual(len(result.keywords.selection.evidence), 5)
        with self.assertRaises(ValidationError):
            result.select_candidate(result.keywords.candidates[0])
        invalid = harvest(
            PREFIXES + '<urn:s> dcat:keyword "steel", <urn:concept>.', subject="urn:s"
        )
        self.assertEqual(invalid.keywords.status, "unresolved")
        self.assertEqual(invalid.keywords.candidates[0].value, ("steel",))
        self.assertEqual(len(invalid.keywords.candidates[0].evidence), 1)
        self.assertEqual(len(invalid.keywords.observations), 2)
        with self.assertRaises(IncompleteHarvestError):
            invalid.to_publication_metadata()
        self.assertEqual(
            invalid.with_overrides(keywords=("steel",))
            .to_publication_metadata()
            .keywords,
            ("steel",),
        )

    def test_language_aliases_preserve_codes_and_defer_resource_values(self):
        for predicate in (
            "dc:language",
            "dct:language",
            "schema:inLanguage",
            "oldschema:inLanguage",
        ):
            with self.subTest(predicate=predicate):
                result = harvest(
                    PREFIXES + f'<urn:s> {predicate} "de-DE".', subject="urn:s"
                )
                self.assertEqual(result.to_publication_metadata().language, "de-DE")
        invalid = harvest(PREFIXES + "<urn:s> dct:language <urn:de>.", subject="urn:s")
        self.assertEqual(invalid.language.status, "unresolved")
        self.assertEqual(
            invalid.with_overrides(language="de").to_publication_metadata().language,
            "de",
        )

    def test_generic_review_is_invariant_under_statement_order(self):
        graph = Graph().parse(
            data=PREFIXES + """<urn:s> dct:issued "2020-01-01", "2021-01-01";
            dct:created "2019-01-01"; dcat:keyword "a", "b";
            dct:identifier "other", "10.1234/ABC"; dct:license "MIT", "CC-BY".""",
            format="turtle",
        )
        reverse = Graph()
        for triple in reversed(sorted(graph, key=str)):
            reverse.add(triple)
        first, second = (harvest(g, subject="urn:s") for g in (graph, reverse))
        for field in ("publication_date", "keywords", "doi", "license", "language"):
            self.assertEqual(getattr(first, field), getattr(second, field))
        self.assertEqual(first.diagnostics, second.diagnostics)
