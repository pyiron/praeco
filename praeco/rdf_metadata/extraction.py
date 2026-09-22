"""Bounded direct RDF mappings, without remote imports or reasoning."""

from __future__ import annotations

import re
from typing import Literal as TypeLiteral
from typing import cast

from rdflib import (
    DC,
    DCTERMS,
    FOAF,
    PROV,
    RDF,
    RDFS,
    SKOS,
    BNode,
    Graph,
    Literal,
    URIRef,
)

from praeco.metadata import Organization, Person
from praeco.rdf_metadata.models import (
    Candidate,
    CreatorObservation,
    CreatorReview,
    Evidence,
    FieldName,
    FieldReview,
)


def schema(local: str) -> tuple[URIRef, URIRef]:
    return URIRef("http://schema.org/" + local), URIRef("https://schema.org/" + local)


TEXT_PREDICATES: dict[FieldName, tuple[URIRef, ...]] = {
    "title": (DC.title, DCTERMS.title, *schema("name")),
    "description": (DC.description, DCTERMS.description, *schema("description")),
}
_CREATORS = (DC.creator, DCTERMS.creator, *schema("creator"))
_RELATION_RULES: tuple[tuple[TypeLiteral["creator", "attribution"], str], ...] = (
    ("attribution", "attribution"),
    ("creator", "creators"),
)
_NAMES = (RDFS.label, SKOS.prefLabel, FOAF.name, *schema("name"))
_PERSON_TYPES = frozenset((FOAF.Person, PROV.Person, *schema("Person")))
_ORGANIZATION_TYPES = frozenset(
    (FOAF.Organization, PROV.Organization, *schema("Organization"))
)
_SOFTWARE_TYPES = frozenset(
    (PROV.SoftwareAgent, *schema("SoftwareApplication"), *schema("SoftwareSourceCode"))
)


def literal_field(
    graph: Graph,
    subject: URIRef | BNode,
    name: FieldName,
    predicates: tuple[URIRef, ...],
    languages: tuple[str | None, ...],
    context: object,
) -> FieldReview[str]:
    """Group normalized text without discarding languages or duplicate support."""
    observed = []
    groups: dict[str, list[tuple[Literal, Evidence]]] = {}
    invalid = False
    for predicate in predicates:
        for obj in sorted(
            graph.objects(subject, predicate), key=lambda node: node.n3()
        ):
            evidence = Evidence(name, ((subject.n3(), predicate.n3(), obj.n3()),))
            observed.append(evidence)
            if isinstance(obj, Literal) and str(obj).strip():
                groups.setdefault(str(obj).strip(), []).append((obj, evidence))
            else:
                invalid = True
    ranked = []
    for value, support in sorted(groups.items()):
        ranks = []
        for literal, _ in support:
            lang = literal.language.lower() if literal.language else None
            ranks.append(languages.index(lang) if lang in languages else len(languages))
        candidate = Candidate(
            name,
            value,
            tuple(sorted((e for _, e in support), key=lambda e: e.triples)),
            context,
            subject,
        )
        ranked.append((candidate, min(ranks)))
    best = min((rank for _, rank in ranked), default=0)
    choices = [candidate for candidate, rank in ranked if rank == best]
    selected = choices[0] if len(choices) == 1 and not invalid else None
    return FieldReview(
        name,
        value=None if selected is None else selected.value,
        status=(
            "resolved"
            if selected is not None
            else "unresolved" if observed else "missing"
        ),
        origin="automatic" if selected is not None else None,
        candidates=tuple(candidate for candidate, _ in ranked),
        selection=selected,
        observations=tuple(sorted(observed, key=lambda e: e.triples)),
    )


def extract_fields(
    graph: Graph,
    subject: URIRef | BNode,
    languages: tuple[str | None, ...],
    context: object,
) -> tuple[FieldReview[object], ...]:
    return tuple(
        literal_field(graph, subject, name, predicates, languages, context)
        for name, predicates in TEXT_PREDICATES.items()
    )


def extract_creators(
    graph: Graph,
    subject: URIRef | BNode,
    languages: tuple[str | None, ...],
    context: object,
) -> CreatorReview:
    """Keep every direct creator, including agents that cannot yet be published."""
    links: dict[URIRef | BNode | Literal, list[Evidence]] = {}
    for predicate in (*_CREATORS, PROV.wasAttributedTo):
        for node in graph.objects(subject, predicate):
            term = cast(URIRef | BNode | Literal, node)
            rule = "attribution" if predicate == PROV.wasAttributedTo else "creators"
            links.setdefault(term, []).append(
                Evidence(rule, ((subject.n3(), predicate.n3(), term.n3()),))
            )
    observations = []
    creators: list[Person | Organization] = []
    direct = 0
    for term, support in sorted(links.items(), key=lambda item: item[0].n3()):
        relations: tuple[TypeLiteral["creator", "attribution"], ...] = tuple(
            relation
            for relation, rule in _RELATION_RULES
            if any(item.rule == rule for item in support)
        )
        evidence = tuple(sorted(support, key=lambda item: item.triples))
        if isinstance(term, Literal):
            name = str(term).strip() or None
            candidates = (
                ()
                if name is None
                else (Candidate("creators", name, evidence, context, subject),)
            )
            observation = CreatorObservation(
                term,
                "person" if "creator" in relations else "unknown",
                (),
                name,
                candidates,
                None,
                None,
                relations,
                evidence,
            )
        else:
            types = tuple(
                sorted(
                    {t for t in graph.objects(term, RDF.type) if isinstance(t, URIRef)}
                )
            )
            names = literal_field(graph, term, "creators", _NAMES, languages, context)
            type_evidence = tuple(
                Evidence("agent_type", ((term.n3(), RDF.type.n3(), t.n3()),))
                for t in sorted(
                    graph.objects(term, RDF.type), key=lambda node: node.n3()
                )
            )
            identifier = str(term) if isinstance(term, URIRef) else None
            orcid_match = re.fullmatch(
                r"https?://orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])/?",
                identifier or "",
                flags=re.IGNORECASE,
            )
            orcid = (
                None
                if orcid_match is None
                else "https://orcid.org/" + orcid_match[1].upper()
            )
            kind: TypeLiteral[
                "person", "organization", "software", "unknown", "conflicting"
            ]
            if _SOFTWARE_TYPES.intersection(types):
                kind = "software"
            elif _PERSON_TYPES.intersection(types) and _ORGANIZATION_TYPES.intersection(
                types
            ):
                kind = "conflicting"
            elif _PERSON_TYPES.intersection(types):
                kind = "person"
            elif _ORGANIZATION_TYPES.intersection(types):
                kind = "organization"
            else:
                kind = "unknown"
            observation = CreatorObservation(
                term,
                kind,
                types,
                names.value,
                names.candidates,
                identifier,
                orcid,
                relations,
                tuple(
                    sorted(
                        (*evidence, *type_evidence, *names.observations),
                        key=lambda item: (item.rule, item.triples),
                    )
                ),
            )
        observations.append(observation)
        if "creator" in relations:
            direct += 1
            if observation._complete:
                if observation.kind == "person":
                    creators.append(
                        Person(name=observation.name, orcid=observation.orcid)
                    )
                else:
                    creators.append(
                        Organization(
                            name=cast(str, observation.name),
                            identifier=observation.identifier,
                        )
                    )
    return CreatorReview(
        tuple(creators),
        (
            "missing"
            if not direct
            else "resolved" if len(creators) == direct else "unresolved"
        ),
        "automatic" if creators else None,
        tuple(observations),
    )
