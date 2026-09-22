"""Bounded direct RDF mappings, without remote imports or reasoning."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from typing import Literal as TypeLiteral
from typing import TypeVar, cast

from rdflib import (
    DC,
    DCAT,
    DCTERMS,
    FOAF,
    PROV,
    RDF,
    RDFS,
    SKOS,
    XSD,
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
    Suggestion,
)


def schema(local: str) -> tuple[URIRef, URIRef]:
    return URIRef("http://schema.org/" + local), URIRef("https://schema.org/" + local)


TEXT_PREDICATES: dict[FieldName, tuple[URIRef, ...]] = {
    "title": (DC.title, DCTERMS.title, *schema("name")),
    "description": (DC.description, DCTERMS.description, *schema("description")),
    "language": (DC.language, DCTERMS.language, *schema("inLanguage")),
}
_VALUE = TypeVar("_VALUE", str, date)
_Term = URIRef | BNode | Literal
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
    return _scalar_field(graph, subject, name, predicates, languages, context, _text)


def _text(term: _Term) -> str | None:
    return str(term).strip() or None if isinstance(term, Literal) else None


def _license(term: _Term) -> str | None:
    return str(term).strip() or None if isinstance(term, (Literal, URIRef)) else None


def _doi(term: _Term) -> str | None:
    value = _license(term)
    if value is None:
        return None
    value = re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", value, flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def _date(term: _Term) -> date | None:
    if not isinstance(term, Literal):
        return None
    if term.datatype in (XSD.date, XSD.dateTime):
        parsed = term.toPython()
        if isinstance(parsed, datetime):
            return parsed.date()
        return parsed if isinstance(parsed, date) else None
    if term.datatype not in (None, XSD.string) or not re.match(
        r"^\d{4}-\d{2}-\d{2}(?:$|[Tt ])", str(term).strip()
    ):
        return None
    try:
        return datetime.fromisoformat(str(term).strip()).date()
    except ValueError:
        return None


def _scalar_field(
    graph: Graph,
    subject: URIRef | BNode,
    name: FieldName,
    predicates: tuple[URIRef, ...],
    languages: tuple[str | None, ...],
    context: object,
    normalize: Callable[[_Term], _VALUE | None],
    *,
    ignore_invalid: bool = False,
) -> FieldReview[_VALUE]:
    """Group normalized values without discarding languages or duplicate support."""
    observed: list[Evidence] = []
    groups: dict[_VALUE, list[tuple[_Term, Evidence]]] = {}
    invalid = False
    for predicate in predicates:
        for obj in sorted(
            graph.objects(subject, predicate), key=lambda node: node.n3()
        ):
            term = cast(_Term, obj)
            value = normalize(term)
            rule = "unmapped_identifier" if name == "doi" and value is None else name
            evidence = Evidence(rule, ((subject.n3(), predicate.n3(), obj.n3()),))
            observed.append(evidence)
            if value is not None:
                groups.setdefault(value, []).append((term, evidence))
            else:
                invalid = not ignore_invalid
    ranked: list[tuple[Candidate[_VALUE], int]] = []
    for value, support in sorted(groups.items()):
        ranks: list[int] = []
        for literal, _ in support:
            lang = (
                literal.language.lower()
                if isinstance(literal, Literal) and literal.language
                else None
            )
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
            else "unresolved" if ranked or invalid else "missing"
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
    text_fields: tuple[FieldReview[object], ...] = tuple(
        literal_field(graph, subject, name, predicates, languages, context)
        for name, predicates in TEXT_PREDICATES.items()
    )
    license_review = _scalar_field(
        graph,
        subject,
        "license",
        (DCTERMS.license, *schema("license")),
        languages,
        context,
        _license,
    )
    doi = _scalar_field(
        graph,
        subject,
        "doi",
        (DCTERMS.identifier, *schema("identifier")),
        languages,
        context,
        _doi,
        ignore_invalid=True,
    )
    published = _scalar_field(
        graph,
        subject,
        "publication_date",
        (DCTERMS.issued, *schema("datePublished")),
        (),
        context,
        _date,
    )
    weaker = _scalar_field(
        graph,
        subject,
        "publication_date",
        (DCTERMS.created, DC.date, DCTERMS.date, *schema("dateCreated")),
        (),
        context,
        _date,
        ignore_invalid=True,
    )
    published = replace(
        published,
        suggestions=tuple(
            Suggestion("publication_date", item.value, item.evidence, context, subject)
            for item in weaker.candidates
        ),
        observations=tuple(
            sorted(
                (*published.observations, *weaker.observations), key=lambda e: e.triples
            )
        ),
    )
    words = literal_field(
        graph,
        subject,
        "keywords",
        (DCTERMS.subject, DCAT.keyword, *schema("keywords")),
        (),
        context,
    )
    keyword_value = tuple(item.value for item in words.candidates)
    keyword_evidence = tuple(
        sorted(
            (e for item in words.candidates for e in item.evidence),
            key=lambda e: e.triples,
        )
    )
    keyword_candidate = Candidate(
        "keywords", keyword_value, keyword_evidence, context, subject
    )
    # Distinct keywords form a collection, not competing scalar values.
    complete = bool(keyword_value) and len(keyword_evidence) == len(words.observations)
    keywords = FieldReview(
        "keywords",
        value=keyword_value if complete else None,
        status="resolved" if complete else words.status,
        origin="automatic" if complete else None,
        candidates=(keyword_candidate,) if keyword_value else (),
        selection=keyword_candidate if complete else None,
        observations=words.observations,
    )
    return (*text_fields, license_review, doi, published, keywords)


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
    observations: list[CreatorObservation] = []
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
