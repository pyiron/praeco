"""Dataportal-specific adaptation of publication metadata."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from praeco.exceptions import ValidationError
from praeco.metadata import (
    Contributor,
    Organization,
    Person,
    PublicationMetadata,
    RelatedIdentifier,
)

_CONTACT_FIELDS = frozenset({"uri", "name", "email", "identifier", "url"})
_PUBLISHER_FIELDS = frozenset(_CONTACT_FIELDS | {"type"})


@dataclass
class DataportalMetadata:
    """Adapt service-neutral publication metadata to a CKAN package payload."""

    metadata: PublicationMetadata
    name: str | None = None
    owner_org: str | None = None
    private: bool | None = None
    groups: list[str] = field(default_factory=list)
    extras: dict[str, str] = field(default_factory=dict)
    dataset_type: str | None = None
    publisher: Mapping[str, str] | None = None
    contact: list[Mapping[str, str]] = field(default_factory=list)
    modified: date | str | None = None
    identifier: str | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate Dataportal-specific fields and adapter boundaries."""
        if not isinstance(self.metadata, PublicationMetadata):
            raise ValidationError("metadata must be a PublicationMetadata instance")

        if self.name is not None:
            _ = _required_string(self.name, "name")
        if self.owner_org is not None:
            _ = _required_string(self.owner_org, "owner_org")
        if self.dataset_type is not None:
            _ = _required_string(self.dataset_type, "dataset_type")
        if self.modified is not None:
            _ = _date_string(self.modified, "modified")
        if self.identifier is not None:
            _ = _required_string(self.identifier, "identifier")
        if self.private is not None and not isinstance(self.private, bool):
            raise ValidationError("private must be a boolean when provided")

        if not isinstance(self.groups, list):
            raise ValidationError("groups must be a list")
        for group in self.groups:
            _ = _required_string(group, "group")

        if self.publisher is not None:
            _ = _schema_mapping(
                self.publisher,
                "publisher",
                allowed_fields=_PUBLISHER_FIELDS,
                require_any=True,
            )
        if not isinstance(self.contact, list):
            raise ValidationError("contact must be a list")
        for contact in self.contact:
            _ = _schema_mapping(
                contact,
                "contact",
                allowed_fields=_CONTACT_FIELDS,
                require_any=True,
            )

        if not isinstance(self.extras, dict):
            raise ValidationError("extras must be a dict")
        normalized_extra_keys: set[str] = set()
        for key, value in self.extras.items():
            normalized_key = _required_string(key, "extra key")
            if normalized_key in normalized_extra_keys:
                raise ValidationError(
                    f"duplicate extra key after normalization: {normalized_key!r}"
                )
            normalized_extra_keys.add(normalized_key)
            if not isinstance(value, str):
                raise ValidationError("extra values must be strings")

        conflicts = sorted(normalized_extra_keys & _generated_extra_keys(self.metadata))
        if conflicts:
            raise ValidationError(
                "extras conflict with PublicationMetadata fields: "
                + ", ".join(conflicts)
            )

        _ = self._package_name()

    def to_payload(self) -> dict[str, Any]:
        """Serialize metadata to a CKAN package action payload."""
        self.validate()

        payload: dict[str, Any] = {
            "name": self._package_name(),
            "title": self.metadata.title,
            "notes": self.metadata.description,
            "tags": [{"name": keyword} for keyword in self.metadata.keywords],
        }

        _add_if_present(payload, "owner_org", self.owner_org)
        if self.private is not None:
            payload["private"] = self.private
        _add_if_present(payload, "license_id", self.metadata.license)
        _add_if_present(payload, "version", self.metadata.version)
        _add_if_present(payload, "type", self.dataset_type)
        payload["creator"] = [
            _dataportal_agent(creator) for creator in self.metadata.creators
        ]
        if self.metadata.publication_date is not None:
            payload["issued"] = self.metadata.publication_date.isoformat()
        if self.metadata.language is not None:
            payload["language"] = [self.metadata.language]
        if self.publisher is not None:
            payload["publisher"] = [
                _schema_mapping(
                    self.publisher,
                    "publisher",
                    allowed_fields=_PUBLISHER_FIELDS,
                    require_any=True,
                )
            ]
        if self.contact:
            payload["contact"] = [
                _schema_mapping(
                    item,
                    "contact",
                    allowed_fields=_CONTACT_FIELDS,
                    require_any=True,
                )
                for item in self.contact
            ]
        if self.modified is not None:
            payload["modified"] = _date_string(self.modified, "modified")
        _add_if_present(payload, "identifier", self.identifier or self.metadata.doi)

        if self.groups:
            payload["groups"] = [
                {"name": _required_string(group, "group")} for group in self.groups
            ]

        extras = self._serialized_extras()
        if extras:
            payload["extras"] = [
                {"key": key, "value": value} for key, value in extras.items()
            ]

        return payload

    def _package_name(self) -> str:
        if self.name is not None:
            return _required_string(self.name, "name")

        name = _slugify(self.metadata.title)
        if not name:
            raise ValidationError(
                "name must be provided when title cannot produce a CKAN package name"
            )
        return name

    def _serialized_extras(self) -> dict[str, str]:
        extras = {
            _required_string(key, "extra key"): value
            for key, value in self.extras.items()
        }

        if self.metadata.publication_date is not None:
            extras["publication_date"] = self.metadata.publication_date.isoformat()
        if self.metadata.doi is not None:
            extras["doi"] = self.metadata.doi
        if self.metadata.language is not None:
            extras["language"] = self.metadata.language

        extras["creators"] = _json_value(
            [_creator_dict(creator) for creator in self.metadata.creators]
        )
        if self.metadata.contributors:
            extras["contributors"] = _json_value(
                [_contributor_dict(item) for item in self.metadata.contributors]
            )
        if self.metadata.related_identifiers:
            extras["related_identifiers"] = _json_value(
                [
                    _related_identifier_dict(item)
                    for item in self.metadata.related_identifiers
                ]
            )

        return extras


def _generated_extra_keys(metadata: PublicationMetadata) -> set[str]:
    keys = {"creators"}
    if metadata.publication_date is not None:
        keys.add("publication_date")
    if metadata.doi is not None:
        keys.add("doi")
    if metadata.language is not None:
        keys.add("language")
    if metadata.contributors:
        keys.add("contributors")
    if metadata.related_identifiers:
        keys.add("related_identifiers")
    return keys


def _dataportal_agent(creator: Person | Organization) -> dict[str, str]:
    """Serialize a neutral creator into the Dataportal agent field shape."""
    if isinstance(creator, Organization):
        data = {"name": creator.name, "type": "Organization"}
        _add_if_present(data, "identifier", creator.identifier)
        return data
    data = {
        "name": _person_name(creator),
        "type": "Person",
    }
    _add_if_present(data, "identifier", _orcid_uri(creator.orcid))
    return data


def _orcid_uri(value: str | None) -> str | None:
    """Return an ORCID as a stable HTTPS URI when present."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    prefix = "https://orcid.org/"
    for scheme_prefix in ("https://orcid.org/", "http://orcid.org/"):
        if text.startswith(scheme_prefix):
            return prefix + text.removeprefix(scheme_prefix)
    return prefix + text


def _person_name(person: Person) -> str:
    """Return the display name used for Dataportal person fields."""
    if person.name:
        return person.name
    if person.family_name and person.given_names:
        return f"{person.family_name}, {person.given_names}"
    raise ValidationError(
        "person requires either name or both family_name and given_names"
    )


def _person_dict(person: Person) -> dict[str, str]:
    data: dict[str, str] = {}
    _add_if_present(data, "family_name", person.family_name)
    _add_if_present(data, "given_names", person.given_names)
    _add_if_present(data, "name", person.name)
    _add_if_present(data, "affiliation", person.affiliation)
    _add_if_present(data, "orcid", person.orcid)
    _add_if_present(data, "gnd", person.gnd)
    return data


def _creator_dict(creator: Person | Organization) -> dict[str, str]:
    if isinstance(creator, Organization):
        return _dataportal_agent(creator)
    return _person_dict(creator)


def _contributor_dict(contributor: Contributor) -> dict[str, Any]:
    data: dict[str, Any] = {"person": _person_dict(contributor.person)}
    _add_if_present(data, "role", contributor.role)
    return data


def _related_identifier_dict(
    related_identifier: RelatedIdentifier,
) -> dict[str, str]:
    data = {
        "identifier": related_identifier.identifier,
        "relation": related_identifier.relation,
    }
    _add_if_present(data, "resource_type", related_identifier.resource_type)
    return data


def _json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _schema_mapping(
    value: Mapping[str, str],
    field_name: str,
    *,
    allowed_fields: frozenset[str],
    require_any: bool,
) -> dict[str, str]:
    """Validate and trim a Dataportal schema mapping."""
    if not isinstance(value, Mapping):
        raise ValidationError(f"{field_name} must be a mapping")

    data: dict[str, str] = {}
    for key, raw_value in value.items():
        normalized_key = _required_string(key, f"{field_name} key")
        if normalized_key not in allowed_fields:
            raise ValidationError(
                f"{field_name} contains unsupported field: {normalized_key}"
            )
        if not isinstance(raw_value, str):
            raise ValidationError(f"{field_name} values must be strings")
        _add_if_present(data, normalized_key, raw_value)

    if require_any and not data:
        raise ValidationError(f"{field_name} must contain at least one non-empty field")
    return data


def _date_string(value: date | str, field_name: str) -> str:
    """Validate a date-like Dataportal field and return its ISO date string."""
    if isinstance(value, datetime):
        raise ValidationError(f"{field_name} must be an ISO date")
    if isinstance(value, date):
        return value.isoformat()
    text = _required_string(value, field_name)
    try:
        _ = date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO date") from exc
    return text


def _slugify(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())
    return slug.strip("-")


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _add_if_present(data: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None and value.strip():
        data[key] = value.strip()
