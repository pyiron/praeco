"""Dataclass-based authoring model for Zenodo deposition metadata."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import praeco.metadata as common_metadata
from praeco.exceptions import ValidationError

_UPLOAD_TYPES = {
    "dataset",
    "image",
    "lesson",
    "other",
    "physicalobject",
    "poster",
    "presentation",
    "publication",
    "software",
    "video",
}
_ACCESS_RIGHTS = {"closed", "embargoed", "open", "restricted"}
_COMMON_METADATA_FIELDS = {
    "publication_date",
    "title",
    "creators",
    "description",
    "license",
    "doi",
    "keywords",
    "related_identifiers",
    "contributors",
    "version",
    "language",
}
_LEGACY_COMMON_METADATA_MESSAGE = (
    "Setting publication metadata fields directly on ZenodoMetadata is deprecated. "
    "Use praeco.PublicationMetadata and wrap it with a ZenodoMetadata adapter, "
    "for example ZenodoMetadata.software(publication)."
)


@dataclass
class Creator:
    """Creator metadata with optional structured name parts."""

    family_name: str | None = None
    given_names: str | None = None
    name: str | None = None
    affiliation: str | None = None
    orcid: str | None = None
    gnd: str | None = None

    def validate(self) -> None:
        _ = self._api_name()

    def to_api_dict(self) -> dict[str, str]:
        data = {"name": self._api_name()}
        _add_if_present(data, "affiliation", self.affiliation)
        _add_if_present(data, "orcid", self.orcid)
        _add_if_present(data, "gnd", self.gnd)
        return data

    def _api_name(self) -> str:
        if self.name and self.name.strip():
            return self.name.strip()

        family_name = (self.family_name or "").strip()
        given_names = (self.given_names or "").strip()
        if family_name and given_names:
            return f"{family_name}, {given_names}"

        raise ValidationError(
            "creator requires either name or both family_name and given_names"
        )


@dataclass
class RelatedIdentifier:
    """Reference to a related persistent identifier."""

    identifier: str
    relation: str
    resource_type: str | None = None

    def to_api_dict(self) -> dict[str, str]:
        data = {
            "identifier": _required_string(self.identifier, "identifier"),
            "relation": _required_string(self.relation, "relation"),
        }
        _add_if_present(data, "resource_type", self.resource_type)
        return data


@dataclass
class Contributor:
    """Contributor metadata."""

    name: str
    type: str
    affiliation: str | None = None
    orcid: str | None = None
    gnd: str | None = None

    def to_api_dict(self) -> dict[str, str]:
        data = {
            "name": _required_string(self.name, "contributor name"),
            "type": _required_string(self.type, "contributor type"),
        }
        _add_if_present(data, "affiliation", self.affiliation)
        _add_if_present(data, "orcid", self.orcid)
        _add_if_present(data, "gnd", self.gnd)
        return data


@dataclass
class CommunityRef:
    """Reference to a Zenodo community."""

    identifier: str

    def to_api_dict(self) -> dict[str, str]:
        return {"identifier": _required_string(self.identifier, "community identifier")}


@dataclass
class GrantRef:
    """Reference to a Zenodo/OpenAIRE grant."""

    id: str

    def to_api_dict(self) -> dict[str, str]:
        return {"id": _required_string(self.id, "grant id")}


@dataclass
class ZenodoMetadata:
    """Top-level Zenodo deposition metadata authoring object."""

    upload_type: str | None = None
    publication_type: str | None = None
    image_type: str | None = None
    publication_date: date | str | None = None
    title: str | None = None
    creators: list[Creator] = field(default_factory=list)
    description: str | None = None
    access_right: str = "open"
    license: str | None = None
    embargo_date: date | str | None = None
    access_conditions: str | None = None
    doi: str | None = None
    prereserve_doi: bool | None = None
    keywords: list[str] = field(default_factory=list)
    notes: str | None = None
    related_identifiers: list[RelatedIdentifier] = field(default_factory=list)
    contributors: list[Contributor] = field(default_factory=list)
    communities: list[CommunityRef] = field(default_factory=list)
    grants: list[GrantRef] = field(default_factory=list)
    version: str | None = None
    language: str | None = "eng"
    metadata: common_metadata.PublicationMetadata | None = None

    def validate(self) -> None:
        """Validate local metadata requirements before submission."""
        self._validate_publication_metadata_boundary()
        self._warn_if_legacy_common_metadata()

        upload_type = _required_string(self.upload_type, "upload_type")
        if upload_type not in _UPLOAD_TYPES:
            raise ValidationError(f"unsupported upload_type: {upload_type!r}")

        _ = _date_string(self._publication_date(), "publication_date")
        _ = _required_string(self._title(), "title")
        _ = _required_string(self._description(), "description")

        creators = self._creators()
        if not creators:
            raise ValidationError("creators must contain at least one creator")
        for creator in creators:
            if isinstance(creator, Creator):
                creator.validate()
            else:
                _ = _creator_api_name(creator)

        if upload_type == "publication":
            _ = _required_string(self.publication_type, "publication_type")
        if upload_type == "image":
            _ = _required_string(self.image_type, "image_type")

        access_right = _required_string(self.access_right, "access_right")
        if access_right not in _ACCESS_RIGHTS:
            raise ValidationError(f"unsupported access_right: {access_right!r}")
        if access_right in {"open", "embargoed"}:
            _ = _required_string(self._license(), "license")
        if access_right == "embargoed":
            _ = _date_string(self.embargo_date, "embargo_date")
        if access_right == "restricted":
            _ = _required_string(self.access_conditions, "access_conditions")

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize to Zenodo's metadata object."""
        self.validate()

        data: dict[str, Any] = {
            "upload_type": _required_string(self.upload_type, "upload_type"),
            "publication_date": _date_string(
                self._publication_date(),
                "publication_date",
            ),
            "title": _required_string(self._title(), "title"),
            "creators": [_creator_to_api_dict(creator) for creator in self._creators()],
            "description": _required_string(self._description(), "description"),
            "access_right": _required_string(self.access_right, "access_right"),
        }

        _add_if_present(data, "publication_type", self.publication_type)
        _add_if_present(data, "image_type", self.image_type)
        _add_if_present(data, "license", self._license())
        _add_if_present(data, "embargo_date", _optional_date_string(self.embargo_date))
        _add_if_present(data, "access_conditions", self.access_conditions)
        _add_if_present(data, "doi", self._doi())
        if self.prereserve_doi is not None:
            data["prereserve_doi"] = self.prereserve_doi
        keywords = self._keywords()
        if keywords:
            data["keywords"] = keywords
        _add_if_present(data, "notes", self.notes)
        related_identifiers = self._related_identifiers()
        if related_identifiers:
            data["related_identifiers"] = [
                _related_identifier_to_api_dict(related)
                for related in related_identifiers
            ]
        contributors = self._contributors()
        if contributors:
            data["contributors"] = [
                _contributor_to_api_dict(contributor) for contributor in contributors
            ]
        if self.communities:
            data["communities"] = [
                community.to_api_dict() for community in self.communities
            ]
        if self.grants:
            data["grants"] = [grant.to_api_dict() for grant in self.grants]
        _add_if_present(data, "version", self._version())
        _add_if_present(data, "language", self._language())
        return data

    def to_payload(self) -> dict[str, Any]:
        """Serialize to a Zenodo deposition request payload."""
        return {"metadata": self.to_api_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ZenodoMetadata:
        """Build metadata from a Zenodo metadata dict or deposition payload."""
        source = _metadata_source(data)
        return cls(
            upload_type=_optional_string(source.get("upload_type")),
            publication_type=_optional_string(source.get("publication_type")),
            image_type=_optional_string(source.get("image_type")),
            publication_date=_optional_date_value(source.get("publication_date")),
            title=_optional_string(source.get("title")),
            creators=[
                _creator_from_dict(item) for item in _mapping_list(source, "creators")
            ],
            description=_optional_string(source.get("description")),
            access_right=_optional_string(source.get("access_right")) or "open",
            license=_optional_string(source.get("license")),
            embargo_date=_optional_date_value(source.get("embargo_date")),
            access_conditions=_optional_string(source.get("access_conditions")),
            doi=_optional_string(source.get("doi")),
            prereserve_doi=_optional_bool(source.get("prereserve_doi")),
            keywords=_string_list(source.get("keywords")),
            notes=_optional_string(source.get("notes")),
            related_identifiers=[
                _related_identifier_from_dict(item)
                for item in _mapping_list(source, "related_identifiers")
            ],
            contributors=[
                _contributor_from_dict(item)
                for item in _mapping_list(source, "contributors")
            ],
            communities=[
                _community_from_dict(item)
                for item in _mapping_list(source, "communities")
            ],
            grants=[_grant_from_dict(item) for item in _mapping_list(source, "grants")],
            version=_optional_string(source.get("version")),
            language=_optional_string(source.get("language")),
        )

    @classmethod
    def software(
        cls,
        metadata: common_metadata.PublicationMetadata | None = None,
    ) -> ZenodoMetadata:
        return cls(upload_type="software", metadata=metadata)

    @classmethod
    def dataset(
        cls,
        metadata: common_metadata.PublicationMetadata | None = None,
    ) -> ZenodoMetadata:
        return cls(upload_type="dataset", metadata=metadata)

    @classmethod
    def publication(
        cls,
        publication_type: str,
        metadata: common_metadata.PublicationMetadata | None = None,
    ) -> ZenodoMetadata:
        return cls(
            upload_type="publication",
            publication_type=publication_type,
            metadata=metadata,
        )

    @classmethod
    def image(
        cls,
        image_type: str,
        metadata: common_metadata.PublicationMetadata | None = None,
    ) -> ZenodoMetadata:
        return cls(upload_type="image", image_type=image_type, metadata=metadata)

    def add_creator(self, **kwargs: Any) -> Creator:
        _warn_legacy_common_metadata(stacklevel=2)
        creator = Creator(**kwargs)
        self.creators.append(creator)
        return creator

    def add_keyword(self, keyword: str) -> None:
        _warn_legacy_common_metadata(stacklevel=2)
        keyword = keyword.strip()
        if not keyword:
            raise ValidationError("keyword must be non-empty")
        self.keywords.append(keyword)

    def add_related_identifier(self, **kwargs: Any) -> RelatedIdentifier:
        _warn_legacy_common_metadata(stacklevel=2)
        related = RelatedIdentifier(**kwargs)
        self.related_identifiers.append(related)
        return related

    def add_community(self, identifier: str) -> CommunityRef:
        community = CommunityRef(identifier=identifier)
        self.communities.append(community)
        return community

    def add_grant(self, grant_id: str) -> GrantRef:
        grant = GrantRef(id=grant_id)
        self.grants.append(grant)
        return grant

    def _publication_date(self) -> date | str | None:
        if self.metadata is None:
            return self.publication_date
        return self.metadata.publication_date

    def _title(self) -> str | None:
        if self.metadata is None:
            return self.title
        return self.metadata.title

    def _description(self) -> str | None:
        if self.metadata is None:
            return self.description
        return self.metadata.description

    def _creators(
        self,
    ) -> (
        tuple[common_metadata.Person | common_metadata.Organization, ...]
        | list[Creator]
    ):
        if self.metadata is None:
            return self.creators
        return self.metadata.creators

    def _license(self) -> str | None:
        if self.metadata is None:
            return self.license
        return self.metadata.license

    def _doi(self) -> str | None:
        if self.metadata is None:
            return self.doi
        return self.metadata.doi

    def _keywords(self) -> list[str]:
        if self.metadata is not None:
            return list(self.metadata.keywords)
        return [
            keyword.strip() for keyword in self.keywords if keyword and keyword.strip()
        ]

    def _related_identifiers(
        self,
    ) -> tuple[common_metadata.RelatedIdentifier, ...] | list[RelatedIdentifier]:
        if self.metadata is None:
            return self.related_identifiers
        return self.metadata.related_identifiers

    def _contributors(
        self,
    ) -> tuple[common_metadata.Contributor, ...] | list[Contributor]:
        if self.metadata is None:
            return self.contributors
        return self.metadata.contributors

    def _version(self) -> str | None:
        if self.metadata is None:
            return self.version
        return self.metadata.version

    def _language(self) -> str | None:
        if self.metadata is None:
            return self.language
        return self.metadata.language or self.language

    def _validate_publication_metadata_boundary(self) -> None:
        if self.metadata is None:
            return

        conflicts = [
            field_name
            for field_name in _COMMON_METADATA_FIELDS
            if self._has_legacy_common_field_value(field_name)
        ]
        if conflicts:
            joined = ", ".join(conflicts)
            raise ValidationError(
                "cannot set Zenodo common metadata fields when metadata is provided: "
                f"{joined}"
            )

    def _has_legacy_common_field_value(self, field_name: str) -> bool:
        value = getattr(self, field_name)
        if field_name == "language":
            return value not in {None, "eng"}
        if isinstance(value, list):
            return bool(value)
        return value is not None

    def _warn_if_legacy_common_metadata(self) -> None:
        if self.metadata is not None:
            return
        if any(
            self._has_legacy_common_field_value(field_name)
            for field_name in _COMMON_METADATA_FIELDS
        ):
            _warn_legacy_common_metadata(stacklevel=3)


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _warn_legacy_common_metadata(*, stacklevel: int) -> None:
    warnings.warn(
        _LEGACY_COMMON_METADATA_MESSAGE,
        DeprecationWarning,
        stacklevel=stacklevel + 1,
    )


def _creator_to_api_dict(
    creator: Creator | common_metadata.Person | common_metadata.Organization,
) -> dict[str, str]:
    if isinstance(creator, Creator):
        return creator.to_api_dict()
    if isinstance(creator, common_metadata.Organization):
        return {"name": creator.name}
    data = {"name": _person_api_name(creator)}
    _add_if_present(data, "affiliation", creator.affiliation)
    _add_if_present(data, "orcid", creator.orcid)
    _add_if_present(data, "gnd", creator.gnd)
    return data


def _person_api_name(person: common_metadata.Person) -> str:
    if person.name:
        return person.name
    if person.family_name and person.given_names:
        return f"{person.family_name}, {person.given_names}"
    raise ValidationError(
        "person requires either name or both family_name and given_names"
    )


def _creator_api_name(
    creator: common_metadata.Person | common_metadata.Organization,
) -> str:
    if isinstance(creator, common_metadata.Organization):
        return creator.name
    return _person_api_name(creator)


def _related_identifier_to_api_dict(
    related_identifier: RelatedIdentifier | common_metadata.RelatedIdentifier,
) -> dict[str, str]:
    if isinstance(related_identifier, RelatedIdentifier):
        return related_identifier.to_api_dict()
    data = {
        "identifier": _required_string(related_identifier.identifier, "identifier"),
        "relation": _required_string(related_identifier.relation, "relation"),
    }
    _add_if_present(data, "resource_type", related_identifier.resource_type)
    return data


def _contributor_to_api_dict(
    contributor: Contributor | common_metadata.Contributor,
) -> dict[str, str]:
    if isinstance(contributor, Contributor):
        return contributor.to_api_dict()
    data = {
        "name": _person_api_name(contributor.person),
        "type": _required_string(contributor.role, "contributor role"),
    }
    _add_if_present(data, "affiliation", contributor.person.affiliation)
    _add_if_present(data, "orcid", contributor.person.orcid)
    _add_if_present(data, "gnd", contributor.person.gnd)
    return data


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValidationError("prereserve_doi must be a boolean when provided")


def _optional_date_value(value: object) -> date | str | None:
    if value is None or isinstance(value, date):
        return value
    return _date_string(value if isinstance(value, str) else str(value), "date")


def _date_string(value: date | str | None, field_name: str) -> str:
    if value is None:
        value = date.today()
    if isinstance(value, date):
        return value.isoformat()
    text = _required_string(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO date (YYYY-MM-DD)") from exc
    return parsed.isoformat()


def _optional_date_string(value: date | str | None) -> str | None:
    if value is None:
        return None
    return _date_string(value, "date")


def _add_if_present(data: dict[str, Any], key: str, value: object) -> None:
    if isinstance(value, str):
        if value.strip():
            data[key] = value.strip()
    elif value is not None:
        data[key] = value


def _metadata_source(data: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = data.get("metadata")
    if isinstance(metadata, Mapping):
        return metadata
    return data


def _mapping_list(data: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{key} must be a list")

    out: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValidationError(f"{key} entries must be objects")
        out.append(item)
    return out


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("keywords must be a list")
    return [text for item in value if (text := _optional_string(item))]


def _creator_from_dict(data: Mapping[str, Any]) -> Creator:
    return Creator(
        family_name=_optional_string(data.get("family_name")),
        given_names=_optional_string(data.get("given_names")),
        name=_optional_string(data.get("name")),
        affiliation=_optional_string(data.get("affiliation")),
        orcid=_optional_string(data.get("orcid")),
        gnd=_optional_string(data.get("gnd")),
    )


def _related_identifier_from_dict(data: Mapping[str, Any]) -> RelatedIdentifier:
    return RelatedIdentifier(
        identifier=_required_string(data.get("identifier"), "identifier"),
        relation=_required_string(data.get("relation"), "relation"),
        resource_type=_optional_string(data.get("resource_type")),
    )


def _contributor_from_dict(data: Mapping[str, Any]) -> Contributor:
    return Contributor(
        name=_required_string(data.get("name"), "contributor name"),
        type=_required_string(data.get("type"), "contributor type"),
        affiliation=_optional_string(data.get("affiliation")),
        orcid=_optional_string(data.get("orcid")),
        gnd=_optional_string(data.get("gnd")),
    )


def _community_from_dict(data: Mapping[str, Any]) -> CommunityRef:
    return CommunityRef(
        identifier=_required_string(data.get("identifier"), "community identifier")
    )


def _grant_from_dict(data: Mapping[str, Any]) -> GrantRef:
    return GrantRef(id=_required_string(data.get("id"), "grant id"))
