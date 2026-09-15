import unittest
import warnings
from datetime import date

import praeco.metadata as common_metadata
from praeco.exceptions import ValidationError
from praeco.services.zenodo import (
    CommunityRef,
    Contributor,
    Creator,
    GrantRef,
    RelatedIdentifier,
    ZenodoMetadata,
)
from praeco.services.zenodo.metadata import _add_if_present, _person_api_name

_LEGACY_METADATA_WARNING = (
    "Setting publication metadata fields directly on ZenodoMetadata is deprecated.*"
)


def _valid_metadata(**overrides):
    values = {
        "upload_type": "software",
        "publication_date": "2026-04-21",
        "title": "praeco",
        "creators": [Creator(name="Doe, Jane")],
        "description": "Python client.",
        "access_right": "open",
        "license": "Apache-2.0",
    }
    values.update(overrides)
    return ZenodoMetadata(**values)


def _valid_publication_metadata(**overrides):
    values = {
        "title": "praeco",
        "publication_date": "2026-04-21",
        "description": "Python client.",
        "creators": [common_metadata.Person(family_name="Doe", given_names="Jane")],
        "license": "Apache-2.0",
    }
    values.update(overrides)
    return common_metadata.PublicationMetadata(**values)


class TestZenodoMetadata(unittest.TestCase):
    def test_serializes_mixed_person_and_organization_creators(self):
        metadata = _valid_publication_metadata(
            creators=[
                common_metadata.Person(
                    family_name="Doe",
                    given_names="Jane",
                    orcid="0000",
                    affiliation="Lab",
                ),
                common_metadata.Organization(name="Materials Lab", identifier="lab-1"),
            ]
        )

        payload = ZenodoMetadata.dataset(metadata).to_payload()

        self.assertEqual(
            payload["metadata"]["creators"],
            [
                {"name": "Doe, Jane", "orcid": "0000", "affiliation": "Lab"},
                {"name": "Materials Lab"},
            ],
        )

    def setUp(self):
        self._warning_context = warnings.catch_warnings()
        self._warning_context.__enter__()
        self.addCleanup(self._warning_context.__exit__, None, None, None)
        warnings.filterwarnings(
            "ignore",
            message=_LEGACY_METADATA_WARNING,
            category=DeprecationWarning,
        )

    def test_software_metadata_serializes_to_zenodo_payload(self):
        md = ZenodoMetadata.software()
        md.title = "praeco"
        md.publication_date = date(2026, 4, 21)
        md.description = "Python client."
        md.license = "Apache-2.0"
        md.creators.append(Creator(family_name="Doe", given_names="Jane"))
        md.add_keyword("python")

        self.assertDictEqual(
            md.to_payload(),
            {
                "metadata": {
                    "upload_type": "software",
                    "publication_date": "2026-04-21",
                    "title": "praeco",
                    "creators": [{"name": "Doe, Jane"}],
                    "description": "Python client.",
                    "access_right": "open",
                    "license": "Apache-2.0",
                    "language": "eng",
                    "keywords": ["python"],
                }
            },
        )

    def test_from_dict_accepts_metadata_payload(self):
        md = ZenodoMetadata.from_dict(
            {
                "metadata": {
                    "upload_type": "dataset",
                    "publication_date": "2026-04-21",
                    "title": "dataset",
                    "creators": [{"name": "Doe, Jane", "orcid": "0000"}],
                    "description": "Data.",
                    "access_right": "open",
                    "license": "cc-by-4.0",
                    "keywords": ["science", ""],
                    "communities": [{"identifier": "pyiron"}],
                    "grants": [{"id": "10.13039/501100000000::12345"}],
                }
            }
        )

        self.assertEqual(md.upload_type, "dataset")
        self.assertEqual(md.creators[0].name, "Doe, Jane")
        self.assertEqual(md.creators[0].orcid, "0000")
        self.assertEqual(md.keywords, ["science"])
        self.assertEqual(md.communities[0].identifier, "pyiron")
        self.assertEqual(md.grants[0].id, "10.13039/501100000000::12345")
        self.assertEqual(md.to_api_dict()["publication_date"], "2026-04-21")

    def test_publication_metadata_serializes_to_zenodo_payload(self):
        publication = _valid_publication_metadata(
            creators=[
                common_metadata.Person(
                    family_name="Doe",
                    given_names="Jane",
                    affiliation="CERN",
                    orcid="0000-0000-0000-0000",
                    gnd="123",
                )
            ],
            contributors=[
                common_metadata.Contributor(
                    person=common_metadata.Person(
                        name="Curator, Chris",
                        affiliation="CERN",
                    ),
                    role="DataCurator",
                )
            ],
            keywords=["python", "client"],
            doi="10.1234/example",
            version="1.0.0",
            language="eng",
            related_identifiers=[
                common_metadata.RelatedIdentifier(
                    identifier="10.1234/data",
                    relation="isSupplementedBy",
                    resource_type="dataset",
                )
            ],
        )

        md = ZenodoMetadata.software(publication)
        payload = md.to_payload()

        self.assertDictEqual(
            payload,
            {
                "metadata": {
                    "upload_type": "software",
                    "publication_date": "2026-04-21",
                    "title": "praeco",
                    "creators": [
                        {
                            "name": "Doe, Jane",
                            "affiliation": "CERN",
                            "orcid": "0000-0000-0000-0000",
                            "gnd": "123",
                        }
                    ],
                    "description": "Python client.",
                    "access_right": "open",
                    "license": "Apache-2.0",
                    "doi": "10.1234/example",
                    "keywords": ["python", "client"],
                    "related_identifiers": [
                        {
                            "identifier": "10.1234/data",
                            "relation": "isSupplementedBy",
                            "resource_type": "dataset",
                        }
                    ],
                    "contributors": [
                        {
                            "name": "Curator, Chris",
                            "type": "DataCurator",
                            "affiliation": "CERN",
                        }
                    ],
                    "version": "1.0.0",
                    "language": "eng",
                }
            },
        )

    def test_publication_metadata_adapter_does_not_warn(self):
        publication = _valid_publication_metadata()
        md = ZenodoMetadata.software(publication)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            payload = md.to_payload()

        deprecations = [
            warning
            for warning in caught
            if issubclass(warning.category, DeprecationWarning)
        ]
        self.assertEqual(deprecations, [])
        self.assertEqual(payload["metadata"]["title"], "praeco")

    def test_legacy_common_metadata_serialization_warns(self):
        md = _valid_metadata()

        with self.assertWarnsRegex(DeprecationWarning, "PublicationMetadata"):
            payload = md.to_api_dict()

        self.assertEqual(payload["title"], "praeco")

    def test_legacy_common_metadata_helper_methods_warn(self):
        md = ZenodoMetadata.dataset()

        with self.assertWarnsRegex(DeprecationWarning, "PublicationMetadata"):
            creator = md.add_creator(name="Doe, Jane")
        with self.assertWarnsRegex(DeprecationWarning, "PublicationMetadata"):
            md.add_keyword("data")
        with self.assertWarnsRegex(DeprecationWarning, "PublicationMetadata"):
            related = md.add_related_identifier(
                identifier="10.1234/example",
                relation="cites",
            )

        self.assertIs(md.creators[0], creator)
        self.assertEqual(md.keywords, ["data"])
        self.assertIs(md.related_identifiers[0], related)

    def test_publication_metadata_keeps_zenodo_specific_fields_on_adapter(self):
        publication = _valid_publication_metadata()
        md = ZenodoMetadata.publication(
            "article",
            publication,
        )
        md.prereserve_doi = True
        md.notes = "Release notes."
        md.add_community("pyiron")
        md.add_grant("grant-1")

        payload = md.to_api_dict()

        self.assertEqual(payload["publication_type"], "article")
        self.assertTrue(payload["prereserve_doi"])
        self.assertEqual(payload["notes"], "Release notes.")
        self.assertEqual(payload["communities"], [{"identifier": "pyiron"}])
        self.assertEqual(payload["grants"], [{"id": "grant-1"}])

    def test_publication_metadata_rejects_duplicate_common_fields(self):
        publication = _valid_publication_metadata()
        cases = [
            ({"title": "legacy"}, "title"),
            ({"creators": [Creator(name="Legacy, Creator")]}, "creators"),
            ({"keywords": ["legacy"]}, "keywords"),
            ({"language": "deu"}, "language"),
        ]

        for kwargs, message in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ValidationError, message),
            ):
                ZenodoMetadata(
                    metadata=publication,
                    upload_type="software",
                    **kwargs,
                ).validate()

    def test_publication_metadata_contributor_requires_role_for_zenodo(self):
        publication = _valid_publication_metadata(
            contributors=[
                common_metadata.Contributor(
                    person=common_metadata.Person(name="Curator, Chris"),
                )
            ],
        )

        with self.assertRaisesRegex(ValidationError, "contributor role"):
            ZenodoMetadata.software(publication).to_api_dict()

    def test_publication_person_adapter_rejects_invalid_identity(self):
        person = object.__new__(common_metadata.Person)
        object.__setattr__(person, "name", None)
        object.__setattr__(person, "family_name", None)
        object.__setattr__(person, "given_names", None)

        with self.assertRaisesRegex(ValidationError, "person requires"):
            _person_api_name(person)

    def test_creator_can_use_explicit_name(self):
        creator = Creator(name="Zenodo Team", affiliation="CERN")
        self.assertEqual(
            creator.to_api_dict(),
            {"name": "Zenodo Team", "affiliation": "CERN"},
        )

    def test_creator_requires_name_or_name_parts(self):
        with self.assertRaisesRegex(ValidationError, "creator requires"):
            Creator().validate()

    def test_related_identifier_serializes_optional_resource_type(self):
        related = RelatedIdentifier(
            identifier="10.1234/example",
            relation="isSupplementTo",
            resource_type="dataset",
        )

        self.assertEqual(
            related.to_api_dict(),
            {
                "identifier": "10.1234/example",
                "relation": "isSupplementTo",
                "resource_type": "dataset",
            },
        )

    def test_contributor_serializes_optional_identifiers(self):
        contributor = Contributor(
            name="Curator, Chris",
            type="DataCurator",
            affiliation="CERN",
            orcid="0000-0000-0000-0000",
            gnd="123",
        )

        self.assertEqual(
            contributor.to_api_dict(),
            {
                "name": "Curator, Chris",
                "type": "DataCurator",
                "affiliation": "CERN",
                "orcid": "0000-0000-0000-0000",
                "gnd": "123",
            },
        )

    def test_community_and_grant_refs_validate_identifiers(self):
        self.assertEqual(CommunityRef("pyiron").to_api_dict(), {"identifier": "pyiron"})
        self.assertEqual(GrantRef("grant-1").to_api_dict(), {"id": "grant-1"})

    def test_required_fields_are_validated(self):
        md = ZenodoMetadata.software()
        with self.assertRaisesRegex(
            ValidationError, "title must be a non-empty string"
        ):
            md.validate()

    def test_open_access_requires_license(self):
        md = ZenodoMetadata.dataset()
        md.title = "dataset"
        md.publication_date = "2026-04-21"
        md.description = "Data."
        md.creators.append(Creator(name="Doe, Jane"))

        with self.assertRaisesRegex(ValidationError, "license"):
            md.validate()

    def test_metadata_validates_upload_and_access_variants(self):
        cases = [
            (
                _valid_metadata(upload_type="unsupported"),
                "unsupported upload_type",
            ),
            (
                _valid_metadata(upload_type="publication"),
                "publication_type",
            ),
            (
                _valid_metadata(upload_type="image"),
                "image_type",
            ),
            (
                _valid_metadata(access_right="invalid"),
                "unsupported access_right",
            ),
            (
                _valid_metadata(access_right="embargoed", embargo_date="invalid_date"),
                "embargo_date",
            ),
            (
                _valid_metadata(access_right="restricted", license=None),
                "access_conditions",
            ),
        ]

        for metadata, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValidationError, message),
            ):
                metadata.validate()

    def test_metadata_requires_at_least_one_creator(self):
        md = _valid_metadata()
        md.creators.clear()

        with self.assertRaisesRegex(ValidationError, "creators"):
            md.validate()

    def test_full_metadata_serializes_optional_fields(self):
        md = ZenodoMetadata.publication("article")
        md.title = "Paper"
        md.publication_date = "2026-04-21"
        md.description = "Publication."
        md.license = "cc-by-4.0"
        md.prereserve_doi = False
        md.doi = "10.1234/example"
        md.notes = "Release notes."
        md.version = "1.0.0"
        md.language = "eng"
        md.add_creator(name="Doe, Jane")
        md.add_related_identifier(
            identifier="10.1234/data",
            relation="isSupplementedBy",
        )
        md.contributors.append(Contributor(name="Curator, Chris", type="DataCurator"))
        md.add_community("pyiron")
        md.add_grant("grant-1")

        payload = md.to_api_dict()

        self.assertEqual(payload["publication_type"], "article")
        self.assertFalse(payload["prereserve_doi"])
        self.assertEqual(
            payload["related_identifiers"][0]["identifier"], "10.1234/data"
        )
        self.assertEqual(payload["contributors"][0]["type"], "DataCurator")
        self.assertEqual(payload["communities"], [{"identifier": "pyiron"}])
        self.assertEqual(payload["grants"], [{"id": "grant-1"}])
        self.assertEqual(payload["version"], "1.0.0")
        self.assertEqual(payload["language"], "eng")

    def test_image_metadata_serializes_image_type_and_embargo(self):
        md = ZenodoMetadata.image("figure")
        md.title = "Figure"
        md.publication_date = date(2026, 4, 21)
        md.description = "Image."
        md.creators.append(Creator(name="Doe, Jane"))
        md.access_right = "embargoed"
        md.license = "cc-by-4.0"
        md.embargo_date = date(2026, 5, 1)

        payload = md.to_api_dict()

        self.assertEqual(payload["image_type"], "figure")
        self.assertEqual(payload["embargo_date"], "2026-05-01")

    def test_restricted_metadata_serializes_access_conditions(self):
        md = _valid_metadata(access_right="restricted", license=None)
        md.access_conditions = "Available on request."

        payload = md.to_api_dict()

        self.assertEqual(payload["access_conditions"], "Available on request.")
        self.assertNotIn("license", payload)

    def test_add_keyword_rejects_blank_keyword(self):
        with self.assertRaisesRegex(ValidationError, "keyword"):
            ZenodoMetadata.dataset().add_keyword(" ")

    def test_helper_methods_append_metadata_entries(self):
        md = ZenodoMetadata.dataset()

        creator = md.add_creator(name="Doe, Jane")
        related = md.add_related_identifier(
            identifier="10.1234/example",
            relation="cites",
        )
        community = md.add_community("pyiron")
        grant = md.add_grant("grant-1")

        self.assertIs(md.creators[0], creator)
        self.assertIs(md.related_identifiers[0], related)
        self.assertIs(md.communities[0], community)
        self.assertIs(md.grants[0], grant)

    def test_add_if_present_keeps_non_string_values(self):
        data = {}

        _add_if_present(data, "prereserve_doi", False)

        self.assertEqual(data, {"prereserve_doi": False})

    def test_from_dict_accepts_full_metadata_payload(self):
        md = ZenodoMetadata.from_dict(
            {
                "upload_type": "publication",
                "publication_type": "article",
                "image_type": "figure",
                "publication_date": date(2026, 4, 21),
                "title": "Paper",
                "creators": [
                    {
                        "family_name": "Doe",
                        "given_names": "Jane",
                        "affiliation": "CERN",
                        "gnd": "123",
                    }
                ],
                "description": "Publication.",
                "access_right": "embargoed",
                "license": "cc-by-4.0",
                "embargo_date": "2026-05-01",
                "access_conditions": "Available on request.",
                "doi": "10.1234/example",
                "prereserve_doi": True,
                "keywords": None,
                "notes": "Notes.",
                "related_identifiers": [
                    {
                        "identifier": "10.1234/data",
                        "relation": "isSupplementedBy",
                        "resource_type": "dataset",
                    }
                ],
                "contributors": [
                    {
                        "name": "Curator, Chris",
                        "type": "DataCurator",
                        "affiliation": "CERN",
                    }
                ],
                "communities": [{"identifier": "pyiron"}],
                "grants": [{"id": "grant-1"}],
                "version": "1.0.0",
                "language": "eng",
            }
        )

        self.assertEqual(md.publication_date, date(2026, 4, 21))
        self.assertTrue(md.prereserve_doi)
        self.assertEqual(md.related_identifiers[0].resource_type, "dataset")
        self.assertEqual(md.contributors[0].affiliation, "CERN")

    def test_from_dict_rejects_invalid_optional_values(self):
        cases = [
            ({"prereserve_doi": "yes"}, "prereserve_doi"),
            ({"publication_date": "not-a-date"}, "date"),
            ({"creators": "Doe"}, "creators must be a list"),
            ({"creators": ["Doe"]}, "creators entries must be objects"),
            ({"keywords": "science"}, "keywords must be a list"),
            ({"related_identifiers": [{"relation": "cites"}]}, "identifier"),
            ({"contributors": [{"name": "Curator"}]}, "contributor type"),
        ]

        for payload, message in cases:
            with (
                self.subTest(payload=payload),
                self.assertRaisesRegex(ValidationError, message),
            ):
                ZenodoMetadata.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
