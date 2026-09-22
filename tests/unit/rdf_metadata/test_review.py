import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date

from pydantic import ValidationError as PydanticValidationError
from rdflib import Graph

from praeco import Contributor, Organization, Person, RelatedIdentifier
from praeco.exceptions import ValidationError
from praeco.rdf_metadata import Candidate, IncompleteHarvestError
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest


class TestTextCandidates(unittest.TestCase):
    def test_title_and_description_aliases_keep_exact_evidence(self):
        for name, predicates in (
            (
                "title",
                (
                    "http://purl.org/dc/elements/1.1/title",
                    "http://purl.org/dc/terms/title",
                    "http://schema.org/name",
                    "https://schema.org/name",
                ),
            ),
            (
                "description",
                (
                    "http://purl.org/dc/elements/1.1/description",
                    "http://purl.org/dc/terms/description",
                    "http://schema.org/description",
                    "https://schema.org/description",
                ),
            ),
        ):
            for predicate in predicates:
                with self.subTest(name=name, predicate=predicate):
                    result = harvest(
                        f'<urn:s> <{predicate}> " Value "@en .', subject="urn:s"
                    )
                    review = getattr(result, name)
                    self.assertEqual(
                        (review.value, review.status, review.origin),
                        ("Value", "resolved", "automatic"),
                    )
                    self.assertEqual(
                        review.selection.evidence[0].triples,
                        (("<urn:s>", f"<{predicate}>", '" Value "@en'),),
                    )
                    self.assertEqual(review.observations, review.selection.evidence)

    def test_language_preferences_rank_without_discarding_alternatives(self):
        text = '<urn:s> <http://purl.org/dc/terms/title> "English"@en, "Deutsch"@de, "Untagged" .'
        cases = (
            ((), None),
            (("EN", None), "English"),
            ((None, "en"), "Untagged"),
            (("fr",), None),
            (("de", "en"), "Deutsch"),
        )
        for languages, expected in cases:
            with self.subTest(languages=languages):
                result = harvest(text, subject="urn:s", preferred_languages=languages)
                self.assertEqual(result.title.value, expected)
                self.assertEqual(len(result.title.candidates), 3)
                self.assertEqual(len(result.title.observations), 3)
                self.assertEqual(
                    result.title.status,
                    "unresolved" if expected is None else "resolved",
                )

    def test_equal_normalized_values_keep_all_language_and_alias_support(self):
        text = """<urn:s> <http://purl.org/dc/terms/title> " Title "@en, "Title"@de;
            <http://purl.org/dc/elements/1.1/title> "Title" ."""
        result = harvest(text, subject="urn:s")
        self.assertEqual(result.title.value, "Title")
        self.assertEqual(len(result.title.candidates), 1)
        self.assertEqual(len(result.title.selection.evidence), 3)
        graph = Graph().parse(data=text, format="turtle")
        reversed_graph = Graph()
        for triple in reversed(sorted(graph, key=str)):
            reversed_graph.add(triple)
        other = harvest(reversed_graph, subject="urn:s")
        self.assertEqual(result.title, other.title)
        self.assertEqual(result.diagnostics, other.diagnostics)

    def test_invalid_observations_are_unresolved_and_survive_completion(self):
        for obj in ('" "', "<urn:not-a-literal>", "[]"):
            with self.subTest(obj=obj):
                result = harvest(
                    f"<urn:s> <http://purl.org/dc/terms/title> {obj} .", subject="urn:s"
                )
                self.assertEqual(result.title.status, "unresolved")
                self.assertEqual(result.title.candidates, ())
                completed = result.with_overrides(
                    description="Description", creators=(Person(name="Jane"),)
                )
                with self.assertRaises(IncompleteHarvestError) as caught:
                    completed.to_publication_metadata()
                self.assertEqual(
                    tuple(d.field for d in caught.exception.diagnostics), ("title",)
                )
                reviewed = completed.with_overrides(title="Reviewed")
                self.assertEqual(reviewed.to_publication_metadata().title, "Reviewed")
                self.assertEqual(reviewed.title.observations, result.title.observations)

    def test_graph_changes_after_loading_do_not_change_extraction(self):
        graph = Graph().parse(
            data='<urn:s> <http://purl.org/dc/terms/title> "Original" .',
            format="turtle",
        )
        result = harvest(graph)
        graph.remove((None, None, None))
        self.assertEqual(result.select_subject("urn:s").title.value, "Original")


class TestReviewOperations(unittest.TestCase):
    def test_missing_required_fields_block_until_supplied(self):
        values = dict(
            title="Title", description="Description", creators=(Person(name="Jane"),)
        )
        for missing in values:
            with self.subTest(missing=missing):
                loaded = harvest("<urn:s> <urn:p> 1 .", subject="urn:s")
                incomplete = loaded.with_overrides(
                    **{k: v for k, v in values.items() if k != missing}
                )
                with self.assertRaises(IncompleteHarvestError) as caught:
                    incomplete.to_publication_metadata()
                self.assertIsInstance(caught.exception, ValidationError)
                self.assertEqual(
                    tuple(d.field for d in caught.exception.diagnostics), (missing,)
                )
                complete = incomplete.with_overrides(**{missing: values[missing]})
                metadata = complete.to_publication_metadata()
                self.assertEqual(
                    (metadata.title, metadata.description, metadata.creators),
                    ("Title", "Description", values["creators"]),
                )
                self.assertEqual(loaded.title.status, "missing")

    def test_selection_and_equal_override_have_distinct_origins(self):
        text = """<urn:s> <http://purl.org/dc/terms/title> "A", "B";
            <http://purl.org/dc/terms/description> "C", "D" ."""
        original = harvest(text, subject="urn:s")
        candidate = original.title.candidates[0]
        selected = original.select_candidate(candidate)
        overridden = original.with_overrides(title=candidate.value)
        self.assertEqual(selected.title.value, overridden.title.value)
        self.assertEqual(selected.title.origin, "selection")
        self.assertIs(selected.title.selection, candidate)
        self.assertEqual(overridden.title.origin, "override")
        self.assertIsNone(overridden.title.selection)
        self.assertEqual(selected.title.observations, overridden.title.observations)
        self.assertEqual(selected.title.candidates, original.title.candidates)
        self.assertEqual(original.title.status, "unresolved")
        with self.assertRaises(IncompleteHarvestError):
            selected.with_overrides(
                creators=(Person(name="Jane"),)
            ).to_publication_metadata()
        completed = selected.with_overrides(
            description="Reviewed", creators=(Person(name="Jane"),)
        )
        self.assertEqual(completed.to_publication_metadata().title, candidate.value)
        self.assertEqual(
            completed.select_subject("urn:s").description.origin, "override"
        )

    def test_records_remain_valid_across_review_copies_only_in_same_context(self):
        text = '<urn:s> <http://purl.org/dc/terms/title> "A", "B" . <urn:other> <http://purl.org/dc/terms/title> "Other" .'
        loaded = harvest(text)
        result = loaded.select_subject("urn:s")
        candidate = result.title.candidates[0]
        self.assertEqual(
            result.with_overrides(description="D")
            .select_candidate(candidate)
            .title.value,
            "A",
        )
        other_subject = loaded.select_subject("urn:other")
        foreign = harvest(text, subject="urn:s")
        for invalid in (
            foreign.title.candidates[0],
            other_subject.title.candidates[0],
            replace(candidate, value="invented"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                result.select_candidate(invalid)
        for invalid in (
            "A",
            Candidate("keywords", "word", ()),
            Candidate("unknown", "value", ()),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                result.select_candidate(invalid)

    def test_review_requires_a_selected_subject(self):
        result = harvest("<urn:s> <urn:p> 1 .")
        with self.assertRaises(IncompleteHarvestError) as caught:
            result.to_publication_metadata()
        self.assertEqual(caught.exception.diagnostics, result.diagnostics)
        for operation in (
            lambda: result.with_overrides(title="T"),
            lambda: result.clear("doi"),
            lambda: result.select_candidate(Candidate("title", "T", ())),
        ):
            with self.assertRaisesRegex(ValidationError, "select a valid subject"):
                operation()

    def test_all_neutral_override_fields_survive_conversion(self):
        person = Person(name="Jane")
        organization = Organization(name="Lab", identifier="urn:lab")
        contributor = Contributor(person=Person(name="Curator"), role="DataCurator")
        related = RelatedIdentifier(identifier="10.1234/other", relation="cites")
        original = harvest("<urn:s> <urn:p> 1 .", subject="urn:s")
        result = original.with_overrides(
            title=" T ",
            description=" D ",
            creators=(person, organization),
            publication_date=date(2020, 1, 2),
            contributors=(contributor,),
            keywords=(" word ",),
            license=" urn:license ",
            doi=" 10.1234/test ",
            version=" 1 ",
            language=" en ",
            related_identifiers=(related,),
        )
        person.name = "Changed"
        organization.name = "Changed"
        contributor.person.name = "Changed"
        related.identifier = "Changed"
        result.creators.value[0].name = "Returned change"
        result.creators.value[1].name = "Returned change"
        result.contributors.value[0].person.name = "Returned change"
        result.related_identifiers.value[0].identifier = "Returned change"
        metadata = result.to_publication_metadata()
        self.assertEqual(tuple(c.name for c in metadata.creators), ("Jane", "Lab"))
        self.assertIsInstance(metadata.creators[1], Organization)
        self.assertEqual(metadata.contributors[0].person.name, "Curator")
        self.assertEqual(metadata.related_identifiers[0].identifier, "10.1234/other")
        self.assertEqual((metadata.title, metadata.description), ("T", "D"))
        for name, expected in (
            ("publication_date", date(2020, 1, 2)),
            ("keywords", ("word",)),
            ("license", "urn:license"),
            ("doi", "10.1234/test"),
            ("version", "1"),
            ("language", "en"),
        ):
            with self.subTest(name=name):
                self.assertEqual(getattr(metadata, name), expected)
                self.assertEqual(getattr(result, name).value, expected)
        metadata.creators[0].name = "Converted change"
        self.assertEqual(result.creators.value[0].name, "Jane")
        self.assertEqual(original.creators.value, ())
        with self.assertRaises(FrozenInstanceError):
            result.title.value = "Mutation"

    def test_clearing_and_empty_overrides_are_explicit_exclusion(self):
        result = harvest("<urn:s> <urn:p> 1 .", subject="urn:s").with_overrides(
            title="T",
            description="D",
            creators=(Person(name="Jane"),),
            publication_date=date(2020, 1, 2),
            keywords=("a",),
        )
        for name, empty in (("publication_date", None), ("keywords", ())):
            with self.subTest(name=name):
                cleared = result.clear(name)
                overridden = result.with_overrides(**{name: empty})
                self.assertEqual(getattr(cleared, name), getattr(overridden, name))
                self.assertEqual(
                    getattr(cleared.to_publication_metadata(), name), empty
                )
                self.assertEqual(getattr(cleared, name).origin, "exclusion")
                self.assertEqual(getattr(result, name).status, "resolved")
        self.assertEqual(
            result.with_overrides().to_publication_metadata(),
            result.to_publication_metadata(),
        )
        for name in ("title", "description", "creators", "unknown"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                result.clear(name)

    def test_invalid_overrides_fail_visibly_and_leave_the_harvest_unchanged(self):
        result = harvest("<urn:s> <urn:p> 1 .", subject="urn:s")
        with self.assertRaisesRegex(ValidationError, "unknown metadata"):
            result.with_overrides(unknown="value")
        for changes in (
            dict(title=" "),
            dict(description=""),
            dict(creators=()),
            dict(creators=({"name": "Jane", "orcid": 123},)),
            dict(publication_date="2020"),
            dict(keywords=(" ",)),
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(PydanticValidationError),
            ):
                result.with_overrides(**changes)
        person = Person(name="Jane")
        with self.assertRaises(PydanticValidationError):
            person.name = ""
        with self.assertRaises(PydanticValidationError):
            result.with_overrides(creators=(person,))
        valid_dict = result.with_overrides(creators=({"name": "Jane"},))
        self.assertEqual(valid_dict.creators.value[0].name, "Jane")
        self.assertEqual(result.creators.value, ())
