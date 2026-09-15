import importlib.metadata

try:
    # Installed package will find its version
    __version__ = importlib.metadata.version(__name__)
except importlib.metadata.PackageNotFoundError:
    # Repository clones will register an unknown version
    __version__ = "0.0.0+unknown"

from praeco.http_client import HttpClient
from praeco.metadata import (
    Contributor,
    Organization,
    Person,
    PublicationMetadata,
    RelatedIdentifier,
)
from praeco.services.dataportal import DataportalClient
from praeco.services.ontodocker import OntodockerClient
from praeco.services.zenodo import ZenodoClient

__all__ = [
    "Contributor",
    "DataportalClient",
    "HttpClient",
    "OntodockerClient",
    "Organization",
    "Person",
    "PublicationMetadata",
    "RelatedIdentifier",
    "ZenodoClient",
]
