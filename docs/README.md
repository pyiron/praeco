# praeco

`praeco` provides Python clients for working with remote services used to publish, upload, query, and manage research and semantic assets.

The main user-facing API is built around service clients:

- `OntodockerClient` for Ontodocker-backed RDF datasets, endpoint discovery, and SPARQL queries.
- `DataportalClient` for datasets, assets, DCAT RDF, and SPARQL workflows on the [MaterialDigital Dataportal](https://dataportal.material-digital.de).
- `ZenodoClient` for Zenodo depositions, files, metadata, license lookup, and publication workflows.

`HttpClient` is the shared HTTP(S) base client used by service clients. Advanced users may also use it directly when they need low-level access to an HTTP API or want to prototype support for a new service.

`praeco` is not a workflow engine, scheduler, triple store, or archival backend. It is a client layer for talking to those services through explicit Python APIs.

## Overview

The public API is organized in two layers.

Service clients implement domain workflows:

- `OntodockerClient` exposes `endpoints`, `datasets`, and `sparql` resources.
- `DataportalClient` exposes `datasets`, `assets`, `rdf`, and `sparql` resources.
- `ZenodoClient` exposes `depositions`, `files`, `licenses`, and `records` resources.

Protocol clients provide reusable transport behavior:

- `HttpClient` normalizes base URLs, manages bearer-token headers, handles timeouts and TLS verification, and provides small request/response helpers.

New user code should usually start with a service client. Use `HttpClient` directly only when a service-specific method does not exist yet, or when you are developing a new service adapter.

## Installation

`praeco` supports Python 3.11 to 3.13. Development in this repository currently targets Python 3.12.

For local use or development:

```bash
git clone https://github.com/pyiron/praeco.git
cd praeco
conda create -n praeco python=3.12
conda activate praeco
pip install -e .
```

If you want the documentation environment as well, see `docs/environment.yml`.

PyPI and conda-forge releases are planned, but the current hands-on installation path is an editable install from the repository.

## Service Clients

Service clients are the primary API for normal use. They subclass or build on `HttpClient`, then attach small resource objects for service-specific behavior. Generic transport code stays in `praeco/http_client.py` and `praeco/transport/`; service-specific routes, models, and error handling live under `praeco/services/<service>/`.

### OntodockerClient

`OntodockerClient` is the service-specific client for Ontodocker datasets, endpoint discovery, and SPARQL queries.

#### Architecture

An `OntodockerClient` exposes three resource objects:

```python
from praeco import OntodockerClient

client = OntodockerClient("ontodocker.example.org", token="your-token")

client.endpoints
client.datasets
client.sparql
```

These resources share the same transport configuration: bearer-token authentication, timeout handling, TLS verification, and request execution come from `HttpClient`.

Endpoint discovery also contains Ontodocker-specific compatibility logic for historical endpoint URL formats. That behavior belongs to the Ontodocker service package rather than the generic transport layer.

#### Basic Usage

For notebooks or scripts, configure the service URL and optional token in the environment:

```bash
export ONTODOCKER_ADDRESS="https://ontodocker.example.org"
export ONTODOCKER_TOKEN="..."
```

Create a client:

```python
import os

from praeco import OntodockerClient

client = OntodockerClient(
    address=os.environ["ONTODOCKER_ADDRESS"],
    token=os.getenv("ONTODOCKER_TOKEN") or None,
)
```

Discover available endpoints and datasets:

```python
raw_endpoints = client.endpoints.list_raw()
endpoints = client.endpoints.list()
datasets = client.datasets.list()
```

Create a disposable dataset, upload Turtle, and fetch it again:

```python
from pathlib import Path

dataset = "praeco_demo"
turtle_path = Path("demo.ttl")
turtle_path.write_text(
    """
@prefix ex: <https://example.org/> .

ex:sample ex:label "Praeco demo sample" .
""".strip()
    + "\n",
    encoding="utf-8",
)

client.datasets.create(dataset)
client.datasets.upload_turtlefile(dataset, turtle_path)

turtle_text = client.datasets.fetch_turtle(dataset)
downloaded = client.datasets.download_turtle(dataset, "downloaded_demo.ttl")
```

Upload an in-memory `rdflib.Graph`:

```python
import rdflib

graph = rdflib.Graph()
EX = rdflib.Namespace("https://example.org/")

graph.add((EX.sample2, EX.label, rdflib.Literal("Graph-created sample")))
client.datasets.upload_graph(dataset, graph)
```

Run SPARQL queries:

```python
query = """
SELECT ?s ?p ?o
WHERE {
  ?s ?p ?o .
}
LIMIT 10
"""

raw_result = client.sparql.query_raw(dataset, query)
df = client.sparql.query_df(dataset, query, columns=["s", "p", "o"])
```

Clean up disposable resources when finished:

```python
client.datasets.delete(dataset)
turtle_path.unlink(missing_ok=True)
Path(downloaded).unlink(missing_ok=True)
```

#### More Information

Use `OntodockerClient` for dataset, endpoint, and SPARQL workflows. Use `HttpClient` directly only when you need an endpoint that the Ontodocker resources do not expose yet. If that endpoint becomes part of normal Ontodocker usage, add it as a method on an Ontodocker resource class instead of duplicating URL construction in notebooks or scripts.

See the [OntodockerClient notebook](https://github.com/pyiron/praeco/blob/main/notebooks/OntodockerClient.ipynb) for a runnable demo and more detailed usage.

### DataportalClient

`DataportalClient` supports publication and semantic-data workflows on the CKAN-backed [MaterialDigital Dataportal](https://dataportal.material-digital.de). It uses the Dataportal deployment by default, while still allowing another compatible address to be supplied explicitly.

#### Architecture

A `DataportalClient` exposes four resource objects:

```python
from praeco import DataportalClient

client = DataportalClient(api_token="your-token")

client.datasets
client.assets
client.rdf
client.sparql
```

The client builds on praeco's shared HTTP and CKAN transport infrastructure. The resource objects provide typed dataset and asset operations, DCAT RDF retrieval, and discovery and querying of dataset-associated SPARQL endpoints.

#### Basic Usage

Provide a Dataportal API token through the environment:

```bash
export DATAPORTAL_TOKEN="..."
```

Create a client:

```python
import os

from praeco import DataportalClient

client = DataportalClient(api_token=os.environ["DATAPORTAL_TOKEN"])
```

Service-independent publication fields are modeled with `PublicationMetadata`. Wrap them in `DataportalMetadata` to add CKAN and Dataportal-specific fields before creating a dataset:

```python
from praeco import Person, PublicationMetadata
from praeco.services.dataportal import DataportalMetadata

publication = PublicationMetadata(
    title="praeco Dataportal example",
    description="Example dataset created with praeco.",
    creators=[Person(name="Example Author")],
    keywords=["praeco", "dataportal"],
)
metadata = DataportalMetadata(
    metadata=publication,
    name="praeco-dataportal-example",
    owner_org="organization-id",
    private=True,
)

dataset = client.datasets.create(metadata)
```

Upload Turtle using a format recognized by the Dataportal's Fuseki integration:

```python
from pathlib import Path

asset = client.assets.upload_rdf(
    dataset,
    Path("dataset.ttl"),
    format="turtle",
)
```

The Dataportal performs triplestore updates asynchronously. Once Fuseki indexing has completed and the generated SPARQL resource is available, query it through the dataset model:

```python
dataset = client.datasets.show(dataset)
endpoint = client.sparql.endpoint(dataset)
result = client.sparql.query_json(
    endpoint,
    "ASK WHERE { ?subject ?predicate ?object }",
)
```

#### Downloading Assets

`client.assets.download()` writes the content of one asset to a local file, and `client.assets.download_all()` writes the uploaded assets of a dataset. Both accept an id or a model:

```python
# Download one asset ...
path = client.assets.download(asset, directory="downloads")

# ... under a name of your choice ...
renamed = client.assets.download(asset, directory="downloads", filename="copy.ttl")

# ... or every uploaded asset of the dataset.
paths = client.assets.download_all(dataset, directory="all-assets")
```

`download()` always fetches the asset's current metadata first, also when given a `DataportalAssetInfo`, and then streams the content from the asset's `url`. That URL must be an absolute HTTP(S) URL; otherwise `ValidationError` is raised before any content is requested. `download_all()` fetches the dataset once and downloads only uploaded assets (`url_type` `"upload"`), one at a time in the order the Dataportal reports them. Link assets, which point to an external URL, are skipped; download them one by one with `download()`. Without uploaded assets, `download_all()` downloads nothing and returns an empty list, after the same check of `directory` described below; a missing `directory` is then not created. Both methods return the written paths, `Path(directory) / name`, and create a missing `directory`.

The API token is sent only to the client's own address: the same scheme, host, and port (a missing port means 80 for `http` and 443 for `https`). Content from any other URL, such as an external link asset, is downloaded without the token, and `requests` drops the token when a redirect leads to another host. As a consequence, if the asset URLs name the Dataportal under another address than the client's, for example another alias of the host or `http` instead of `https`, the token is not sent and a private asset fails with the server's error. A response status of 400 or higher raises `CkanApiError`.

By default, a file is named after the last segment of the URL path, percent-decoded, for example `dataset.ttl` for `.../download/dataset.ttl`. If that segment is empty or unsafe, the asset id is used instead, without a warning. Pass `filename=` to `download()` to choose the name yourself; it is used as given, and an unsafe name raises `ValidationError` before any request. A safe name is a single file name that works on every platform: not empty, `.` or `..`; none of `/ \ : * ? " < > |` and no control characters; no trailing dot or space; not a Windows device name such as `CON`, `NUL`, `COM1` or `LPT1`, also with an extension (`con.txt`); and at most 255 bytes in UTF-8. These rules apply on every operating system.

Each file is streamed to a temporary file next to its target and moved into place only when complete. For uploaded assets, the received size is checked against the asset's `size`, and a mismatch raises `ValidationError` and leaves no file behind. Link assets are not size-checked, because their `size` is entered by hand. No checksum is verified.

Existing files are not replaced by default: if a target already exists, `FileExistsError` is raised before anything is downloaded. Pass `overwrite=True` to replace existing files. A `directory` that exists but is not a directory, or an existing directory at a target path, raises `FileExistsError` even with `overwrite=True`. In `download_all()`, uploaded assets whose file names coincide raise `ValidationError` naming the asset ids, before anything is downloaded; on case-insensitive filesystems, names that differ only in case refer to the same local file and are not detected. If a download fails partway through `download_all()`, the files completed earlier are kept.

The same methods exist on the internal CKAN layer as `client.resources.download(resource, ...)` and `client.resources.download_all(package, ...)`; the asset methods delegate to them.

#### More Information

Creating datasets and starting Fuseki updates require suitable permissions for the selected organization. Use disposable private datasets when validating write workflows against the live deployment, and clean them up afterwards.

See the [DataportalClient notebook](https://github.com/pyiron/praeco/blob/main/notebooks/DataportalClient.ipynb) for a complete live workflow covering organization discovery, metadata, datasets, RDF assets, Fuseki indexing, SPARQL querying, and cleanup.

### ZenodoClient

`ZenodoClient` is the service-specific client for Zenodo deposition drafts, file uploads, record file downloads, metadata authoring, license lookup, and publication actions.

#### Architecture

A `ZenodoClient` exposes four resource objects:

```python
from praeco import ZenodoClient

client = ZenodoClient(sandbox=True, token="your-sandbox-token")

client.depositions
client.files
client.licenses
client.records
```

`client.depositions` owns draft and publication lifecycle operations such as creating drafts, setting metadata, publishing, editing, discarding edits, creating new versions, and deleting unpublished drafts.

`client.files` owns draft-file operations such as listing, uploading, renaming, and deleting files. File uploads use the bucket link returned by Zenodo.

`client.licenses` provides read-only lookup of Zenodo license metadata.

`client.records.files` lists and downloads the files of published records and of your own drafts through the InvenioRDM records API. It is read-only; see Downloading Record Files below.

The current draft/deposition implementation uses Zenodo's legacy deposition API. This is the Zenodo-specific API still used for the core create, upload, update, and publish workflow implemented here. A future migration toward the newer InvenioRDM REST API is expected, but the existing resource surface is kept stable until there is a tested migration path.

#### Basic Usage

For development and testing, use the Zenodo sandbox:

```bash
export ZENODO_SANDBOX_TOKEN="..."
```

Sandbox and production Zenodo have separate accounts and tokens. A sandbox token must come from `https://sandbox.zenodo.org`, not production Zenodo.

Create a client and a small artifact:

```python
import os
from pathlib import Path

from praeco import Person, PublicationMetadata, ZenodoClient
from praeco.services.zenodo import Creator, ZenodoMetadata

client = ZenodoClient(sandbox=True, token=os.environ["ZENODO_SANDBOX_TOKEN"])

artifact = Path("demo_artifact.txt")
artifact.write_text(
    "Hello from praeco's Zenodo sandbox demo.\n",
    encoding="utf-8",
)
```

Build service-independent publication metadata and wrap it in the Zenodo adapter:

```python
publication = PublicationMetadata(
    title="praeco Zenodo sandbox demo",
    description="Small demonstration upload created with praeco.",
    creators=[
        Person(
            family_name="Doe",
            given_names="Jane",
            affiliation="Example Institute",
        )
    ],
    keywords=["praeco", "zenodo", "sandbox"],
    license="cc-by-4.0",
    version="0.1.0",
)

metadata = ZenodoMetadata.software(publication)
```

Directly setting publication fields such as `title`, `creators`, or `keywords` on `ZenodoMetadata` is deprecated. Use `PublicationMetadata` for reusable publication fields and `ZenodoMetadata` for Zenodo-specific fields.

The deprecated direct style still works temporarily for migration:

```python
metadata = ZenodoMetadata.software()
metadata.title = "praeco Zenodo sandbox demo"
metadata.description = "Small demonstration upload created with praeco."
metadata.license = "cc-by-4.0"
metadata.creators.append(
    Creator(
        family_name="Doe",
        given_names="Jane",
        affiliation="Example Institute",
    )
)
```

Create an unpublished draft, pre-reserve a DOI, upload the artifact, and set the metadata:

```python
draft = client.depositions.create(prereserve_doi=True)
uploaded = client.files.upload(draft, artifact)
draft = client.depositions.set_metadata(draft, metadata)
```

Publishing is an explicit action:

```python
# published = client.depositions.publish(draft)
```

For routine demos, leave drafts unpublished and clean them up:

```python
client.depositions.delete(draft)
artifact.unlink(missing_ok=True)
```

Production Zenodo should be treated differently from the sandbox. Publishing on production Zenodo creates a real archival record; a DOI becomes a persistent, citable scholarly identifier when the record is published.

#### Downloading Record Files

`client.records.files` lists and downloads the files of a Zenodo record by its record id. Open published records need no token:

```python
from praeco import ZenodoClient

client = ZenodoClient()

names = client.records.files.list(1234567)

# Download selected files ...
paths = client.records.files.download(1234567, names[0], directory="selected")

# ... or all of them.
all_paths = client.records.files.download_all(1234567, directory="all-files")
```

`list()` returns the file keys in the order Zenodo reports them. `download()` accepts one key or a sequence of keys, which must match `list()` exactly; unknown or duplicate keys raise `ValidationError` before any file is downloaded. Both download methods return the written paths, `Path(directory) / key`, in the order requested; `download_all()` follows the order of `list()`.

With a token, the same calls read the files of your own unpublished drafts and edit drafts when you pass `draft=True`. A `DepositionInfo` can be passed in place of the record id:

```python
import os

client = ZenodoClient(sandbox=True, token=os.environ["ZENODO_SANDBOX_TOKEN"])
draft = client.depositions.create()  # or any DepositionInfo of your own drafts

draft_names = client.records.files.list(draft, draft=True)
draft_paths = client.records.files.download_all(
    draft,
    directory="draft-files",
    draft=True,
)
```

`draft=False`, the default, always reads the published record's files; there is no automatic fallback to a draft.

Each file is streamed to a temporary file next to its target and checked against the size and MD5 checksum reported by Zenodo before it is moved into place, so a failed or mismatched download leaves no partial file behind. Mismatches raise `ValidationError`. Files completed earlier in the same call are kept.

Keys that contain `/` are written to matching subdirectories of `directory`, which are created as needed. Keys that are empty, absolute, contain a `..` path component, or would resolve outside `directory` are rejected with `ValidationError`.

Existing files are not replaced by default: if any target already exists, `FileExistsError` is raised before anything is downloaded. Pass `overwrite=True` to replace existing files.

Keys whose local paths coincide or nest, such as `x/y` and `x//y`, or `a` and `a/b`, raise `ValidationError`, and an existing directory at a target, or an existing file where a parent directory is needed, raises `FileExistsError` even with `overwrite=True`. Both are checked before anything is downloaded. On case-insensitive filesystems, keys that differ only in case refer to the same local file and are not detected up front.

`client.files` stays the legacy deposition file API used for uploads and for listing, renaming, and deleting the files of your own drafts. It does not download files; use `client.records.files` for that.

#### Metadata

`PublicationMetadata` is praeco's service-independent authoring model for publication fields such as title, description, creators, contributors, related identifiers, keywords, license, DOI, version, language, and publication date.

`ZenodoMetadata` adapts `PublicationMetadata` into Zenodo's API payload shape and keeps Zenodo-specific fields such as upload type, access control, communities, grants, DOI reservation, and notes.

Convenience constructors set the upload type:

```python
software = ZenodoMetadata.software(publication)
dataset = ZenodoMetadata.dataset(publication)
article = ZenodoMetadata.publication("article", publication)
image = ZenodoMetadata.image("figure", publication)
```

Common nested metadata is modeled independently of Zenodo:

- `Person` for creators and contributor identities.
- `Contributor` for additional contributors with a role.
- `RelatedIdentifier` for related persistent identifiers or URLs.

Zenodo-specific repeated metadata still uses Zenodo helpers:

- `CommunityRef` for Zenodo community identifiers.
- `GrantRef` for grant references.

`ZenodoMetadata.to_api_dict()` returns the inner Zenodo metadata object:

```python
metadata_object = metadata.to_api_dict()
```

`ZenodoMetadata.to_payload()` wraps that object as `{"metadata": ...}`, which is the shape used by Zenodo deposition create and update requests:

```python
request_payload = metadata.to_payload()
```

The typed model performs local validation for stable structural rules before a request is sent, such as required title, description, creator, access, and license fields.

Plain `PublicationMetadata` is not passed directly to `client.depositions`. Wrap it in `ZenodoMetadata` so the Zenodo upload type and service-specific validation remain explicit.

For Zenodo fields that are documented but not yet modeled by `ZenodoMetadata`, pass a raw mapping. Raw mappings are wrapped as `{"metadata": ...}` by `client.depositions.create()` and `client.depositions.set_metadata()`, but they do not receive praeco's local metadata validation:

```python
raw_metadata = metadata.to_api_dict()
raw_metadata["references"] = [
    "Doe J. (2026). Example reference for a sandbox upload. DOI:10.0000/example",
]

draft = client.depositions.set_metadata(draft, raw_metadata)
```

Server responses use `DepositionInfo`. Its `metadata` field remains a raw dictionary because Zenodo may return normalized values or fields outside praeco's authoring model.

#### Sandbox vs Production

Zenodo sandbox is for testing API workflows, metadata, uploads, DOI reservation, and publication behavior. Sandbox records use test DOI infrastructure and should not be cited as persistent scholarly records. Sandbox data may also be reset.

Production Zenodo is the real publication environment. Published production records are archival research outputs, and their DOIs are persistent scholarly identifiers. Use `ZenodoClient(sandbox=True, ...)` for development and switch to the default production target only when publication is intentional.

#### More Information

Useful token scopes:

- `deposit:write` for creating drafts, updating metadata, and uploading files.
- `deposit:actions` for publishing, editing, discarding edits, and creating new versions.

Zenodo API failures raise `ZenodoApiError` or a more specific subclass such as `ZenodoValidationError`, `ZenodoAuthenticationError`, `ZenodoPermissionError`, or `ZenodoNotFoundError`. Local metadata and input validation failures use `praeco.exceptions.ValidationError`.

See the [ZenodoClient notebook](https://github.com/pyiron/praeco/blob/main/notebooks/ZenodoClient.ipynb) for a sandbox demo and more detailed usage.

## Protocol Clients

Protocol clients provide lower-level infrastructure for service clients and advanced use.

### HttpClient

`HttpClient` is the generic HTTP(S) client and base class for HTTP-backed service clients.

#### Architecture

`HttpClient` centralizes shared transport behavior:

- normalizing a host or URL into `base_url`
- configuring bearer-token authorization headers
- passing timeout and TLS verification settings to `requests`
- allowing an externally managed `requests.Session`
- exposing helpers for common text and JSON request patterns
- raising consistent praeco HTTP errors

Developers adding a new HTTP-based service client should usually put domain methods on small resource classes and let the service client inherit from or compose `HttpClient`.

#### Basic Usage

Create a client:

```python
from praeco import HttpClient

client = HttpClient("api.example.org", token="initial-token")
client.base_url
```

Use `default_scheme="http"` for local development services without TLS:

```python
local = HttpClient("localhost:8000", default_scheme="http")
```

Token updates keep the session authorization header in sync:

```python
client.token = "rotated-token"
client.token = None
```

Use convenience helpers when the response shape is simple:

```python
json_payload = client.get_json("https://api.example.org/status")
text_payload = client.get_text("https://api.example.org/version")

created = client.post_text(
    "https://api.example.org/items",
    json={"name": "demo"},
)
updated = client.put_text(
    "https://api.example.org/items/demo",
    json={"name": "demo"},
)
deleted = client.delete_text("https://api.example.org/items/demo")
```

Use `request()` when you need direct access to the underlying `requests.Response`:

```python
response = client.request(
    "GET",
    "https://api.example.org/status",
    headers={"Accept": "application/json"},
)
```

#### More Information

Use `HttpClient` directly when:

- an implemented service client does not expose the endpoint you need
- you are prototyping support for a new service
- the API is small enough that a full service client would not yet pay off

Once route construction, response parsing, or workflow logic starts repeating, move that behavior into a service-specific client under `praeco/services/`.

See the [HttpClient notebook](https://github.com/pyiron/praeco/blob/main/notebooks/HttpClient.ipynb) for a runnable demonstration of the transport API.

## Developer Guide

The repository is organized by responsibility:

- `praeco/http_client.py` contains the public reusable HTTP client.
- `praeco/transport/` contains generic transport helpers for authentication, session creation, URL normalization/composition, and response handling.
- `praeco/services/ontodocker/` contains Ontodocker routes, resources, models, and compatibility helpers.
- `praeco/services/dataportal/` contains Dataportal datasets, assets, metadata, DCAT RDF, SPARQL, and CKAN-backed models.
- `praeco/services/zenodo/` contains Zenodo routes, resources, metadata authoring objects, response models, and Zenodo-specific errors.
- `tests/unit/` contains focused behavior tests using fake sessions and responses where practical.
- `tests/integration/` contains integration-oriented checks, including the README doctest loader.
- `notebooks/` contains runnable demos for the public clients.
- `.notes/` may contain local planning or investigation notes. Treat these as internal working material, not automatically user-facing documentation.

Keep generic behavior generic. URL normalization, authentication header handling, request execution, and general response helpers belong in transport code. Service routes, service models, compatibility behavior, and service-specific exceptions belong under the corresponding service package.

When a workflow becomes normal user behavior, prefer adding a resource method over repeating low-level URL construction in notebooks or application code.

## Development And Validation

Run commands from the project root.

Format with Black:

```bash
black .
```

Sort imports with Ruff:

```bash
ruff check --select I --fix .
```

Inspect broader Ruff suggestions before applying them:

```bash
ruff check --fix --diff .
```

Run tests:

```bash
pytest -q
```

`docs/README.md` is the package README and is loaded by `tests/integration/test_readme.py` as a doctest file. Keep README examples either simple enough to execute locally or formatted as illustrative fenced code blocks without doctest prompts when they require external services.
