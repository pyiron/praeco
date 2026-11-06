import unittest
from datetime import date
from pathlib import Path

from rdflib import URIRef

from praeco import Person, harvest_publication_metadata_from_rdf
from praeco.rdf_metadata import IncompleteHarvestError

CORPUS = Path(__file__).parents[2] / "resources/rdf_metadata/corpus"
DC_CREATOR = "<http://purl.org/dc/elements/1.1/creator>"
RDFS_LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
REVIEWED_CREATORS = (Person(name="Jane Doe"),)


class TestPmdReferenceCorpus(unittest.TestCase):
    """Harvesting of the PMD reference files, with the exact PMD rules applied."""

    def test_pmdco2_example_keeps_its_creator_identities_unresolved(self):
        subject = URIRef("https://w3id.org/pmd/ao/tte/")
        harvest = harvest_publication_metadata_from_rdf(
            CORPUS / "pmdco2_tto_example.ttl"
        ).select_subject_automatically()

        self.assertEqual(
            [candidate.subject.term for candidate in harvest.subject_candidates],
            [subject],
        )
        self.assertEqual(harvest.subject, harvest.subject_candidates[0].subject)
        self.assertEqual(harvest.subject_origin, "automatic")
        self.assertEqual(
            harvest.title.value, "Tensile Test Ontology (TTO) data mapping example"
        )
        self.assertEqual(harvest.description.status, "missing")
        self.assertEqual(harvest.publication_date.status, "missing")
        self.assertEqual(harvest.publication_date.suggestions, ())

        creators = harvest.creators
        self.assertEqual(creators.status, "unresolved")
        orcids = [
            "https://orcid.org/0000-0001-7192-7143",
            "https://orcid.org/0000-0002-3717-7104",
            "https://orcid.org/0000-0002-7094-5371",
            "https://orcid.org/0000-0003-4971-3645",
        ]
        self.assertCountEqual(
            [observation.orcid for observation in creators.observations], orcids
        )
        for observation in creators.observations:
            with self.subTest(orcid=observation.orcid):
                self.assertEqual(observation.kind, "unknown")
                self.assertIsNone(observation.name)
                self.assertEqual(observation.relations, ("creator",))
                self.assertIn(
                    (subject.n3(), DC_CREATOR, f"<{observation.orcid}>"),
                    [t for item in observation.evidence for t in item.triples],
                )
        conflicting = {item.orcid: item for item in creators.observations}[orcids[1]]
        names = [
            "Bernd Bayerlein",
            "Jörg Waitelonis",
            "Markus Schilling",
            "Philipp von Hartrott",
        ]
        self.assertCountEqual(
            [
                (candidate.value, candidate.evidence[0].triples)
                for candidate in conflicting.name_candidates
            ],
            [(name, ((f"<{orcids[1]}>", RDFS_LABEL, f'"{name}"'),)) for name in names],
        )
        self.assertCountEqual(
            [
                observation.orcid
                for observation in creators.observations
                if not observation.name_candidates
            ],
            [orcids[0], orcids[2], orcids[3]],
        )

        with self.assertRaises(IncompleteHarvestError) as caught:
            harvest.to_publication_metadata()
        self.assertCountEqual(
            [(item.code, item.field) for item in caught.exception.diagnostics],
            [("missing_required", "description")]
            + [("unresolved_creator", "creators")] * 4,
        )

        reviewed = harvest.with_overrides(
            description="Tensile test data mapped with PMDco 2.",
            creators=REVIEWED_CREATORS,
        )
        metadata = reviewed.to_publication_metadata()
        self.assertEqual(
            metadata.title, "Tensile Test Ontology (TTO) data mapping example"
        )
        self.assertEqual(metadata.creators, REVIEWED_CREATORS)
        self.assertIsNone(metadata.publication_date)
        self.assertEqual(reviewed.diagnostics, ())
        self.assertEqual(reviewed.creators.observations, creators.observations)

    def test_pmdco2_example_suggests_its_description_and_keywords(self):
        harvest = harvest_publication_metadata_from_rdf(
            CORPUS / "pmdco2_tto_example.ttl"
        ).select_subject_automatically()

        description = harvest.description
        self.assertEqual(
            [suggestion.value for suggestion in description.suggestions],
            [
                "Data from 10 tensile tests. Material: S355. Test standard: DIN EN ISO 6892-1."
            ],
        )
        self.assertEqual(
            [
                (item.rule, len(item.triples))
                for item in description.suggestions[0].evidence
            ],
            [
                ("pmdco2_tensile_test", 20),
                ("pmdco2_material", 20),
                ("pmdco2_test_standard", 12),
            ],
        )
        self.assertIn(
            (
                "<https://w3id.org/pmd/ao/tte/_standard>",
                "<https://w3id.org/pmd/co/value>",
                '"DIN EN ISO 6892-1"',
            ),
            description.suggestions[0].evidence[2].triples,
        )
        self.assertEqual((description.value, description.status), (None, "missing"))

        keywords = harvest.keywords
        self.assertEqual(
            [suggestion.value for suggestion in keywords.suggestions],
            [("S355", "tensile test")],
        )
        self.assertEqual(
            [
                (item.rule, len(item.triples))
                for item in keywords.suggestions[0].evidence
            ],
            [("pmdco2_tensile_test", 20), ("pmdco2_material", 20)],
        )
        self.assertEqual((keywords.value, keywords.status), (None, "missing"))

    def test_pmdco2_example_converts_its_accepted_suggestions(self):
        harvest = harvest_publication_metadata_from_rdf(
            CORPUS / "pmdco2_tto_example.ttl"
        ).select_subject_automatically()

        reviewed = (
            harvest.accept_suggestion(harvest.description.suggestions[0])
            .accept_suggestion(harvest.keywords.suggestions[0])
            .with_overrides(creators=REVIEWED_CREATORS)
        )

        metadata = reviewed.to_publication_metadata()
        self.assertEqual(
            metadata.description,
            "Data from 10 tensile tests. Material: S355. Test standard: DIN EN ISO 6892-1.",
        )
        self.assertEqual(metadata.keywords, ("S355", "tensile test"))
        self.assertEqual(metadata.creators, REVIEWED_CREATORS)
        self.assertEqual(reviewed.description.origin, "acceptance")
        self.assertEqual(reviewed.keywords.origin, "acceptance")
        self.assertEqual(reviewed.diagnostics, ())
        self.assertEqual(reviewed.creators.observations, harvest.creators.observations)

    def test_pmdco3_example_offers_its_creation_date_only_as_a_suggestion(self):
        subject = URIRef("https://w3id.org/pmd/demodata/tensiletest_S355/")
        harvest = harvest_publication_metadata_from_rdf(
            CORPUS / "S355_data_tto_pmdco3.ttl"
        ).select_subject_automatically()

        self.assertEqual(
            [candidate.subject.term for candidate in harvest.subject_candidates],
            [subject],
        )
        self.assertEqual(harvest.subject, harvest.subject_candidates[0].subject)
        self.assertEqual(harvest.subject_origin, "automatic")
        self.assertEqual(
            harvest.title.value,
            "TTO/PMDco 3.0 A-Box mapping example of S355 steel tensile test data",
        )
        self.assertEqual(harvest.description.status, "missing")
        self.assertEqual(harvest.creators.status, "missing")
        self.assertEqual(harvest.creators.observations, ())

        self.assertEqual(harvest.publication_date.status, "missing")
        self.assertIsNone(harvest.publication_date.value)
        self.assertEqual(
            [
                (suggestion.value, suggestion.evidence[0].triples)
                for suggestion in harvest.publication_date.suggestions
            ],
            [
                (
                    date(2026, 4, 16),
                    (
                        (
                            subject.n3(),
                            "<http://purl.org/dc/terms/created>",
                            '"2026-04-16"^^<http://www.w3.org/2001/XMLSchema#date>',
                        ),
                    ),
                )
            ],
        )

        with self.assertRaises(IncompleteHarvestError) as caught:
            harvest.to_publication_metadata()
        self.assertCountEqual(
            [(item.code, item.field) for item in caught.exception.diagnostics],
            [("missing_required", "description"), ("missing_required", "creators")],
        )

        reviewed = harvest.with_overrides(
            description="S355 tensile test data mapped with PMDco 3.",
            creators=REVIEWED_CREATORS,
        )
        metadata = reviewed.to_publication_metadata()
        self.assertEqual(
            metadata.title,
            "TTO/PMDco 3.0 A-Box mapping example of S355 steel tensile test data",
        )
        self.assertEqual(metadata.creators, REVIEWED_CREATORS)
        self.assertIsNone(metadata.publication_date)
        self.assertEqual(reviewed.diagnostics, ())
        self.assertEqual(len(reviewed.publication_date.suggestions), 1)

    def test_pmdco3_example_suggests_its_description_and_keywords(self):
        harvest = harvest_publication_metadata_from_rdf(
            CORPUS / "S355_data_tto_pmdco3.ttl"
        ).select_subject_automatically()

        description = harvest.description
        self.assertEqual(
            [suggestion.value for suggestion in description.suggestions],
            [
                "Data from 10 tensile tests. Material: S355. Test standard: DIN EN ISO 6892-1."
            ],
        )
        self.assertEqual(
            [
                (item.rule, len(item.triples))
                for item in description.suggestions[0].evidence
            ],
            [
                ("pmdco3_tensile_test", 20),
                ("pmdco3_material", 40),
                ("pmdco3_test_standard", 50),
            ],
        )
        self.assertIn(
            (
                "<https://w3id.org/pmd/demodata/tensiletest_S355/testpiece/Zd2_material_material_identifier_value>",
                "<https://w3id.org/pmd/co/PMD_0000006>",
                '"S355"^^<http://www.w3.org/2001/XMLSchema#string>',
            ),
            description.suggestions[0].evidence[1].triples,
        )
        self.assertEqual((description.value, description.status), (None, "missing"))

        keywords = harvest.keywords
        self.assertEqual(
            [suggestion.value for suggestion in keywords.suggestions],
            [("S355", "tensile test")],
        )
        self.assertEqual(
            [
                (item.rule, len(item.triples))
                for item in keywords.suggestions[0].evidence
            ],
            [("pmdco3_tensile_test", 20), ("pmdco3_material", 40)],
        )
        self.assertEqual((keywords.value, keywords.status), (None, "missing"))

    def test_pmdco3_example_converts_its_accepted_suggestions(self):
        harvest = harvest_publication_metadata_from_rdf(
            CORPUS / "S355_data_tto_pmdco3.ttl"
        ).select_subject_automatically()

        reviewed = (
            harvest.accept_suggestion(harvest.description.suggestions[0])
            .accept_suggestion(harvest.keywords.suggestions[0])
            .with_overrides(creators=REVIEWED_CREATORS)
        )

        metadata = reviewed.to_publication_metadata()
        self.assertEqual(
            metadata.description,
            "Data from 10 tensile tests. Material: S355. Test standard: DIN EN ISO 6892-1.",
        )
        self.assertEqual(metadata.keywords, ("S355", "tensile test"))
        self.assertEqual(metadata.creators, REVIEWED_CREATORS)
        self.assertIsNone(metadata.publication_date)
        self.assertEqual(reviewed.description.origin, "acceptance")
        self.assertEqual(reviewed.keywords.origin, "acceptance")
        self.assertEqual(reviewed.diagnostics, ())
        self.assertEqual(len(reviewed.publication_date.suggestions), 1)

    def test_both_generations_suggest_equivalent_facts(self):
        pmdco2, pmdco3 = (
            harvest_publication_metadata_from_rdf(
                CORPUS / name
            ).select_subject_automatically()
            for name in ("pmdco2_tto_example.ttl", "S355_data_tto_pmdco3.ttl")
        )

        self.assertEqual(
            pmdco2.description.suggestions[0].value,
            pmdco3.description.suggestions[0].value,
        )
        self.assertEqual(
            pmdco2.keywords.suggestions[0].value,
            pmdco3.keywords.suggestions[0].value,
        )
