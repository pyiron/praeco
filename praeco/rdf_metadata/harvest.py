"""Explicit, local RDF publication metadata harvesting."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Self, Unpack, cast

from rdflib import Graph, URIRef

from praeco.exceptions import ValidationError
from praeco.metadata import (
    Contributor,
    Organization,
    Person,
    PublicationMetadata,
    RelatedIdentifier,
)
from praeco.rdf_metadata.extraction import extract_creators, extract_fields
from praeco.rdf_metadata.models import (
    FIELD_NAMES,
    OPTIONAL_FIELDS,
    Candidate,
    CreatorReview,
    Diagnostic,
    FieldName,
    FieldReview,
    IncompleteHarvestError,
    MetadataOverrides,
    OptionalField,
    SourceInfo,
    SubjectRecord,
    Suggestion,
)
from praeco.rdf_metadata.source import LoadedSource, load_source


@dataclass(frozen=True)
class RdfMetadataHarvest:
    """A source snapshot with one explicitly selected publication subject."""

    _source: LoadedSource = field(repr=False, compare=False)
    _preferred_languages: tuple[str | None, ...] = field(repr=False)
    subject: SubjectRecord | None = None
    _requested_subject: URIRef | None = field(default=None, repr=False)
    _reviews: tuple[FieldReview[object], ...] = field(
        default_factory=lambda: tuple(
            FieldReview(name) for name in FIELD_NAMES if name != "creators"
        ),
        repr=False,
    )
    _creators: CreatorReview = field(default_factory=CreatorReview, repr=False)

    def _raw_field(self, name: FieldName) -> FieldReview[object]:
        return next(review for review in self._reviews if review.field == name)

    def _public_field(self, name: FieldName) -> FieldReview[Any]:
        review = self._raw_field(name)
        return replace(review, value=deepcopy(review.value))

    @property
    def title(self) -> FieldReview[str]:
        return self._public_field("title")

    @property
    def description(self) -> FieldReview[str]:
        return self._public_field("description")

    @property
    def publication_date(self) -> FieldReview[date]:
        return self._public_field("publication_date")

    @property
    def contributors(self) -> FieldReview[tuple[Contributor, ...]]:
        return self._public_field("contributors")

    @property
    def keywords(self) -> FieldReview[tuple[str, ...]]:
        return self._public_field("keywords")

    @property
    def license(self) -> FieldReview[str]:
        return self._public_field("license")

    @property
    def doi(self) -> FieldReview[str]:
        return self._public_field("doi")

    @property
    def version(self) -> FieldReview[str]:
        return self._public_field("version")

    @property
    def language(self) -> FieldReview[str]:
        return self._public_field("language")

    @property
    def related_identifiers(self) -> FieldReview[tuple[RelatedIdentifier, ...]]:
        return self._public_field("related_identifiers")

    @property
    def creators(self) -> CreatorReview:
        return replace(self._creators, value=deepcopy(self._creators.value))

    @property
    def source(self) -> SourceInfo:
        return self._source.info

    @property
    def subjects(self) -> tuple[SubjectRecord, ...]:
        return self._source.subjects

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        if self.subject is not None:
            diagnostics: list[Diagnostic] = []
            for review in self._reviews:
                for evidence in review.observations:
                    if evidence.rule == "unmapped_identifier":
                        diagnostics.append(
                            Diagnostic(
                                "unmapped_identifier",
                                "doi",
                                self.subject.term,
                                "Identifier is retained for review but is not a recognized DOI.",
                                False,
                                (evidence,),
                            )
                        )
                if review.status == "unresolved" or (
                    review.field in ("title", "description")
                    and review.status == "missing"
                ):
                    diagnostics.append(
                        Diagnostic(
                            (
                                "unresolved_field"
                                if review.status == "unresolved"
                                else "missing_required"
                            ),
                            review.field,
                            self.subject.term,
                            f"{review.field} requires review.",
                            True,
                            review.observations,
                        )
                    )
            if self._creators.status == "missing":
                diagnostics.append(
                    Diagnostic(
                        "missing_required",
                        "creators",
                        self.subject.term,
                        "creators requires a non-empty reviewed list.",
                        True,
                    )
                )
            for observation in self._creators.observations:
                if (
                    "creator" in observation.relations
                    and not observation._complete
                    and self._creators.status == "unresolved"
                ):
                    diagnostics.append(
                        Diagnostic(
                            "unresolved_creator",
                            "creators",
                            self.subject.term,
                            f"Creator {observation.term.n3()} has unresolved kind or name.",
                            True,
                            observation.evidence,
                        )
                    )
                if observation.relations == ("attribution",):
                    diagnostics.append(
                        Diagnostic(
                            "attribution_requires_review",
                            "creators",
                            self.subject.term,
                            f"Attribution to {observation.term.n3()} does not establish authorship.",
                            False,
                            observation.evidence,
                        )
                    )
            return tuple(diagnostics)
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
        reviews = self._reviews
        creators = self._creators
        if record is not None:
            extracted = extract_fields(
                self._source.graph,
                record.term,
                self._preferred_languages,
                self._source.token,
            )
            reviews = tuple(
                next((item for item in extracted if item.field == review.field), review)
                for review in reviews
            )
            creators = extract_creators(
                self._source.graph,
                record.term,
                self._preferred_languages,
                self._source.token,
            )
        return replace(
            self,
            subject=record,
            _requested_subject=URIRef(term) if record is None else None,
            _reviews=reviews,
            _creators=creators,
        )

    def _require_subject(self) -> SubjectRecord:
        if self.subject is None:
            raise ValidationError("select a valid subject before reviewing fields")
        return self.subject

    def _replace_field(self, review: FieldReview[object]) -> Self:
        return replace(
            self,
            _reviews=tuple(
                review if item.field == review.field else item for item in self._reviews
            ),
        )

    def select_candidate(self, candidate: Candidate[str] | Candidate[date]) -> Self:
        """Choose one of this publication's observed scalar candidates."""
        subject = self._require_subject()
        if (
            not isinstance(candidate, Candidate)
            or candidate.field
            in ("creators", "contributors", "keywords", "related_identifiers")
            or candidate.field not in FIELD_NAMES
        ):
            raise ValidationError("select an observed scalar candidate")
        review = self._raw_field(candidate.field)
        if (
            candidate._context is not self._source.token
            or candidate._subject != subject.term
            or not any(candidate is item for item in review.candidates)
        ):
            raise ValidationError(
                "candidate does not belong to this source and subject"
            )
        return self._replace_field(
            replace(
                review,
                value=candidate.value,
                selection=candidate,
                status="resolved",
                origin="selection",
            )
        )

    def accept_suggestion(self, suggestion: Suggestion[str] | Suggestion[date]) -> Self:
        """Accept an inference locally; conversion publishes its reviewed value."""
        subject = self._require_subject()
        if (
            not isinstance(suggestion, Suggestion)
            or suggestion.field
            in ("creators", "contributors", "keywords", "related_identifiers")
            or suggestion.field not in FIELD_NAMES
        ):
            raise ValidationError("accept an available scalar suggestion")
        review = self._raw_field(suggestion.field)
        if (
            suggestion._context is not self._source.token
            or suggestion._subject != subject.term
            or not any(suggestion is item for item in review.suggestions)
        ):
            raise ValidationError(
                "suggestion does not belong to this source and subject"
            )
        return self._replace_field(
            replace(
                review,
                value=suggestion.value,
                selection=suggestion,
                status="resolved",
                origin="acceptance",
            )
        )

    def with_overrides(self, **changes: Unpack[MetadataOverrides]) -> Self:
        """Replace only supplied fields, preserving their original observations."""
        self._require_subject()
        unknown = changes.keys() - set(FIELD_NAMES)
        if unknown:
            raise ValidationError(
                f"unknown metadata fields: {', '.join(sorted(unknown))}"
            )
        # Validate partial input through the neutral model; placeholders are used
        # only for unsupplied required fields and never enter the harvest.
        supplied: dict[str, Any] = deepcopy(dict(changes))
        for name in ("creators", "contributors", "related_identifiers"):
            if name in supplied and isinstance(supplied[name], (tuple, list)):
                supplied[name] = tuple(
                    _revalidate_object(item) for item in supplied[name]
                )
        values: dict[str, Any] = dict(
            title="validation",
            description="validation",
            creators=(Person(name="validation"),),
        )
        values.update(supplied)
        validated = PublicationMetadata(**values)
        result = self
        for name in changes:
            value = getattr(validated, name)
            if name == "creators":
                result = replace(
                    result,
                    _creators=replace(
                        result._creators,
                        value=value,
                        status="resolved",
                        origin="override",
                    ),
                )
            else:
                review = result._raw_field(cast(FieldName, name))
                excluded = value is None or value == ()
                result = result._replace_field(
                    replace(
                        review,
                        value=value,
                        selection=None,
                        status="excluded" if excluded else "resolved",
                        origin="exclusion" if excluded else "override",
                    )
                )
        return result

    def clear(self, field: OptionalField) -> Self:
        """Explicitly exclude an optional value without erasing RDF evidence."""
        self._require_subject()
        if field not in OPTIONAL_FIELDS:
            raise ValidationError("only optional metadata fields may be cleared")
        review = self._raw_field(field)
        value = (
            () if field in ("contributors", "keywords", "related_identifiers") else None
        )
        return self._replace_field(
            replace(
                review,
                value=value,
                selection=None,
                status="excluded",
                origin="exclusion",
            )
        )

    def to_publication_metadata(self) -> PublicationMetadata:
        """Convert only a completed review; service defaults remain adapter-owned."""
        blocking = tuple(item for item in self.diagnostics if item.blocking)
        if blocking:
            raise IncompleteHarvestError(blocking)
        values: dict[str, Any] = {
            review.field: deepcopy(review.value)
            for review in self._reviews
            if review.status in ("resolved", "excluded")
        }
        values["creators"] = deepcopy(self._creators.value)
        return PublicationMetadata(**values)


def _revalidate_object(value: Any) -> Any:
    """Snapshot and revalidate the supported mutable neutral model objects."""
    if isinstance(value, (Person, Organization, Contributor, RelatedIdentifier)):
        return type(value)(**asdict(value))
    return value


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
