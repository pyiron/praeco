"""Local parsing and privately retained source snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal as TypeLiteral
from typing import cast

from rdflib import (
    DC,
    DCTERMS,
    FOAF,
    RDF,
    RDFS,
    SKOS,
    BNode,
    Dataset,
    Graph,
    Literal,
    URIRef,
)
from rdflib.plugins.parsers.notation3 import RDFSink, SinkParser

from praeco.exceptions import ValidationError
from praeco.rdf_metadata.models import Evidence, SourceInfo, SubjectRecord

_INLINE_BASE = "https://praeco.invalid/rdf/inline/"
_LABELS = frozenset(
    (
        DC.title,
        DCTERMS.title,
        RDFS.label,
        SKOS.prefLabel,
        FOAF.name,
        URIRef("http://schema.org/name"),
        URIRef("https://schema.org/name"),
    )
)


@dataclass(frozen=True)
class LoadedSource:
    """Internal context shared by reviewed copies; never expose its graph."""

    graph: Graph = field(repr=False, compare=False)
    info: SourceInfo
    subjects: tuple[SubjectRecord, ...]
    token: object = field(repr=False, compare=False)


class _LexicalRDFSink(RDFSink):
    """Keep typed literal spellings without changing RDFLib's global settings.

    RDFLib still applies datatype-specific whitespace handling (e.g. xsd:token)
    and parses Turtle numeric shorthand before this hook. This is not a
    byte-for-byte Turtle representation.
    """

    def newLiteral(self, s: str, dt: URIRef | None, lang: str | None) -> Literal:
        return Literal(s, datatype=dt, lang=lang, normalize=False)


def load_source(source: Graph | str | bytes | Path) -> LoadedSource:
    """Parse Turtle locally, or snapshot a caller's already parsed Graph.

    A supplied Graph retains its existing terms; lexical information already
    lost during the caller's parsing cannot be recovered.
    Dataset and other context-aware containers require the caller to select
    an individual graph.
    """
    if isinstance(source, Dataset):
        raise ValidationError(
            "Dataset input requires an explicit graph; pass "
            "dataset.default_graph or dataset.graph(identifier)"
        )
    if isinstance(source, Graph) and source.context_aware:
        raise ValidationError(
            "Context-aware graph input requires an explicit graph; "
            "pass an individual graph, such as "
            "conjunctive_graph.get_context(identifier)"
        )
    raw: bytes | None = None
    kind: TypeLiteral["graph", "text", "bytes", "path"]
    if isinstance(source, Graph):
        kind = "graph"
        graph = Graph(bind_namespaces="none")
        for triple in source:
            graph.add(triple)
    else:
        base = _INLINE_BASE
        try:
            if isinstance(source, Path):
                kind = "path"
                raw = source.read_bytes()
                base = source.resolve().as_uri()
            elif isinstance(source, bytes):
                kind, raw = "bytes", source
            elif isinstance(source, str):
                kind, raw = "text", source.encode("utf-8")
            else:
                raise ValidationError(
                    "source must be a Graph, Turtle str/bytes, or Path"
                )
        except (OSError, UnicodeError) as error:
            raise ValidationError("cannot read RDF source") from error
        graph = Graph()
        try:
            parser = SinkParser(_LexicalRDFSink(graph), baseURI=base, turtle=True)
            parser.loadBuf(raw)
        except Exception as error:
            raise ValidationError("source is not valid Turtle") from error

    info = SourceInfo(
        kind=kind,
        serialization=None if raw is None else "turtle",
        triple_count=len(graph),
        size_bytes=None if raw is None else len(raw),
        sha256=None if raw is None else hashlib.sha256(raw).hexdigest(),
    )
    token = object()
    records: list[SubjectRecord] = []
    for term in sorted(set(graph.subjects()), key=lambda node: node.n3()):
        triples = sorted(
            graph.triples((term, None, None)), key=lambda t: tuple(n.n3() for n in t)
        )
        labels = {
            obj
            for _, predicate, obj in triples
            if predicate in _LABELS and isinstance(obj, Literal)
        }
        types = {
            obj
            for _, predicate, obj in triples
            if predicate == RDF.type and isinstance(obj, URIRef)
        }
        records.append(
            SubjectRecord(
                term=cast(URIRef | BNode, term),
                labels=tuple(sorted(labels, key=lambda node: node.n3())),
                types=tuple(sorted(types)),
                evidence=(
                    Evidence(
                        "subject",
                        tuple((s.n3(), p.n3(), o.n3()) for s, p, o in triples),
                    ),
                ),
                _context=token,
            )
        )
    return LoadedSource(graph, info, tuple(records), token)
