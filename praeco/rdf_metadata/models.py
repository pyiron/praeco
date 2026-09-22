"""Immutable inspection records for local RDF metadata harvesting."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from typing import Generic, Literal, TypedDict, TypeVar

from rdflib import BNode, URIRef
from rdflib import Literal as RdfLiteral

from praeco.exceptions import ValidationError
from praeco.metadata import Contributor, Organization, Person, RelatedIdentifier

FieldName = Literal[
    "title",
    "description",
    "creators",
    "publication_date",
    "contributors",
    "keywords",
    "license",
    "doi",
    "version",
    "language",
    "related_identifiers",
]
OptionalField = Literal[
    "publication_date",
    "contributors",
    "keywords",
    "license",
    "doi",
    "version",
    "language",
    "related_identifiers",
]
Status = Literal["missing", "unresolved", "resolved", "excluded"]
Origin = Literal["automatic", "selection", "acceptance", "override", "exclusion"]
FIELD_NAMES: tuple[FieldName, ...] = (
    "title",
    "description",
    "creators",
    "publication_date",
    "contributors",
    "keywords",
    "license",
    "doi",
    "version",
    "language",
    "related_identifiers",
)
OPTIONAL_FIELDS: tuple[OptionalField, ...] = (
    "publication_date",
    "contributors",
    "keywords",
    "license",
    "doi",
    "version",
    "language",
    "related_identifiers",
)
T = TypeVar("T", covariant=True)


class MetadataOverrides(TypedDict, total=False):
    title: str
    description: str
    creators: tuple[Person | Organization, ...]
    publication_date: date | None
    contributors: tuple[Contributor, ...]
    keywords: tuple[str, ...]
    license: str | None
    doi: str | None
    version: str | None
    language: str | None
    related_identifiers: tuple[RelatedIdentifier, ...]


@dataclass(frozen=True)
class Evidence:
    """A named extraction rule and its supporting triples as full N3 terms."""

    rule: str
    triples: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class Candidate(Generic[T]):
    """A normalized observation; evidence retains every original RDF term."""

    field: FieldName
    value: T
    evidence: tuple[Evidence, ...]
    _context: object = dc_field(default_factory=object, repr=False, compare=False)
    _subject: URIRef | BNode | None = dc_field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Suggestion(Generic[T]):
    """A weaker or derived value that requires explicit acceptance."""

    field: FieldName
    value: T
    evidence: tuple[Evidence, ...]
    _context: object = dc_field(default_factory=object, repr=False, compare=False)
    _subject: URIRef | BNode | None = dc_field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class FieldReview(Generic[T]):
    """One field's source observations and current review decision."""

    field: FieldName
    value: T | None = None
    status: Status = "missing"
    origin: Origin | None = None
    candidates: tuple[Candidate[T], ...] = ()
    suggestions: tuple[Suggestion[T], ...] = ()
    selection: Candidate[T] | Suggestion[T] | None = None
    observations: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class CreatorReview:
    """Reviewed creators; mutable neutral values are copied on public access."""

    value: tuple[Person | Organization, ...] = ()
    status: Status = "missing"
    origin: Origin | None = None


@dataclass(frozen=True)
class SubjectRecord:
    """An inspectable subject belonging to one loaded source."""

    term: URIRef | BNode
    labels: tuple[RdfLiteral, ...]
    types: tuple[URIRef, ...]
    evidence: tuple[Evidence, ...]
    _context: object = dc_field(default_factory=object, repr=False, compare=False)


@dataclass(frozen=True)
class Diagnostic:
    """An explanation of review state, with a stable machine-readable code."""

    code: str
    field: FieldName | None
    subject: URIRef | BNode | None
    message: str
    blocking: bool
    evidence: tuple[Evidence, ...] = ()


class IncompleteHarvestError(ValidationError):
    """Conversion was requested while publication review is incomplete."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]):
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


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
