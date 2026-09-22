"""Explicit, local RDF publication metadata harvesting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Self

from rdflib import Graph, URIRef

from praeco.exceptions import ValidationError
from praeco.rdf_metadata.models import Diagnostic, SourceInfo, SubjectRecord
from praeco.rdf_metadata.source import LoadedSource, load_source


@dataclass(frozen=True)
class RdfMetadataHarvest:
    """A source snapshot with one explicitly selected publication subject."""

    _source: LoadedSource = field(repr=False, compare=False)
    _preferred_languages: tuple[str | None, ...] = field(repr=False)
    subject: SubjectRecord | None = None
    _requested_subject: URIRef | None = field(default=None, repr=False)

    @property
    def source(self) -> SourceInfo:
        return self._source.info

    @property
    def subjects(self) -> tuple[SubjectRecord, ...]:
        return self._source.subjects

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        if self.subject is not None:
            return ()
        if self._requested_subject is not None:
            return (
                Diagnostic(
                    "subject_not_found",
                    None,
                    self._requested_subject,
                    "The requested subject is absent from the source.",
                    True,
                ),
            )
        return (
            Diagnostic(
                "subject_required",
                None,
                None,
                "Select a publication subject before reviewing metadata.",
                True,
            ),
        )

    def select_subject(self, subject: SubjectRecord | str | URIRef) -> Self:
        """Resolve a missing selection; a selected publication stays fixed."""
        if isinstance(subject, SubjectRecord):
            if subject._context is not self._source.token:
                raise ValidationError("subject record belongs to another source")
            term = subject.term
        elif type(subject) is str or isinstance(subject, URIRef):
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]*", subject) is None:
                raise ValidationError("subject must be an absolute IRI")
            term = URIRef(subject)
        else:
            raise ValidationError("select an inspected SubjectRecord or supply an IRI")
        if self.subject is not None:
            if term != self.subject.term:
                raise ValidationError("subject is fixed; create a separate harvest")
            return self
        record = next((item for item in self.subjects if item.term == term), None)
        return replace(
            self,
            subject=record,
            _requested_subject=URIRef(term) if record is None else None,
        )


def harvest_publication_metadata_from_rdf(
    source: Graph | str | bytes | Path,
    *,
    subject: str | URIRef | None = None,
    preferred_languages: tuple[str | None, ...] = (),
) -> RdfMetadataHarvest:
    """Load local RDF; strings are Turtle content, never paths or URLs.

    Omit subject to inspect resources before selecting one. Anonymous subjects
    can be selected using the returned records, without reparsing the source.
    """
    if not isinstance(preferred_languages, tuple) or any(
        lang is not None and (not isinstance(lang, str) or not lang.strip())
        for lang in preferred_languages
    ):
        raise ValidationError(
            "preferred_languages must be a tuple of language tags or None"
        )
    languages = tuple(
        lang.lower() if lang is not None else None for lang in preferred_languages
    )
    result = RdfMetadataHarvest(load_source(source), languages)
    return result if subject is None else result.select_subject(subject)
