"""Dataportal-specific exceptions."""

from __future__ import annotations

from praeco.exceptions import PraecoError
from praeco.services.dataportal.models import (
    DataportalAssetInfo,
    DataportalDatasetInfo,
)


class DatasetUploadError(PraecoError):
    """Raised when `create_with_assets` fails after the dataset was created.

    The original error is the `__cause__`.

    Attributes
    ----------
    dataset
        The dataset as returned when it was created, private. This is a
        snapshot: if the request to make the dataset public failed, it may
        have been applied anyway, so read the dataset again to see its state.
    assets
        The assets uploaded before the failure, in upload order.
    deleted
        Whether the dataset was deleted because `cleanup_on_error` was set.
        If deleting failed, it is False and the delete error is attached as a
        note.
    """

    dataset: DataportalDatasetInfo
    assets: list[DataportalAssetInfo]
    deleted: bool

    def __init__(
        self,
        message: str,
        *,
        dataset: DataportalDatasetInfo,
        assets: list[DataportalAssetInfo],
        deleted: bool,
    ) -> None:
        super().__init__(message)
        self.dataset = dataset
        self.assets = assets
        self.deleted = deleted
