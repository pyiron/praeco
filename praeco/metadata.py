"""Service-independent publication metadata models.

This module defines praeco's reusable publication metadata vocabulary. It must
not import service-specific clients or adapters; publication services should
adapt these models into their own API payloads.
"""

from __future__ import annotations

from dataclasses import field
from datetime import date
from typing import Self

from pydantic import ConfigDict, field_validator, model_validator
from pydantic.dataclasses import dataclass

_MODEL_CONFIG = ConfigDict(validate_assignment=True)

__all__ = [
    "Contributor",
    "Organization",
    "Person",
    "PublicationMetadata",
    "RelatedIdentifier",
]


@dataclass(config=_MODEL_CONFIG)
class Person:
    """Person identity used by publication metadata."""

    family_name: str | None = None
    given_names: str | None = None
    name: str | None = None
    affiliation: str | None = None
    orcid: str | None = None
    gnd: str | None = None

    @field_validator(
        "family_name",
        "given_names",
        "name",
        "affiliation",
        "orcid",
        "gnd",
        mode="after",
    )
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        if self.name or (self.family_name and self.given_names):
            return self
        raise ValueError(
            "person requires either name or both family_name and given_names"
        )


@dataclass(config=_MODEL_CONFIG)
class Organization:
    """Organization identity used as a publication creator."""

    name: str
    identifier: str | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("identifier", mode="after")
    @classmethod
    def _clean_identifier(cls, value: str | None) -> str | None:
        return _optional_text(value)


@dataclass(config=_MODEL_CONFIG)
class Contributor:
    """Publication contributor with an optional service-neutral role."""

    person: Person
    role: str | None = None

    @field_validator("role", mode="after")
    @classmethod
    def _clean_role(cls, value: str | None) -> str | None:
        return _optional_text(value)


@dataclass(config=_MODEL_CONFIG)
class RelatedIdentifier:
    """Reference to a related persistent identifier."""

    identifier: str
    relation: str
    resource_type: str | None = None

    @field_validator("identifier", "relation", mode="after")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("resource_type", mode="after")
    @classmethod
    def _clean_resource_type(cls, value: str | None) -> str | None:
        return _optional_text(value)


@dataclass(config=_MODEL_CONFIG)
class PublicationMetadata:
    """Reusable publication metadata independent of a publication service."""

    title: str
    description: str
    creators: tuple[Person | Organization, ...]
    publication_date: date | None = None
    contributors: tuple[Contributor, ...] = field(default_factory=tuple)
    keywords: tuple[str, ...] = field(default_factory=tuple)
    license: str | None = None
    doi: str | None = None
    version: str | None = None
    language: str | None = None
    related_identifiers: tuple[RelatedIdentifier, ...] = field(default_factory=tuple)

    @field_validator("title", "description", mode="after")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator(
        "license",
        "doi",
        "version",
        "language",
        mode="after",
    )
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("keywords", mode="after")
    @classmethod
    def _clean_keywords(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_required_text(keyword) for keyword in value)

    @model_validator(mode="after")
    def _validate_creators(self) -> Self:
        if self.creators:
            return self
        raise ValueError("creators must contain at least one creator")


def _required_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("value must be a non-empty string")
    return text


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None
