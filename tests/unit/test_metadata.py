import unittest
from datetime import date

from pydantic import ValidationError as PydanticValidationError

from praeco import Organization
from praeco.metadata import (
    Contributor,
    Person,
    PublicationMetadata,
    RelatedIdentifier,
)


class TestPublicationMetadata(unittest.TestCase):
    def test_invalid_person_mapping_cannot_fall_back_to_organization(self):
        for field in ("orcid", "gnd", "affiliation", "family_name", "given_names"):
            with self.subTest(field=field), self.assertRaises(PydanticValidationError):
                PublicationMetadata(
                    title="Dataset",
                    description="Measurements.",
                    creators=[{"name": "Jane Doe", field: 123}],
                )

    def test_organization_normalizes_name_and_optional_identifier(self):
        for identifier, expected in ((None, None), ("   ", None), (" lab-1 ", "lab-1")):
            with self.subTest(identifier=identifier):
                organization = Organization(
                    name=" Materials Lab ", identifier=identifier
                )
                self.assertEqual(organization.name, "Materials Lab")
                self.assertEqual(organization.identifier, expected)

    def test_organization_requires_non_blank_name_on_creation_and_assignment(self):
        for name in ("", "   "):
            with self.subTest(name=name):
                with self.assertRaises(PydanticValidationError):
                    Organization(name=name)
                organization = Organization(name="Materials Lab")
                with self.assertRaises(PydanticValidationError):
                    organization.name = name

    def test_publication_metadata_preserves_mixed_creator_types(self):
        person = Person(name="Doe, Jane", orcid="0000-0000-0000-0000")
        organization = Organization(name="Materials Lab", identifier="lab-1")
        metadata = PublicationMetadata(
            title="Dataset",
            description="Measurements.",
            creators=[person, organization],
        )

        self.assertEqual(metadata.creators, (person, organization))
        self.assertIsInstance(metadata.creators[0], Person)
        self.assertIsInstance(metadata.creators[1], Organization)

    def test_publication_metadata_accepts_reusable_fields(self):
        metadata = PublicationMetadata(
            title=" praeco ",
            description=" Python client. ",
            publication_date="2026-04-21",
            creators=[Person(family_name=" Doe ", given_names=" Jane ")],
            contributors=[
                Contributor(
                    person=Person(name=" Curator, Chris "),
                    role=" DataCurator ",
                )
            ],
            keywords=[" python ", " publishing "],
            license=" Apache-2.0 ",
            doi=" 10.1234/example ",
            version=" 1.0.0 ",
            language=" eng ",
            related_identifiers=[
                RelatedIdentifier(
                    identifier=" 10.1234/data ",
                    relation=" isSupplementedBy ",
                    resource_type=" dataset ",
                )
            ],
        )

        self.assertEqual(metadata.title, "praeco")
        self.assertEqual(metadata.description, "Python client.")
        self.assertEqual(metadata.publication_date, date(2026, 4, 21))
        self.assertEqual(metadata.creators[0].family_name, "Doe")
        self.assertEqual(metadata.contributors[0].person.name, "Curator, Chris")
        self.assertEqual(metadata.contributors[0].role, "DataCurator")
        self.assertEqual(metadata.keywords, ("python", "publishing"))
        self.assertEqual(metadata.license, "Apache-2.0")
        self.assertEqual(metadata.doi, "10.1234/example")
        self.assertEqual(metadata.version, "1.0.0")
        self.assertEqual(metadata.language, "eng")
        self.assertEqual(
            metadata.related_identifiers[0].identifier,
            "10.1234/data",
        )

    def test_publication_metadata_coerces_nested_dicts(self):
        metadata = PublicationMetadata(
            title="Dataset",
            description="Reusable data.",
            creators=[{"name": "Doe, Jane"}],
            contributors=[
                {
                    "person": {"family_name": "Curator", "given_names": "Chris"},
                    "role": "DataCurator",
                }
            ],
            related_identifiers=[
                {
                    "identifier": "10.1234/paper",
                    "relation": "isSupplementTo",
                }
            ],
        )

        self.assertIsInstance(metadata.creators[0], Person)
        self.assertEqual(metadata.creators[0].name, "Doe, Jane")
        self.assertIsInstance(metadata.contributors[0], Contributor)
        self.assertIsInstance(metadata.contributors[0].person, Person)
        self.assertIsInstance(metadata.related_identifiers[0], RelatedIdentifier)

    def test_publication_date_has_no_default(self):
        metadata = PublicationMetadata(
            title="Dataset",
            description="Reusable data.",
            creators=[Person(name="Doe, Jane")],
        )

        self.assertIsNone(metadata.publication_date)

    def test_optional_text_fields_accept_none(self):
        person = Person(
            name="Doe, Jane",
            affiliation=None,
        )
        contributor = Contributor(
            person=person,
            role=None,
        )
        related_identifier = RelatedIdentifier(
            identifier="10.1234/example",
            relation="cites",
            resource_type=None,
        )

        self.assertIsNone(person.affiliation)
        self.assertIsNone(contributor.role)
        self.assertIsNone(related_identifier.resource_type)

    def test_person_requires_name_or_structured_name_parts(self):
        with self.assertRaisesRegex(PydanticValidationError, "person requires"):
            Person()

        with self.assertRaisesRegex(PydanticValidationError, "person requires"):
            Person(family_name="Doe")

    def test_publication_metadata_requires_non_empty_core_fields(self):
        cases = [
            (
                {
                    "title": "",
                    "description": "Data.",
                    "creators": [Person(name="Doe, Jane")],
                },
                "non-empty string",
            ),
            (
                {
                    "title": "Dataset",
                    "description": " ",
                    "creators": [Person(name="Doe, Jane")],
                },
                "non-empty string",
            ),
            (
                {
                    "title": "Dataset",
                    "description": "Data.",
                    "creators": [],
                },
                "creators",
            ),
        ]

        for kwargs, message in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(PydanticValidationError, message),
            ):
                PublicationMetadata(**kwargs)

    def test_related_identifier_requires_non_empty_identifier_and_relation(self):
        cases = [
            ({"identifier": "", "relation": "cites"}, "non-empty string"),
            ({"identifier": "10.1234/example", "relation": " "}, "non-empty string"),
        ]

        for kwargs, message in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(PydanticValidationError, message),
            ):
                RelatedIdentifier(**kwargs)

    def test_assignment_is_validated(self):
        metadata = PublicationMetadata(
            title="Dataset",
            description="Reusable data.",
            creators=[Person(name="Doe, Jane")],
        )

        metadata.publication_date = "2026-05-01"
        metadata.creators = [{"name": "Curator, Chris"}]

        self.assertEqual(metadata.publication_date, date(2026, 5, 1))
        self.assertIsInstance(metadata.creators[0], Person)
        self.assertEqual(metadata.creators[0].name, "Curator, Chris")

        with self.assertRaisesRegex(PydanticValidationError, "non-empty string"):
            metadata.title = " "
        with self.assertRaisesRegex(PydanticValidationError, "creators"):
            metadata.creators = []

    def test_collection_fields_are_immutable_after_validation(self):
        metadata = PublicationMetadata(
            title="Dataset",
            description="Reusable data.",
            creators=[Person(name="Doe, Jane")],
            keywords=["data"],
        )

        self.assertIsInstance(metadata.creators, tuple)
        self.assertIsInstance(metadata.contributors, tuple)
        self.assertIsInstance(metadata.keywords, tuple)
        self.assertIsInstance(metadata.related_identifiers, tuple)

        with self.assertRaises(AttributeError):
            metadata.creators.clear()
        with self.assertRaises(AttributeError):
            metadata.keywords.append(" ")


if __name__ == "__main__":
    unittest.main()
