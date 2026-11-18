"""Dataset CRUD operations for Ontodocker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import rdflib

from praeco.exceptions import ValidationError
from praeco.transport.download import blocking_ancestor, write_response_to_path
from praeco.transport.request import raise_for_status
from praeco.transport.url import join_url

if TYPE_CHECKING:
    from praeco.services.ontodocker.client import OntodockerClient


@dataclass
class DatasetsResource:
    """Ontodocker dataset CRUD operations."""

    client: OntodockerClient

    def _dataset_url(self, dataset_name: str) -> str:
        if not dataset_name or not dataset_name.strip():
            raise ValidationError("dataset name must be non-empty")
        dataset = dataset_name.strip()
        return join_url(self.client.base_url, segments=["api", "v1", "jena", dataset])

    def list(self) -> list[str]:
        """List dataset names.

        Returns
        -------
        datasets
            Dataset identifiers.
        """
        return sorted({e.dataset for e in self.client.endpoints.list()})

    def create(self, name: str) -> str:
        """Create an empty dataset.

        Parameters
        ----------
        name
            Dataset name.

        Returns
        -------
        response_text
            Response body returned by the server.

        Raises
        ------
        ValidationError
            If `name` is empty/blank.
        """
        return self.client.put_text(self._dataset_url(name))

    def delete(self, name: str) -> str:
        """Delete a dataset.

        Parameters
        ----------
        name
            Dataset name.

        Returns
        -------
        response_text
            Response body returned by the server.

        Raises
        ------
        ValidationError
            If `name` is empty/blank.
        """
        return self.client.delete_text(self._dataset_url(name))

    def fetch_turtle(self, name: str) -> str:
        """Fetch a dataset as Turtle text.

        Parameters
        ----------
        name
            Dataset name.

        Returns
        -------
        ttl
            Turtle document as text.

        Raises
        ------
        ValidationError
            If `name` is empty/blank.
        """
        return self.client.get_text(self._dataset_url(name))

    def download_turtle(
        self, name: str, filename: str | Path, *, overwrite: bool = False
    ) -> Path:
        """Download a dataset and save it to a Turtle file.

        The response is streamed to a temporary file next to the target and
        moved into place once complete, so a failed download leaves no
        partial file. The bytes are written as the server sends them.

        Parameters
        ----------
        name
            Dataset name.
        filename
            Output file path. Missing parent directories are created.
        overwrite
            Replace an existing file instead of raising `FileExistsError`.

        Returns
        -------
        path
            Path written to disk.

        Raises
        ------
        ValidationError
            If `name` is empty/blank, or `filename` is blank when provided as a string.
        FileExistsError
            Before the request: if `filename` exists and `overwrite` is False,
            or, also with `overwrite`, if `filename` is a directory or a
            non-directory path is in the way of its parent directories.
        HttpError
            If the server responds with an error status.
        OSError
            If the file cannot be written (e.g. permissions).
        """
        if isinstance(filename, str) and not filename.strip():
            raise ValidationError("filename must be a non-empty path (str/Path)")

        path = Path(filename)
        url = self._dataset_url(name)
        _check_download_target(path, overwrite=overwrite)
        resp = self.client.request("GET", url, stream=True)
        try:
            raise_for_status(resp)
        except BaseException:
            # Also if reading the error body fails, for example on a dropped
            # connection; write_response_to_path closes it otherwise.
            resp.close()
            raise
        return write_response_to_path(resp, path, overwrite=overwrite)

    def upload_turtlefile(self, name: str, turtlefile: str | Path) -> str:
        """Upload a Turtle (.ttl) file into an existing dataset.

        Parameters
        ----------
        name
            Dataset name.
        turtlefile
            Path to a Turtle file on disk.

        Returns
        -------
        response_text
            Response body returned by the server.

        Raises
        ------
        ValidationError
            If `name` or `turtlefile` is empty/blank.
        FileNotFoundError
            If `turtlefile` does not exist.
        PermissionError
            If `turtlefile` cannot be read.
        """
        if isinstance(turtlefile, str):
            turtlefile = turtlefile.strip()
            if not turtlefile:
                raise ValidationError("turtlefile must be a non-empty path")
        path = Path(turtlefile)
        url = self._dataset_url(name)

        with path.open("rb") as f:
            return self.client.post_text(url, files={"file": f})

    def upload_graph(
        self,
        name: str,
        graph: rdflib.Graph,
        *,
        encoding: str = "utf-8",
    ) -> str:
        """Serialize an rdflib.Graph to Turtle and upload it into an existing dataset.

        Ontodocker requires uploads in Turtle format. This method serializes the
        provided graph in-memory and uploads it as multipart form data, using the
        same endpoint and form field name as `upload_turtlefile`.

        Parameters
        ----------
        name
            Dataset name.
        graph
            An ``rdflib.Graph`` instance.
        encoding
            Encoding used when converting Turtle text to bytes.

        Returns
        -------
        response_text
            Response body returned by the server.

        Raises
        ------
        ValidationError
            If `name` is empty/blank or `graph` is not an rdflib.Graph.
        Exception
            Exceptions raised by ``graph.serialize(format="turtle")``.
        """
        url = self._dataset_url(name)

        if not isinstance(graph, rdflib.Graph):
            raise ValidationError("graph must be an rdflib.Graph instance")

        ttl = graph.serialize(format="turtle")

        ttl_bytes = ttl if isinstance(ttl, bytes) else str(ttl).encode(encoding)

        bio = BytesIO(ttl_bytes)
        files = {"file": ("graph.ttl", bio, "text/turtle")}
        return self.client.post_text(url, files=files)


def _check_download_target(path: Path, *, overwrite: bool) -> None:
    """Reject a local target that cannot or must not be written."""
    blocking = blocking_ancestor(path.parent)
    if blocking is None and path.is_dir():
        blocking = path
    if blocking is not None:
        raise FileExistsError(f"local path blocks target file: {blocking}")
    if not overwrite and os.path.lexists(path):
        raise FileExistsError(f"target file already exists: {path}")
