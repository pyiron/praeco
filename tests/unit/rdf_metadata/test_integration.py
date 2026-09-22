import unittest
from datetime import date
from pathlib import Path

from praeco import (
    Organization,
    Person,
    RdfMetadataHarvest,
    harvest_publication_metadata_from_rdf,
)
from praeco.rdf_metadata import IncompleteHarvestError
from praeco.services.dataportal import DataportalMetadata
from praeco.services.zenodo import ZenodoMetadata

EXAMPLE = Path(__file__).parents[2] / "resources/rdf_metadata/review-example.ttl"


class TestPublicInteraction(unittest.TestCase):
    def test_recorded_review_interaction(self):
        harvest = harvest_publication_metadata_from_rdf(EXAMPLE)
        self.assertIsInstance(harvest, RdfMetadataHarvest)
        self.assertEqual(
            [str(subject.term) for subject in harvest.subjects],
            [
                "https://example.org/dataset",
                "https://example.org/organizations/lab",
                "https://example.org/people/jane",
            ],
        )
        harvest = harvest.select_subject(harvest.subjects[0])
        self.assertEqual(
            [candidate.value for candidate in harvest.title.candidates],
            ["Tensile measurements", "Tensile test data"],
        )
        self.assertEqual(harvest.title.status, "unresolved")
        self.assertEqual(harvest.creators.status, "unresolved")
        self.assertEqual(harvest.publication_date.status, "unresolved")
        harvest = harvest.select_candidate(harvest.title.candidates[0])
        harvest = harvest.with_overrides(
            description="Measurements from tensile tests.",
            creators=(Person(name="Jane Doe"), Organization(name="Materials Lab")),
        )
        with self.assertRaises(IncompleteHarvestError) as caught:
            harvest.to_publication_metadata()
        self.assertEqual(
            [item.field for item in caught.exception.diagnostics], ["publication_date"]
        )
        harvest = harvest.clear("publication_date")
        metadata = harvest.to_publication_metadata()
        self.assertEqual(metadata.title, "Tensile measurements")
        self.assertEqual(metadata.description, "Measurements from tensile tests.")
        self.assertEqual(
            metadata.creators,
            (Person(name="Jane Doe"), Organization(name="Materials Lab")),
        )
        self.assertIsNone(metadata.publication_date)
        self.assertEqual(metadata.keywords, ("steel", "tensile testing"))
        self.assertEqual(metadata.license, "CC-BY-4.0")
        self.assertEqual(harvest.diagnostics, ())
        self.assertEqual(len(harvest.creators.observations), 2)
        self.assertEqual(len(harvest.publication_date.candidates), 2)
        self.assertEqual(len(harvest.publication_date.suggestions), 1)

    def test_harvested_values_pass_through_existing_adapters(self):
        harvest = harvest_publication_metadata_from_rdf(
            """
            @prefix dct: <http://purl.org/dc/terms/> .
            @prefix foaf: <http://xmlns.com/foaf/0.1/> .
            <urn:dataset> dct:title "Measurements"; dct:description "Tensile tests.";
                dct:creator <urn:lab>, <http://orcid.org/0000-0002-1825-0097>;
                dct:created "2020-01-02";
                dct:license <https://creativecommons.org/licenses/by/4.0/> .
            <urn:lab> a foaf:Organization; foaf:name "Materials Lab" .
            <http://orcid.org/0000-0002-1825-0097> a foaf:Person; foaf:name "Jane Doe" .
        """,
            subject="urn:dataset",
        )
        reviewed = harvest.accept_suggestion(harvest.publication_date.suggestions[0])
        metadata = reviewed.to_publication_metadata()
        dataportal = DataportalMetadata(metadata=metadata).to_payload()
        zenodo = ZenodoMetadata.dataset(metadata).to_payload()["metadata"]
        self.assertEqual(
            dataportal["creator"],
            [
                {
                    "name": "Jane Doe",
                    "type": "Person",
                    "identifier": "https://orcid.org/0000-0002-1825-0097",
                },
                {
                    "name": "Materials Lab",
                    "type": "Organization",
                    "identifier": "urn:lab",
                },
            ],
        )
        self.assertEqual(
            zenodo["creators"],
            [
                {"name": "Jane Doe", "orcid": "https://orcid.org/0000-0002-1825-0097"},
                {"name": "Materials Lab"},
            ],
        )
        self.assertEqual(metadata.publication_date, date(2020, 1, 2))
        self.assertEqual(zenodo["publication_date"], "2020-01-02")
        self.assertEqual(dataportal["issued"], "2020-01-02")
        self.assertEqual(dataportal["title"], zenodo["title"])
        self.assertEqual(dataportal["license_id"], zenodo["license"])
        self.assertEqual(
            zenodo["license"], "https://creativecommons.org/licenses/by/4.0/"
        )
        self.assertFalse(
            any(item["key"].startswith("rdf_") for item in dataportal.get("extras", []))
        )
        self.assertNotIn("origin", zenodo)
        self.assertEqual(reviewed.publication_date.origin, "acceptance")
        self.assertIsNone(harvest.publication_date.value)
