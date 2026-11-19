"""Material Digital Dataportal client and metadata adapter."""

from praeco.services.dataportal.client import DataportalClient
from praeco.services.dataportal.exceptions import DatasetUploadError
from praeco.services.dataportal.metadata import DataportalMetadata
from praeco.services.dataportal.models import (
    DataportalAssetInfo,
    DataportalDatasetInfo,
    DataportalDatasetSearchResult,
    DatasetWithAssets,
)

__all__ = [
    "DataportalAssetInfo",
    "DataportalClient",
    "DataportalDatasetInfo",
    "DataportalDatasetSearchResult",
    "DataportalMetadata",
    "DatasetUploadError",
    "DatasetWithAssets",
]
