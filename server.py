import httpx
import os
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("HOOPS_WEBAPI_URL", "http://127.0.0.1:8000").rstrip("/")

# Unique session ID per MCP server process — isolates this client's state from others
SESSION_ID = uuid.uuid4().hex
_SESSION_HEADERS = {"X-Session-ID": SESSION_ID}

mcp = FastMCP("HOOPS AI MCP Server")


def _checked(response: httpx.Response) -> httpx.Response:
    """Raise RuntimeError with API detail message on non-2xx responses."""
    if not response.is_success:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        if response.status_code == 503:
            detail = f"[Server configuration error] {detail} — サーバーの設定を確認してください。"
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    return response


def _api_get(url: str, **kwargs) -> httpx.Response:
    try:
        return _checked(httpx.get(url, **kwargs))
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error: {e}") from e


def _api_post(url: str, **kwargs) -> httpx.Response:
    try:
        return _checked(httpx.post(url, **kwargs))
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error: {e}") from e


def _api_delete(url: str, **kwargs) -> httpx.Response:
    try:
        return _checked(httpx.delete(url, **kwargs))
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error: {e}") from e


def _upload_file(cad_file_path: str) -> str:
    """Upload a local CAD file and return its file_id. Idempotent for the same file content."""
    source_path = Path(cad_file_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"CAD file not found: {source_path}")
    with source_path.open("rb") as f:
        response = _api_post(
            f"{API_BASE}/files/upload",
            files={"file": (source_path.name, f, "application/octet-stream")},
            timeout=120,
        )
    return response.json()["file_id"]



def _resolve_file_id(cad_file_path: str = "", file_id: str = "") -> str:
    """Return file_id: use existing one or upload the file if not yet uploaded."""
    if file_id:
        return file_id
    if cad_file_path:
        return _upload_file(cad_file_path)
    raise ValueError("Either cad_file_path or file_id must be provided.")


@mcp.tool()
def upload_cad_model(cad_file_path: str) -> dict:
    """Upload a local CAD file to the server and return a file_id for reuse.

    If the same file content was already uploaded, the server reuses the existing copy
    and returns the same file_id without transferring the file again.

    Always call this tool first when working with a CAD file, then pass the returned
    file_id to other tools (get_brep_attributes, get_brep_adjacency_graph,
    run_MFR_inference, search_similar_shapes, etc.) to avoid re-uploading the same
    model multiple times.

    NOTE: Do NOT call open_cad_viewer unless the user explicitly asks to open or
    display a viewer (e.g. "open the viewer", "show it in the viewer", "launch viewer").

    Returns file_id, filename, and already_existed flag.
    """
    source_path = Path(cad_file_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"CAD file not found: {source_path}")
    with source_path.open("rb") as f:
        response = _api_post(
            f"{API_BASE}/files/upload",
            files={"file": (source_path.name, f, "application/octet-stream")},
            timeout=120,
        )
    return response.json()


@mcp.tool()
def open_cad_viewer(cad_file_path: str = "", file_id: str = "") -> dict:
    """Open a CAD file in the CADViewer 3D browser-based viewer and return the viewer URL.

    STRICT RULE: Call this tool ONLY when the user's message contains explicit viewer
    launch intent, such as: "open the viewer", "launch the viewer", "open CADViewer",
    "open in browser". Do NOT call this tool for: "show me", "display", "give me",
    "get", "analyze", or any request that does not specifically mention opening a viewer.
    Requests like "show me the B-Rep info" or "give me the model info" must NOT trigger
    this tool — use get_brep_attributes or get_brep_adjacency_graph instead.

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended, avoids re-upload)
    - cad_file_path: local path to the CAD file (will be uploaded automatically)
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/CAD/viewer",
        params={"file_id": fid},
        headers=_SESSION_HEADERS,
        timeout=120,
    )
    data = response.json()
    viewer_url = data.get("viewer_url")
    if not viewer_url:
        raise RuntimeError(f"Viewer URL was not returned: {data}")
    return {"viewer_url": viewer_url, "image_url": data.get("image_url")}


@mcp.tool()
def get_MFR_table_of_contents():
    """Return a summary table of contents for the MFR dataset."""

    response = _api_get(f"{API_BASE}/MFR/dataset/table-of-contents")
    return response.json()

@mcp.tool()
def get_MFR_labels_description():
    """Return MFR label IDs, feature names, and descriptions."""

    response = _api_get(f"{API_BASE}/MFR/labels/description")
    return response.json()

@mcp.tool()
def search_MFR_files(
        feature_name: str,
    ):
    """
    Return CAD file names and file IDs that contain the requested MFR feature name.
    Response includes file_names (list of strings) and file_list (list of int file IDs).
    """

    params = {}
    if feature_name:
        params["feature_name"] = feature_name

    response = _api_get(f"{API_BASE}/MFR/files/search", params=params)
    return response.json()


@mcp.tool()
def get_MFR_file_thumbnail(file_id: int) -> str:
    """
    Return the URL of the thumbnail PNG image for a given file ID.
    The URL points directly to the PNG and can be used in HTML: <img src="{result}">
    """
    return f"{API_BASE}/MFR/files/{file_id}/thumbnail"


@mcp.tool()
def run_MFR_inference(cad_file_path: str = "", file_id: str = "") -> dict:
    """Run MFR inference on a CAD file, colorize the viewer, and return results.

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended, avoids re-upload)
    - cad_file_path: local path to the CAD file (will be uploaded automatically)

    Returns predictions, probabilities, viewer_url, image_url, and color_map.
    color_map contains only the labels present in the model: {label_id: {name, color_rgb}}.
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/MFR/inference",
        params={"file_id": fid},
        headers=_SESSION_HEADERS,
        timeout=300,
    )
    return response.json()


@mcp.tool()
def terminate_CAD_viewer(terminate_all: bool = False) -> dict:
    """
    Terminate the CAD viewer.
    - terminate_all=False (default): terminate only the last active viewer.
    - terminate_all=True: terminate all active viewers.
    Returns the number of viewers terminated.
    """
    params = {"all": "true"} if terminate_all else {}
    response = _api_delete(f"{API_BASE}/CAD/viewer", params=params, headers=_SESSION_HEADERS, timeout=30)
    return response.json()


@mcp.tool()
def get_brep_adjacency_graph(cad_file_path: str = "", file_id: str = "") -> dict:
    """Build a face adjacency graph from the B-rep model of a CAD file.

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended, avoids re-upload)
    - cad_file_path: local path to the CAD file (will be uploaded automatically)

    Returns graph data (nodes, edges, counts) and image_url: a URL to a PNG visualization.
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/BRep/adjacency-graph",
        params={"file_id": fid},
        timeout=120,
    )
    return response.json()


@mcp.tool()
def get_brep_attributes(cad_file_path: str = "", file_id: str = "") -> dict:
    """Extract face and edge attributes from the B-rep model of a CAD file.

    Use this tool whenever the user asks to "show", "display", "get", or "give"
    B-Rep or model information — without explicitly requesting to open a viewer.

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended, avoids re-upload)
    - cad_file_path: local path to the CAD file (will be uploaded automatically)

    Returns:
    - faces: types, areas, centroids, loops, types_description
    - edges: types, lengths, dihedrals, convexities, types_description
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/BRep/attributes",
        params={"file_id": fid},
        timeout=120,
    )
    return response.json()


@mcp.tool()
def search_similar_shapes(cad_file_path: str = "", file_id: str = "", top_k: int = 10) -> dict:
    """Search for similar CAD shapes using HOOPS Embeddings and a FAISS index.

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended, avoids re-upload)
    - cad_file_path: local path to the CAD file (will be uploaded automatically)

    Returns the top-k most similar shapes from the indexed database.
    Each hit contains an id (file identifier in the database) and a similarity score.
    Also returns image_url: a URL path to a PNG grid image of the search results,
    and image_base64: the grid image as a base64-encoded PNG string for HTML embedding:
      <img src="data:image/png;base64,{image_base64}">
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/similarity/search",
        params={"file_id": fid, "top_k": top_k},
        timeout=300,
    )
    data = response.json()

    image_url = data.get("image_url", "")
    return data


@mcp.tool()
def get_similar_part_image(filename: str) -> str:
    """Return the URL of the pre-generated PNG thumbnail for a trained part.

    Pass the CAD filename (with or without extension) returned by search_similar_shapes.
    The returned URL points directly to the PNG image and can be used in HTML:
      <img src="{result}">
    """
    return f"{API_BASE}/similarity/part-image?filename={filename}"


@mcp.tool()
def get_similar_search_index_info() -> dict:
    """Return metadata about the FAISS similarity-search index loaded on the server.

    This is a read-only endpoint — it never triggers index construction or retraining.

    Returns:
    - status: "loaded" or "not_loaded"
    - index_path: absolute path to the FAISS index file
    - index_last_modified: UTC last-modified timestamp of the index file
    - index_count: number of embeddings stored in the index
    - model_name: name of the embedding model used to build the index
    - embedding_dim: dimension of each embedding vector
    - metadata: auxiliary metadata stored in the index (e.g. failed_count), or null
    """
    response = _api_get(f"{API_BASE}/similarity/index-info", timeout=60)
    return response.json()


@mcp.tool()
def embed_cad_shape(cad_file_path: str = "", file_id: str = "", include_vector: bool = False) -> dict:
    """Compute the shape embedding vector for a single CAD part and return its metadata.

    No FAISS index or pre-training work is required — the server uses a bundled
    pre-trained model and runs immediately.

    Embeddings are cached server-side by file_id; a second call for the same file
    returns instantly from the cache (cached=true in the response).

    Leave include_vector as False (the default). The raw embedding vector is large
    and not needed for most workflows — omitting it saves context.
    To compare shapes against each other, use compare_cad_shapes instead.

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended, avoids re-upload)
    - cad_file_path: local path to the CAD file (will be uploaded automatically)

    Returns file_id, filename, dim, model_name, num_bodies, cached,
    and vector (only when include_vector=True).
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/similarity/embed",
        params={"file_id": fid, "include_vector": include_vector},
        timeout=300,
    )
    return response.json()


@mcp.tool()
def compare_cad_shapes(
    cad_file_paths: list[str] | None = None,
    file_ids: list[str] | None = None,
    zip_file_path: str = "",
) -> dict:
    """Compute pairwise cosine-similarity scores for two or more CAD parts.

    Returns an N×N similarity matrix (1.0 = identical shape, higher = more similar)
    and a ranked list of pairs sorted by score descending.

    No FAISS index or pre-training work is required — the server uses a bundled
    pre-trained model and runs immediately.

    Inputs can be combined freely:
    - cad_file_paths: list of local CAD file paths (each is uploaded automatically)
    - file_ids: list of existing file IDs from a previous upload_cad_model() call
    - zip_file_path: path to a local ZIP containing CAD files (extracted server-side,
      max 50 files / 500 MB per ZIP); when specified alone, the server determines
      the file count so the 2-part minimum check is skipped

    At least two parts are required in total across cad_file_paths and file_ids
    (unless zip_file_path is the sole input).

    Response fields:
    - count: total number of parts processed
    - model_name: embedding model used
    - files: list of {index, file_id, filename, num_bodies}
    - matrix: N×N cosine-similarity matrix ordered by files[].index
    - pairs: all unique pairs sorted by score descending
    - errors: per-file failures, if any (overall request still succeeds)

    Example natural-language prompts:
    - "この2つのSTEPファイルはどれくらい似ている？"
    - "Compare these three parts and tell me which two are most similar."
    - "ZIPに入っているCADファイルの類似度マトリクスを出して。"
    """
    resolved_ids: list[str] = list(file_ids) if file_ids else []

    for path in (cad_file_paths or []):
        resolved_ids.append(_upload_file(path))

    if not zip_file_path and len(resolved_ids) < 2:
        raise ValueError(
            "At least two parts are required for shape comparison. "
            "Provide two or more entries via cad_file_paths, file_ids, or a zip_file_path."
        )

    params: dict = {}
    if resolved_ids:
        params["file_ids"] = ",".join(resolved_ids)

    files: dict | None = None
    if zip_file_path:
        zip_path = Path(zip_file_path).expanduser().resolve()
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")
        files = {"zip_file": (zip_path.name, zip_path.open("rb"), "application/zip")}

    response = _api_post(
        f"{API_BASE}/similarity/compare",
        params=params,
        files=files,
        timeout=600,
    )
    return response.json()


# ── Part Classification ────────────────────────────────────────────────────────

@mcp.tool()
def run_part_classification_inference(
    cad_file_path: str = "",
    file_id: str = "",
    top_k: int = 5,
) -> dict:
    """Run Part Classification inference on a CAD file and return the top-k predicted classes.

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended, avoids re-upload)
    - cad_file_path: local path to the CAD file (will be uploaded automatically)

    top_k: number of top predictions to return (1–45, default 5).

    Returns a ranked list of part classes with confidence scores (integer %).
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/part-classification/predict",
        params={"file_id": fid, "top_k": top_k},
        timeout=300,
    )
    return response.json()


@mcp.tool()
def get_part_classification_labels() -> dict:
    """Return the full 45-class part label dictionary with IDs and descriptions."""
    response = _api_get(f"{API_BASE}/part-classification/labels")
    return response.json()


@mcp.tool()
def get_part_classification_table_of_contents() -> dict:
    """Return a summary table of contents for the Part Classification dataset, including available groups."""
    response = _api_get(f"{API_BASE}/part-classification/dataset/table-of-contents")
    return response.json()


@mcp.tool()
def get_part_classification_label_distribution() -> dict:
    """Return per-class file count distribution across the Part Classification training dataset."""
    response = _api_get(f"{API_BASE}/part-classification/dataset/label-distribution")
    return response.json()


@mcp.tool()
def get_part_classification_files(label_id: int) -> dict:
    """Return the list of file IDs in the dataset that belong to a given part class.

    label_id: part label ID (0–44).
    """
    response = _api_get(
        f"{API_BASE}/part-classification/dataset/files",
        params={"label_id": label_id},
    )
    return response.json()


@mcp.tool()
def get_part_classification_preview(
    label_id: int,
    k: int = 25,
    grid_cols: int = 8,
) -> dict:
    """Return a URL to a PNG thumbnail grid for a given part class.

    label_id: part label ID (0–44).
    k: max number of thumbnails to show (default 25).
    grid_cols: number of columns in the thumbnail grid (default 8).

    Returns label_id, part_name, and image_url pointing to the PNG grid.
    The image can be embedded in HTML: <img src="{image_url}">
    """
    response = _api_get(
        f"{API_BASE}/part-classification/dataset/preview",
        params={"label_id": label_id, "k": k, "grid_cols": grid_cols},
    )
    return response.json()


# ── Named Index Management ─────────────────────────────────────────────────────


@mcp.tool()
def create_similarity_index(name: str) -> dict:
    """Create a new empty named similarity index on the server.

    The index starts with zero parts and grows as you call add_to_similarity_index.
    Once created, it persists on the server until explicitly deleted — server
    restarts do NOT clear it.

    name: index name matching ^[a-z0-9_-]{1,64}$.  'default' is reserved.

    Returns name, count (0), and dim (embedding dimension).

    Raises an error if the name already exists (409) or is invalid (422).

    Typical workflow:
      1. create_similarity_index("my-parts")
      2. add_to_similarity_index("my-parts", cad_file_paths=[...])
      3. search_similarity_index("my-parts", cad_file_path="query.step")
    """
    response = _api_post(
        f"{API_BASE}/similarity/index/create",
        params={"name": name},
        timeout=60,
    )
    return response.json()


@mcp.tool()
def list_similarity_indexes() -> list:
    """List all similarity indexes available on the server.

    Always includes the built-in 'default' index (is_readonly=true) backed by
    the pre-trained FabWave dataset, plus any user-created named indexes.

    Each entry contains:
    - name: index identifier
    - count: number of registered parts (null if unreadable)
    - last_modified: UTC timestamp of last change
    - is_readonly: true only for the built-in 'default' index

    Use this to check what indexes exist before calling other index tools.
    """
    response = _api_get(f"{API_BASE}/similarity/index/list", timeout=60)
    return response.json()


@mcp.tool()
def add_to_similarity_index(
    name: str,
    cad_file_paths: list[str] | None = None,
    file_ids: list[str] | None = None,
    zip_file_path: str = "",
) -> dict:
    """Register CAD parts in a named similarity index.

    Embeddings are computed server-side and cached — re-adding the same file is fast.
    Re-registering an existing part ID overwrites the old entry (no duplicates).
    A PNG thumbnail is generated automatically for each registered part and stored
    with the index (used in search result grids).

    name: target index name (must already exist — call create_similarity_index first).

    Input sources can be combined freely:
    - cad_file_paths: list of local CAD file paths (each is uploaded automatically)
    - file_ids: list of existing file IDs from a previous upload_cad_model() call
    - zip_file_path: path to a ZIP archive containing CAD files (auto-extracted,
      max 50 files / 500 MB)

    Returns added (new parts), updated (overwritten parts), index_count (total after
    this call), and errors (per-file failures that did not abort the request).
    """
    resolved_ids: list[str] = list(file_ids) if file_ids else []
    for path in (cad_file_paths or []):
        resolved_ids.append(_upload_file(path))

    params: dict = {"name": name}
    if resolved_ids:
        params["file_ids"] = ",".join(resolved_ids)

    files: dict | None = None
    if zip_file_path:
        zip_path = Path(zip_file_path).expanduser().resolve()
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")
        files = {"zip_file": (zip_path.name, zip_path.open("rb"), "application/zip")}

    if not resolved_ids and not zip_file_path:
        raise ValueError(
            "At least one input is required: cad_file_paths, file_ids, or zip_file_path."
        )

    response = _api_post(
        f"{API_BASE}/similarity/index/add",
        params=params,
        files=files,
        timeout=600,
    )
    return response.json()


@mcp.tool()
def search_similarity_index(
    name: str,
    cad_file_path: str = "",
    file_id: str = "",
    top_k: int = 10,
) -> dict:
    """Search a named similarity index for the most similar parts to a query shape.

    Returns an empty hits list (not an error) when the index contains zero entries.
    When hits are found, image_url points to a result-grid PNG showing the query
    part and the top-k matches with their similarity scores.

    name: index name to search (use list_similarity_indexes to see available names).

    Provide either:
    - file_id: ID from a previous upload_cad_model() call (recommended)
    - cad_file_path: local path to the CAD file (uploaded automatically)

    Each hit contains:
    - id: file_id of the registered part
    - score: cosine similarity (1.0 = identical, higher = more similar)
    - metadata: filename, registered_at timestamp

    Also returns image_url: a URL to a PNG result-grid image.
    """
    fid = _resolve_file_id(cad_file_path, file_id)
    response = _api_post(
        f"{API_BASE}/similarity/index/{name}/search",
        params={"file_id": fid, "top_k": top_k},
        timeout=300,
    )
    return response.json()


@mcp.tool()
def remove_from_similarity_index(name: str, part_ids: list[str]) -> dict:
    """Remove specific registered parts from a named similarity index.

    name: target index name.
    part_ids: list of file_ids (SHA-256 hashes) to remove.
              Use the id field from search_similarity_index hits.

    Returns removed (count of IDs submitted) and index_count (total parts remaining).
    Note: no error is raised for IDs that do not exist in the index.
    """
    if not part_ids:
        raise ValueError("part_ids must not be empty.")
    response = _api_delete(
        f"{API_BASE}/similarity/index/{name}/parts",
        params={"part_ids": ",".join(part_ids)},
        timeout=60,
    )
    return response.json()


@mcp.tool()
def delete_similarity_index(name: str) -> dict:
    """Permanently delete a named similarity index and all its stored data.

    This is irreversible — the FAISS index files and all generated thumbnails
    are removed from disk.  The built-in 'default' index cannot be deleted.

    name: index name to delete.

    Returns name and deleted=true on success.
    Raises an error if the index does not exist (404) or name is 'default' (403).
    """
    response = _api_delete(
        f"{API_BASE}/similarity/index/{name}",
        params={"confirm": "true"},
        timeout=60,
    )
    return response.json()


@mcp.tool()
def generate_shape_space_map(
    cad_file_paths: list[str] | None = None,
    file_ids: list[str] | None = None,
    zip_file_path: str = "",
) -> dict:
    """Generate a 3D Shape Space Map that visualizes similarity relationships between CAD parts.

    Parts are positioned in 3D space using classical Multidimensional Scaling (MDS)
    so that similar parts appear close together and dissimilar parts appear far apart.
    Similar parts naturally form visible clusters in the viewer.

    Inputs can be combined freely:
    - cad_file_paths: list of local CAD file paths (each is uploaded automatically)
    - file_ids: list of existing file IDs from a previous upload_cad_model() call
    - zip_file_path: path to a local ZIP containing CAD files (extracted server-side,
      max 50 files / 500 MB per ZIP)

    At least two parts are required (unless zip_file_path is the sole input).

    Response fields:
    - map_id: unique ID for this map session
    - viewer_url: URL to open the interactive 3D viewer in a browser
    - count: number of parts processed
    - parts: list of {index, file_id, filename, scs_url, position} where position is
      the MDS-derived [x, y, z] coordinate (unit scale; viewer slider controls spacing)
    - matrix: N×N cosine-similarity matrix ordered by parts[].index
    - stress: MDS residual (0.0 = exact placement, >0 = approximate; N>=5 is always approximate)
    - errors: per-file failures, if any

    Example natural-language prompts:
    - "この5つのSTEPファイルの形状空間マップを生成して"
    - "Show me a 3D map of how similar these CAD parts are to each other."
    - "Generate a shape space map from the ZIP file and open it in the viewer."
    """
    resolved_ids: list[str] = list(file_ids) if file_ids else []

    for path in (cad_file_paths or []):
        resolved_ids.append(_upload_file(path))

    if not zip_file_path and len(resolved_ids) < 2:
        raise ValueError(
            "At least two parts are required for shape space map. "
            "Provide two or more entries via cad_file_paths, file_ids, or a zip_file_path."
        )

    params: dict = {}
    if resolved_ids:
        params["file_ids"] = ",".join(resolved_ids)

    files: dict | None = None
    if zip_file_path:
        zip_path = Path(zip_file_path).expanduser().resolve()
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")
        files = {"zip_file": (zip_path.name, zip_path.open("rb"), "application/zip")}

    response = _api_post(
        f"{API_BASE}/similarity/map",
        params=params,
        files=files,
        timeout=600,
    )
    return response.json()


if __name__ == "__main__":
    mcp.run(transport="stdio")
