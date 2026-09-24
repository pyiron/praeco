import unittest

from rdflib import BNode, Graph, URIRef

from praeco import Organization, Person
from praeco.exceptions import ValidationError
from praeco.rdf_metadata import IncompleteHarvestError
from praeco.rdf_metadata import harvest_publication_metadata_from_rdf as harvest

PREFIXES = """
@prefix dct: <http://purl.org/dc/terms/> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""


class TestCreators(unittest.TestCase):
    def test_literal_creator_aliases_use_the_documented_person_convention(self):
        for predicate in (
            "http://purl.org/dc/elements/1.1/creator",
            "http://purl.org/dc/terms/creator",
            "http://schema.org/creator",
            "https://schema.org/creator",
        ):
            with self.subTest(predicate=predicate):
                result = harvest(
                    f'<urn:s> <{predicate}> " Jane Doe "@en .', subject="urn:s"
                )
                self.assertEqual(result.creators.value, (Person(name="Jane Doe"),))
                observation = result.creators.observations[0]
                self.assertEqual(observation.term.n3(), '" Jane Doe "@en')
                self.assertEqual(
                    observation.name_candidates[0].evidence[0].triples,
                    (("<urn:s>", f"<{predicate}>", '" Jane Doe "@en'),),
                )
                self.assertEqual(result.creators.status, "resolved")

    def test_explicit_agent_type_aliases_classify_people_and_organizations(self):
        for kind, namespace in (
            (kind, namespace)
            for kind in ("Person", "Organization")
            for namespace in (
                "http://xmlns.com/foaf/0.1/",
                "http://www.w3.org/ns/prov#",
                "http://schema.org/",
                "https://schema.org/",
            )
        ):
            with self.subTest(kind=kind, namespace=namespace):
                text = (
                    PREFIXES
                    + f'<urn:s> dct:creator <urn:agent> . <urn:agent> a <{namespace}{kind}>; foaf:name "Name" .'
                )
                result = harvest(text, subject="urn:s")
                creator = result.creators.value[0]
                self.assertIsInstance(
                    creator, Person if kind == "Person" else Organization
                )
                if kind == "Organization":
                    self.assertEqual(creator.identifier, "urn:agent")
                self.assertEqual(creator.name, "Name")
                self.assertTrue(
                    any(
                        e.rule == "agent_type"
                        for e in result.creators.observations[0].evidence
                    )
                )

    def test_name_aliases_and_language_alternatives_are_retained(self):
        for predicate in (
            "http://www.w3.org/2000/01/rdf-schema#label",
            "http://www.w3.org/2004/02/skos/core#prefLabel",
            "http://xmlns.com/foaf/0.1/name",
            "http://schema.org/name",
            "https://schema.org/name",
        ):
            with self.subTest(predicate=predicate):
                text = (
                    PREFIXES
                    + f'<urn:s> dct:creator <urn:p> . <urn:p> a foaf:Person; <{predicate}> "English"@en, "Deutsch"@de .'
                )
                result = harvest(text, subject="urn:s", preferred_languages=("EN",))
                self.assertEqual(result.creators.value[0].name, "English")
                self.assertEqual(
                    len(result.creators.observations[0].name_candidates), 2
                )
                with self.assertRaises(ValidationError):
                    result.select_candidate(
                        result.creators.observations[0].name_candidates[0]
                    )

    def test_partial_creator_lists_block_until_full_reviewed_replacement(self):
        cases = (
            ("<urn:p>", "<urn:p> a foaf:Person ."),
            ("<urn:p>", '<urn:p> a foaf:Person; foaf:name "A", "B" .'),
            ("<urn:p>", '<urn:p> a foaf:Person; foaf:name " " .'),
            ('" "', ""),
        )
        for agent, facts in cases:
            with self.subTest(agent=agent, facts=facts):
                text = (
                    PREFIXES
                    + f'<urn:s> dct:title "T"; dct:description "D"; dct:creator "Jane", {agent} . {facts}'
                )
                original = harvest(text, subject="urn:s")
                self.assertEqual(original.creators.value, (Person(name="Jane"),))
                self.assertEqual(len(original.creators.observations), 2)
                self.assertEqual(original.creators.status, "unresolved")
                with self.assertRaises(IncompleteHarvestError) as caught:
                    original.to_publication_metadata()
                self.assertEqual(
                    caught.exception.diagnostics[0].code, "unresolved_creator"
                )
                excluded = original.with_overrides(creators=(Person(name="Jane"),))
                self.assertEqual(
                    excluded.to_publication_metadata().creators, (Person(name="Jane"),)
                )
                completed = original.with_overrides(
                    creators=(Person(name="Jane"), Organization(name="Reviewed Lab"))
                )
                self.assertEqual(len(completed.to_publication_metadata().creators), 2)
                self.assertEqual(
                    completed.creators.observations, original.creators.observations
                )
                self.assertEqual(
                    excluded.creators.observations, original.creators.observations
                )
                self.assertEqual(original.creators.status, "unresolved")

    def test_unknown_and_conflicting_kinds_require_review(self):
        for types, expected in (
            ("", "unknown"),
            ("a prov:Agent;", "unknown"),
            ("a foaf:Person, foaf:Organization;", "conflicting"),
        ):
            with self.subTest(types=types):
                text = (
                    PREFIXES
                    + f'<urn:s> dct:title "T"; dct:description "D"; dct:creator <urn:p> . <urn:p> {types} foaf:name "Name" .'
                )
                result = harvest(text, subject="urn:s")
                self.assertEqual(result.creators.observations[0].kind, expected)
                self.assertEqual(result.creators.value, ())
                with self.assertRaises(IncompleteHarvestError):
                    result.to_publication_metadata()
                self.assertEqual(
                    result.with_overrides(creators=(Organization(name="Name"),))
                    .to_publication_metadata()
                    .creators,
                    (Organization(name="Name"),),
                )

    def test_software_types_never_become_publication_creators(self):
        for rdf_type in (
            "http://www.w3.org/ns/prov#SoftwareAgent",
            "http://schema.org/SoftwareApplication",
            "https://schema.org/SoftwareApplication",
            "http://schema.org/SoftwareSourceCode",
            "https://schema.org/SoftwareSourceCode",
        ):
            with self.subTest(rdf_type=rdf_type):
                text = (
                    PREFIXES
                    + f'<urn:s> dct:creator <urn:software> . <urn:software> a <{rdf_type}>, foaf:Person; foaf:name "Software" .'
                )
                result = harvest(text, subject="urn:s")
                self.assertEqual(result.creators.observations[0].kind, "software")
                self.assertEqual(result.creators.value, ())
                with self.assertRaises(IncompleteHarvestError):
                    result.with_overrides(
                        title="T", description="D"
                    ).to_publication_metadata()

    def test_attribution_is_visible_but_does_not_assert_authorship(self):
        for agent in ("<urn:p>", '"Not a linked agent"'):
            with self.subTest(agent=agent):
                text = (
                    PREFIXES
                    + f'<urn:s> dct:title "T"; dct:description "D"; dct:creator "Jane"; prov:wasAttributedTo {agent} . <urn:p> a foaf:Person; foaf:name "Other" .'
                )
                result = harvest(text, subject="urn:s")
                self.assertEqual(
                    result.to_publication_metadata().creators, (Person(name="Jane"),)
                )
                self.assertEqual(len(result.creators.observations), 2)
                diagnostic = result.diagnostics[0]
                self.assertEqual(diagnostic.code, "attribution_requires_review")
                self.assertFalse(diagnostic.blocking)
        only_attributed = harvest(
            PREFIXES
            + '<urn:s> prov:wasAttributedTo <urn:p> . <urn:p> a foaf:Person; foaf:name "Name" .',
            subject="urn:s",
        )
        self.assertEqual(only_attributed.creators.status, "missing")
        self.assertEqual(only_attributed.creators.value, ())

    def test_participation_and_subclass_assertions_do_not_infer_authorship(self):
        text = PREFIXES + """
        <urn:s> prov:wasGeneratedBy <urn:process> .
        <urn:process> prov:wasAssociatedWith <urn:operator> .
        <urn:operator> a foaf:Person; foaf:name "Operator" .
        <urn:subclass> rdfs:subClassOf foaf:Person .
        <urn:other> dct:creator <urn:custom> .
        <urn:custom> a <urn:subclass>; foaf:name "Custom" .
        """
        result = harvest(text, subject="urn:s")
        self.assertEqual(result.creators.observations, ())
        other = harvest(text, subject="urn:other")
        self.assertEqual(other.creators.observations[0].kind, "unknown")

    def test_repeated_agent_links_and_duplicate_name_support_are_preserved(self):
        text = PREFIXES + """
        <urn:s> dc:creator <urn:p>; dct:creator <urn:p>; prov:wasAttributedTo <urn:p> .
        <urn:p> a foaf:Person, <urn:unrecognized>; foaf:name "Name"; rdfs:label " Name " .
        """
        result = harvest(text, subject="urn:s")
        self.assertEqual(len(result.creators.value), 1)
        self.assertEqual(len(result.creators.observations), 1)
        observation = result.creators.observations[0]
        self.assertEqual(observation.relations, ("attribution", "creator"))
        self.assertEqual(len(observation.evidence), 7)
        self.assertEqual(len(observation.name_candidates), 1)
        self.assertEqual(len(observation.name_candidates[0].evidence), 2)
        graph = Graph().parse(data=text, format="turtle")
        reordered = Graph()
        for triple in reversed(sorted(graph, key=str)):
            reordered.add(triple)
        self.assertEqual(result.creators, harvest(reordered, subject="urn:s").creators)

    def test_orcid_resource_normalizes_without_losing_original_identity(self):
        uri = "http://orcid.org/0000-0002-1825-0097"
        text = (
            PREFIXES
            + f'<urn:s> dct:creator <{uri}> . <{uri}> a foaf:Person; foaf:name "Name" .'
        )
        result = harvest(text, subject="urn:s")
        self.assertEqual(result.creators.value[0].orcid, uri.replace("http:", "https:"))
        observation = result.creators.observations[0]
        self.assertEqual(observation.term, URIRef(uri))
        self.assertEqual(observation.identifier, uri)
        self.assertTrue(
            any(
                uri in term
                for e in observation.evidence
                for triple in e.triples
                for term in triple
            )
        )

    def test_blank_node_organization_never_publishes_its_node_label(self):
        text = (
            PREFIXES + '<urn:s> dct:creator [ a prov:Organization; foaf:name "Lab" ] .'
        )
        result = harvest(text, subject="urn:s")
        self.assertEqual(result.creators.value, (Organization(name="Lab"),))
        observation = result.creators.observations[0]
        self.assertIsInstance(observation.term, BNode)
        self.assertIsNone(observation.identifier)
        self.assertIsNone(result.creators.value[0].identifier)
