"""Conservative assessment of publication subjects for automatic selection.

Every rule uses exact terms asserted on the subject itself; there is no
inference, and repeated types, titles, or translations never add weight.
"""

from __future__ import annotations

from collections.abc import Iterable

from rdflib import (
    CSVW,
    DC,
    DCAT,
    DCTERMS,
    OWL,
    PROV,
    RDF,
    VOID,
    BNode,
    Graph,
    Literal,
    URIRef,
)
from rdflib.term import Node

from praeco.rdf_metadata.extraction import TEXT_PREDICATES, schema
from praeco.rdf_metadata.models import Evidence, SubjectCandidate, SubjectRecord

PUBLICATION_TYPES = frozenset(
    (DCAT.Dataset, *schema("Dataset"), VOID.Dataset, OWL.Ontology)
)
STRUCTURAL_TYPES = frozenset(
    (
        CSVW.Cell,
        CSVW.Column,
        CSVW.Datatype,
        CSVW.Dialect,
        CSVW.Direction,
        CSVW.ForeignKey,
        CSVW.NumericFormat,
        CSVW.Row,
        CSVW.Schema,
        CSVW.Table,
        CSVW.TableGroup,
        CSVW.TableReference,
        CSVW.Transformation,
        DCAT.Distribution,
        *schema("DataDownload"),
    )
)
STRUCTURAL_PROPERTIES = (CSVW.url, CSVW.tableSchema)
# The decision table's own agent links, independent of creator extraction.
_AGENT_LINKS = (
    DC.creator,
    DCTERMS.creator,
    *schema("creator"),
    PROV.wasAttributedTo,
)
_Triple = tuple[Node, Node, Node]


def _evidence(rule: str, triples: Iterable[_Triple]) -> Evidence:
    return Evidence(
        rule,
        tuple(
            sorted((s.n3(), p.n3(), o.n3()) for s, p, o in triples),
        ),
    )


def _typed(
    graph: Graph, term: URIRef | BNode, types: frozenset[URIRef]
) -> list[_Triple]:
    return [
        (term, RDF.type, obj) for obj in graph.objects(term, RDF.type) if obj in types
    ]


def _linked(
    graph: Graph, term: URIRef | BNode, predicates: tuple[URIRef, ...]
) -> list[_Triple]:
    return [
        (term, predicate, obj)
        for predicate in predicates
        for obj in graph.objects(term, predicate)
    ]


def assess_subjects(
    graph: Graph, subjects: tuple[SubjectRecord, ...]
) -> tuple[SubjectCandidate, ...]:
    """Apply the decision table to publication-typed and attributed entities.

    Candidates keep the order of ``subjects``. Each applied rule contributes one
    evidence entry; structural rules override publication and entity types.
    """
    # Index lookups keep the cost proportional to the typed resources.
    typed = {
        term
        for rdf_type in (*PUBLICATION_TYPES, PROV.Entity)
        for term in graph.subjects(RDF.type, rdf_type)
    }
    candidates: list[SubjectCandidate] = []
    for record in subjects:
        term = record.term
        if term not in typed:
            continue
        publication = _typed(graph, term, PUBLICATION_TYPES)
        titles = [
            triple
            for triple in _linked(graph, term, TEXT_PREDICATES["title"])
            if isinstance(triple[2], Literal) and str(triple[2]).strip()
        ]
        entity = _typed(graph, term, frozenset((PROV.Entity,)))
        agents = _linked(graph, term, _AGENT_LINKS)
        attributed_entity = bool(entity and titles and agents)
        if not publication and not attributed_entity:
            continue
        structural = _typed(graph, term, STRUCTURAL_TYPES)
        properties = _linked(graph, term, STRUCTURAL_PROPERTIES)
        applied = (
            ("publication_type", publication),
            ("publication_title", titles),
            ("entity_type", entity if attributed_entity else []),
            ("entity_agent", agents if attributed_entity else []),
            ("structural_type", structural),
            ("structural_property", properties),
        )
        candidates.append(
            SubjectCandidate(
                subject=record,
                eligible=bool(publication and titles)
                and not structural
                and not properties,
                evidence=tuple(
                    _evidence(rule, triples) for rule, triples in applied if triples
                ),
            )
        )
    return tuple(candidates)
