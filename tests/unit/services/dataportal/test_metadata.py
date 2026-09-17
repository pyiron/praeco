import json
import unittest
from datetime import datetime
from typing import Any, cast

from praeco.exceptions import ValidationError
from praeco.metadata import (
    Contributor,
    Organization,
    Person,
    PublicationMetadata,
    RelatedIdentifier,
)
from praeco.services.dataportal import DataportalMetadata
from praeco.services.dataportal.metadata import _orcid_uri, _person_name


def publication_metadata(**overrides: Any) -> PublicationMetadata:
    values: dict[str, Any] = {
        "title": "Steel Heat Treatment Data",
        "description": "Measurements from a heat treatment experiment.",
        "publication_date": "2026-06-08",
        "creators": [
            Person(
                family_name="Doe",
                given_names="Jane",
                affiliation="MPI-SusMat",
                orcid="0000-0000-0000-0000",
            )
        ],
        "contributors": [
            Contributor(
                person=Person(name="Curator, Chris"),
                role="DataCurator",
            )
        ],
        "keywords": ["steel", "heat treatment"],
        "license": "CC-BY-4.0",
        "doi": "10.1234/example",
        "version": "1.0.0",
        "language": "eng",
        "related_identifiers": [
            RelatedIdentifier(
                identifier="10.1234/source",
                relation="isDerivedFrom",
                resource_type="dataset",
            )
        ],
    }
    values.update(overrides)
    return PublicationMetadata(**values)


def extras_by_key(payload: dict[str, Any]) -> dict[str, str]:
    return {item["key"]: item["value"] for item in payload.get("extras", [])}


class TestDataportalMetadata(unittest.TestCase):
    def test_serializes_mixed_person_and_organization_creators(self):
        for identifier in (None, "lab-1"):
            with self.subTest(identifier=identifier):
                metadata = publication_metadata(
                    creators=[
                        Person(name="Doe, Jane", orcid="0000", affiliation="Lab"),
                        Organization(name="Materials Lab", identifier=identifier),
                    ]
                )
                payload = DataportalMetadata(metadata=metadata).to_payload()
                organization = {"name": "Materials Lab", "type": "Organization"}
                if identifier is not None:
                    organization["identifier"] = identifier

                self.assertEqual(
                    payload["creator"],
                    [
                        {
                            "name": "Doe, Jane",
                            "type": "Person",
                            "identifier": "https://orcid.org/0000",
                        },
                        organization,
                    ],
                )
                self.assertEqual(
                    json.loads(extras_by_key(payload)["creators"]),
                    [
                        {"name": "Doe, Jane", "orcid": "0000", "affiliation": "Lab"},
                        organization,
                    ],
                )

    def test_serializes_publication_and_dataportal_fields(self):
        metadata = DataportalMetadata(
            metadata=publication_metadata(),
            owner_org="materials-org",
            private=False,
            groups=["heat-treatment"],
            extras={"pmd_profile": "dataset-v1"},
            dataset_type="dataset",
        )

        payload = metadata.to_payload()

        self.assertEqual(payload["name"], "steel-heat-treatment-data")
        self.assertEqual(payload["title"], "Steel Heat Treatment Data")
        self.assertEqual(
            payload["notes"],
            "Measurements from a heat treatment experiment.",
        )
        self.assertEqual(
            payload["tags"],
            [{"name": "steel"}, {"name": "heat treatment"}],
        )
        self.assertEqual(payload["license_id"], "CC-BY-4.0")
        self.assertEqual(payload["version"], "1.0.0")
        self.assertEqual(payload["owner_org"], "materials-org")
        self.assertFalse(payload["private"])
        self.assertEqual(payload["groups"], [{"name": "heat-treatment"}])
        self.assertEqual(payload["type"], "dataset")
        self.assertEqual(
            payload["creator"],
            [
                {
                    "identifier": "https://orcid.org/0000-0000-0000-0000",
                    "name": "Doe, Jane",
                    "type": "Person",
                }
            ],
        )
        self.assertEqual(payload["issued"], "2026-06-08")
        self.assertEqual(payload["language"], ["eng"])
        self.assertEqual(payload["identifier"], "10.1234/example")

        extras = extras_by_key(payload)
        self.assertEqual(extras["pmd_profile"], "dataset-v1")
        self.assertEqual(extras["publication_date"], "2026-06-08")
        self.assertEqual(extras["doi"], "10.1234/example")
        self.assertEqual(extras["language"], "eng")
        self.assertEqual(
            json.loads(extras["creators"]),
            [
                {
                    "affiliation": "MPI-SusMat",
                    "family_name": "Doe",
                    "given_names": "Jane",
                    "orcid": "0000-0000-0000-0000",
                }
            ],
        )
        self.assertEqual(
            json.loads(extras["contributors"]),
            [
                {
                    "person": {"name": "Curator, Chris"},
                    "role": "DataCurator",
                }
            ],
        )
        self.assertEqual(
            json.loads(extras["related_identifiers"]),
            [
                {
                    "identifier": "10.1234/source",
                    "relation": "isDerivedFrom",
                    "resource_type": "dataset",
                }
            ],
        )

    def test_explicit_name_is_trimmed(self):
        metadata = DataportalMetadata(
            metadata=publication_metadata(),
            name="  explicit-dataset-name  ",
        )

        self.assertEqual(metadata.to_payload()["name"], "explicit-dataset-name")

    def test_optional_publication_values_are_omitted(self):
        publication = publication_metadata(
            publication_date=None,
            contributors=[],
            keywords=[],
            license=None,
            doi=None,
            version=None,
            language=None,
            related_identifiers=[],
        )

        payload = DataportalMetadata(metadata=publication).to_payload()
        extras = extras_by_key(payload)

        self.assertEqual(payload["tags"], [])
        self.assertEqual(
            payload["creator"],
            [
                {
                    "identifier": "https://orcid.org/0000-0000-0000-0000",
                    "name": "Doe, Jane",
                    "type": "Person",
                }
            ],
        )
        self.assertNotIn("license_id", payload)
        self.assertNotIn("version", payload)
        self.assertNotIn("issued", payload)
        self.assertNotIn("language", payload)
        self.assertNotIn("identifier", payload)
        self.assertEqual(set(extras), {"creators"})

    def test_dataportal_specific_schema_fields_are_serialized(self):
        metadata = DataportalMetadata(
            metadata=publication_metadata(),
            publisher={
                "name": "MPI-SusMat",
                "type": "Organization",
                "identifier": "https://ror.org/03y34c780",
                "url": "https://www.mpie.de/",
            },
            contact=[
                {
                    "name": "Data Steward",
                    "email": "data@example.org",
                    "identifier": "https://ror.org/03y34c780",
                }
            ],
            modified="2026-07-22",
            identifier="https://doi.org/10.1234/explicit",
        )

        payload = metadata.to_payload()

        self.assertEqual(
            payload["publisher"],
            [
                {
                    "name": "MPI-SusMat",
                    "type": "Organization",
                    "identifier": "https://ror.org/03y34c780",
                    "url": "https://www.mpie.de/",
                }
            ],
        )
        self.assertEqual(
            payload["contact"],
            [
                {
                    "name": "Data Steward",
                    "email": "data@example.org",
                    "identifier": "https://ror.org/03y34c780",
                }
            ],
        )
        self.assertEqual(payload["modified"], "2026-07-22")
        self.assertEqual(payload["identifier"], "https://doi.org/10.1234/explicit")

    def test_modified_accepts_date_instances(self):
        metadata = DataportalMetadata(
            metadata=publication_metadata(),
            modified=publication_metadata().publication_date,
        )

        self.assertEqual(metadata.to_payload()["modified"], "2026-06-08")

    def test_modified_rejects_datetime_instances(self):
        with self.assertRaisesRegex(ValidationError, "modified must be an ISO date"):
            DataportalMetadata(
                metadata=publication_metadata(),
                modified=datetime(2026, 7, 22, 10, 30),
            )

    def test_schema_creator_accepts_explicit_person_name(self):
        publication = publication_metadata(
            creators=[Person(name="Steel Research Group")],
        )

        payload = DataportalMetadata(metadata=publication).to_payload()

        self.assertEqual(
            payload["creator"],
            [
                {
                    "name": "Steel Research Group",
                    "type": "Person",
                }
            ],
        )

    def test_schema_creator_keeps_multiple_creators(self):
        publication = publication_metadata(
            creators=[
                Person(name="Steel Research Group"),
                Person(name="Doe, Jane", orcid="https://orcid.org/0000-0000-0000-0001"),
            ],
        )

        payload = DataportalMetadata(metadata=publication).to_payload()

        self.assertEqual(
            payload["creator"],
            [
                {
                    "name": "Steel Research Group",
                    "type": "Person",
                },
                {
                    "identifier": "https://orcid.org/0000-0000-0000-0001",
                    "name": "Doe, Jane",
                    "type": "Person",
                },
            ],
        )

    def test_person_name_rejects_invalid_person_state(self):
        person = object.__new__(Person)

        with self.assertRaisesRegex(ValidationError, "person requires"):
            _ = _person_name(person)

    def test_orcid_uri_omits_blank_values(self):
        self.assertIsNone(_orcid_uri(" "))

    def test_generated_extra_collision_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "publication_date"):
            DataportalMetadata(
                metadata=publication_metadata(),
                extras={"publication_date": "override"},
            )

    def test_duplicate_normalized_extra_keys_are_rejected(self):
        with self.assertRaisesRegex(
            ValidationError,
            "duplicate extra key after normalization: 'profile'",
        ):
            DataportalMetadata(
                metadata=publication_metadata(),
                extras={"profile": "first", " profile ": "second"},
            )

    def test_blank_dataportal_fields_are_rejected(self):
        cases = [
            ({"name": " "}, "name"),
            ({"owner_org": " "}, "owner_org"),
            ({"dataset_type": " "}, "dataset_type"),
            ({"identifier": " "}, "identifier"),
            ({"modified": " "}, "modified"),
            ({"groups": [" "]}, "group"),
            ({"publisher": {"name": " "}}, "publisher"),
            ({"contact": [{"email": " "}]}, "contact"),
            ({"extras": {" ": "value"}}, "extra key"),
        ]

        for kwargs, message in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ValidationError, message),
            ):
                DataportalMetadata(metadata=publication_metadata(), **kwargs)

    def test_private_must_be_boolean(self):
        with self.assertRaisesRegex(ValidationError, "private must be a boolean"):
            DataportalMetadata(
                metadata=publication_metadata(),
                private=cast(Any, "false"),
            )

    def test_groups_and_extras_require_expected_container_types(self):
        cases = [
            ({"groups": None}, "groups must be a list"),
            ({"groups": "foo"}, "groups must be a list"),
            ({"contact": None}, "contact must be a list"),
            ({"contact": "foo"}, "contact must be a list"),
            ({"extras": None}, "extras must be a dict"),
            ({"extras": []}, "extras must be a dict"),
        ]

        for kwargs, message in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ValidationError, message),
            ):
                DataportalMetadata(
                    metadata=publication_metadata(),
                    **cast(Any, kwargs),
                )

    def test_extra_values_must_be_strings(self):
        with self.assertRaisesRegex(ValidationError, "extra values must be strings"):
            DataportalMetadata(
                metadata=publication_metadata(),
                extras=cast(Any, {"priority": 1}),
            )

    def test_schema_mappings_reject_invalid_fields_and_values(self):
        cases = [
            ({"publisher": "publisher"}, "publisher must be a mapping"),
            ({"publisher": {"unknown": "value"}}, "unsupported field"),
            ({"publisher": {"name": 1}}, "publisher values must be strings"),
            ({"contact": [{"type": "Person"}]}, "unsupported field"),
            ({"contact": [{"name": 1}]}, "contact values must be strings"),
            ({"modified": "2026/07/22"}, "modified must be an ISO date"),
        ]

        for kwargs, message in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ValidationError, message),
            ):
                DataportalMetadata(
                    metadata=publication_metadata(),
                    **cast(Any, kwargs),
                )

    def test_metadata_must_be_publication_metadata(self):
        with self.assertRaisesRegex(ValidationError, "PublicationMetadata"):
            DataportalMetadata(metadata=cast(Any, {"title": "raw"}))

    def test_name_is_required_when_title_cannot_form_ascii_slug(self):
        with self.assertRaisesRegex(ValidationError, "name must be provided"):
            DataportalMetadata(
                metadata=publication_metadata(title="材料"),
            )

    def test_serialization_revalidates_mutable_specific_fields(self):
        metadata = DataportalMetadata(metadata=publication_metadata())
        metadata.groups.append(" ")

        with self.assertRaisesRegex(ValidationError, "group"):
            metadata.to_payload()


if __name__ == "__main__":
    unittest.main()
