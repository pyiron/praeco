"""Bounded direct RDF mappings, without remote imports or reasoning."""

from __future__ import annotations

from rdflib import DC, DCTERMS, BNode, Graph, Literal, URIRef

from praeco.rdf_metadata.models import Candidate, Evidence, FieldName, FieldReview


def schema(local: str) -> tuple[URIRef, URIRef]:
    return URIRef("http://schema.org/" + local), URIRef("https://schema.org/" + local)


TEXT_PREDICATES: dict[FieldName, tuple[URIRef, ...]] = {
    "title": (DC.title, DCTERMS.title, *schema("name")),
    "description": (DC.description, DCTERMS.description, *schema("description")),
}


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
