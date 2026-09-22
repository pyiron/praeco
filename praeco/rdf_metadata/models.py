"""Immutable inspection records for local RDF metadata harvesting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rdflib import BNode, URIRef
from rdflib import Literal as RdfLiteral


@dataclass(frozen=True)
class Evidence:
    """A named extraction rule and its supporting triples as full N3 terms."""

    rule: str
    triples: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class SubjectRecord:
    """An inspectable subject belonging to one loaded source."""

    term: URIRef | BNode
    labels: tuple[RdfLiteral, ...]
    types: tuple[URIRef, ...]
    evidence: tuple[Evidence, ...]
    _context: object = field(default_factory=object, repr=False, compare=False)


@dataclass(frozen=True)
class Diagnostic:
    """An explanation of review state, with a stable machine-readable code."""

    code: str
    field: str | None
    subject: URIRef | BNode | None
    message: str
    blocking: bool
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class SourceInfo:
    """Source audit information; a Graph has no original-byte checksum."""

    kind: Literal["graph", "text", "bytes", "path"]
    serialization: Literal["turtle"] | None
    triple_count: int
    size_bytes: int | None
    sha256: str | None

    def matches_checksum(self, expected_sha256: str) -> bool | None:
        """Compare a hexadecimal digest, or return None when unavailable."""
        if self.sha256 is None:
            return None
        return self.sha256 == expected_sha256.strip().lower()
