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


if __name__ == "__main__":
    mcp.run(transport="stdio")
