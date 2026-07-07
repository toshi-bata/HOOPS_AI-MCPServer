# HOOPS AI MCP Server

An MCP (Model Context Protocol) server that bridges [Claude Desktop](https://claude.ai/download) to the HOOPS AI WebAPI.  
With this server registered in Claude Desktop, users can perform 3D CAD analysis through natural language — no code required.  
See the root [README](../README.md) for an overview of the full platform.

---

## Prerequisites

- [uv](https://github.com/astral-sh/uv) installed on the **Claude Desktop machine** (Claude Desktop uses `uv` to launch the MCP server process)
- The **WebAPI server** running and accessible (default: `http://127.0.0.1:8000`)  
  → See [webapi/README.md](../webapi/README.md) for setup instructions

---

## Setup

### Register the MCP server in Claude Desktop

1. Open **Claude Desktop**
2. Go to **Settings** → **Developer** → **Edit Config**
3. This opens `claude_desktop_config.json`. Add the following entry under `mcpServers`:

```json
{
  "mcpServers": {
    "hoops-ai": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "C:\\path\\to\\HOOPS_AI-MCP\\mcp_server",
        "server.py"
      ]
    }
  }
}
```

> Replace `C:\\path\\to\\HOOPS_AI-MCP` with the actual path where you cloned this repository.

> **Troubleshooting — `uv` not found:** Claude Desktop launches with a limited PATH and may fail to find `uv` even if it works in your terminal.  
> If the MCP server does not appear in Claude Desktop, use the **full path** to `uv.exe` instead of `"uv"`:
> ```powershell
> where.exe uv   # find the full path, e.g. C:\Users\<you>\.local\bin\uv.exe
> ```
> Then update `"command"` in the config:
> ```json
> "command": "C:\\Users\\<you>\\.local\\bin\\uv.exe"
> ```

**Same machine (default):**

No additional configuration is needed.  
The MCP server defaults to `http://127.0.0.1:8000`, so if the WebAPI server is running on the same machine, the basic config above works as-is.

**When the WebAPI server is on a different machine (client-server setup):**

Add `"env": {"HOOPS_WEBAPI_URL": "..."}` to the config — no system environment variable is needed.  
Claude Desktop passes this value to the MCP server process automatically:

```json
{
  "mcpServers": {
    "hoops-ai": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "C:\\path\\to\\HOOPS_AI-MCP\\mcp_server",
        "server.py"
      ],
      "env": {
        "HOOPS_WEBAPI_URL": "http://192.168.0.6:8000"
      }
    }
  }
}
```

> Replace `192.168.0.6` with the actual IP address of the machine running the WebAPI server.  
> This is the **only configuration change needed** on the client machine.

4. Save the file and **restart Claude Desktop**.

### (Optional) Import the Skill file

The `skills/` folder contains a `.skill` file that defines the expected behaviors and best-practice instructions for using this MCP server with Claude Desktop.  
Importing it gives Claude a consistent baseline for how to invoke the HOOPS AI tools — you can then customize the skill to match your own workflow.

**How to import:**

1. In Claude Desktop, go to **Settings** → **Skills**
2. Click **Import Skill** and select `skills/hoops-ai-tool-tips.skill` from this repository
3. Review and edit the skill content as needed for your use case

---

## Available MCP Tools

Claude Desktop can call these 30 tools using natural language:

### File Management

| Tool | Description |
|---|---|
| `upload_cad_model` | Upload a local CAD file to the server. Returns `file_id`, `filename`, and `already_existed`. Pass `file_id` to other tools to avoid re-uploading. |
| `open_cad_viewer` | Open a CAD file in the interactive 3D browser viewer. Returns `viewer_url` and `image_url` (PNG preview). |
| `terminate_CAD_viewer` | Terminate the last active viewer, or all viewers (`terminate_all=True`). |

### B-Rep Analysis

| Tool | Description |
|---|---|
| `get_brep_adjacency_graph` | Build a face adjacency graph from a CAD file. Returns graph data (nodes, edges, counts) and `image_url` (PNG visualization URL). |
| `get_brep_attributes` | Extract face and edge attributes (types, areas, lengths, dihedral angles, etc.) from a CAD file. |

### Manufacturing Feature Recognition (MFR)

| Tool | Description |
|---|---|
| `get_MFR_table_of_contents` | Get a summary of the MFR dataset. |
| `get_MFR_labels_description` | List all MFR label IDs, feature names, and descriptions. |
| `search_MFR_files` | Find CAD files in the MFR dataset that contain a given manufacturing feature. |
| `get_MFR_file_thumbnail` | Return the URL of the thumbnail PNG for a given dataset file ID. |
| `run_MFR_inference` | Run MFR inference on a CAD file. Returns predictions, probabilities, `viewer_url`, and `image_url`. |

### Shape Similarity Search

| Tool | Description |
|---|---|
| `search_similar_shapes` | Find the top-k most similar parts using HOOPS Embeddings and a FAISS index. Returns match IDs, similarity scores, and `image_url`. |
| `get_similar_part_image` | Return the URL of the pre-generated PNG thumbnail for a part filename returned by `search_similar_shapes`. |
| `get_similar_search_index_info` | Return metadata about the loaded FAISS index: status, entry count, embedding model name, vector dimension, file path, last-modified timestamp, and auxiliary metadata. Read-only. |
| `embed_cad_shape` | Compute the shape embedding for a single CAD part (no FAISS index or training required). Returns `file_id`, `filename`, `dim`, `model_name`, `num_bodies`, and `cached`. Embeddings are cached server-side for fast repeated calls. |
| `get_embedding_settings` | Return the server-wide active embedding model (`'signal'` or `'default'`). Used by `compare_cad_shapes`, `generate_shape_space_map`, and `create_similarity_index`. |
| `set_embedding_model` | Set the server-wide active embedding model: `'signal'` (HOOPS AI SIGNAL model, default) or `'default'` (1M model). Affects all subsequent compare/map/index-create calls. Existing indexes are unaffected. |
| `compare_cad_shapes` | Compute pairwise cosine-similarity scores for 2+ CAD parts (no FAISS index or training required). Returns an N×N similarity matrix, a ranked pair list, and per-file error details. Accepts local paths, existing `file_id`s, and/or a ZIP file in any combination. Uses the server-wide active model (default: `'signal'`). |

### Named Similarity Index Management

| Tool | Description |
|---|---|
| `create_similarity_index` | Create a new empty named index. The embeddings model is taken from the server-wide setting (`set_embedding_model`; default `'signal'`). Persists across server restarts. Returns `name`, `count` (0), `dim`, and `model`. Raises 409 if the name already exists. |
| `list_similarity_indexes` | List all similarity indexes including the built-in read-only `default` index. Each entry contains `name`, `count`, `last_modified`, `is_readonly`, and `model`. |
| `add_to_similarity_index` | Register CAD parts in a named index. Accepts local paths, `file_id`s, and/or a ZIP in any combination. The embedder is always the one recorded in the index at creation time (`model.json`). Returns `added`, `updated`, `index_count`, and `errors`. |
| `search_similarity_index` | Search a named index for the top-k most similar parts to a query CAD file. The correct embedder is selected automatically based on the index model. Returns hits with `id`, `score`, `metadata`, and an `image_url` result-grid PNG. |
| `remove_from_similarity_index` | Remove specific parts (by `file_id`) from a named index. Returns `removed` count and `index_count` remaining. |
| `delete_similarity_index` | Permanently delete a named index and all its stored data. Irreversible. Raises 403 for the built-in `default` index. |

### Shape Space Map

| Tool | Description |
|---|---|
| `generate_shape_space_map` | Generate a Shape Embeddings Map and **return the full result when complete** (blocks until done, up to 580 s). Accepts local paths, `file_id`s, and/or a ZIP. Returns `map_id`, `viewer_url`, per-part MDS `position`, similarity `matrix`, and MDS `stress` directly — no polling needed in normal use. |
| `get_shape_space_map_result` | Fallback poll for a map job started by `generate_shape_space_map`. Only needed if `generate_shape_space_map` returned `status: "processing"` due to a server-side timeout. Returns `status` (`"processing"` / `"done"` / `"failed"`); when `"done"`, the full result is included. |
| `query_shape_space_map` | Project a query CAD part onto an existing Shape Space Map (highlighted in magenta). Set `persist=true` to permanently add the query part to the original map. Returns `overlay_map_id`, `viewer_url`, and `nearest_parts`. |

### Part Classification

| Tool | Description |
|---|---|
| `run_part_classification_inference` | Run Part Classification inference on a CAD file. Returns the top-k predicted part classes with confidence scores (1–45 classes). |
| `get_part_classification_labels` | Return the full 45-class part label dictionary with IDs and descriptions. |
| `get_part_classification_table_of_contents` | Get a summary of the Part Classification dataset including available groups. |
| `get_part_classification_label_distribution` | Return per-class file count distribution across the Part Classification training dataset. |
| `get_part_classification_files` | Return the list of file IDs in the dataset that belong to a given part class (`label_id` 0–44). |
| `get_part_classification_preview` | Return a URL to a PNG thumbnail grid for a given part class (`label_id`, `k`, `grid_cols`). |

---

## Example Usage in Claude Desktop

Once the MCP server is registered and the WebAPI server is running, you can chat with Claude:

```
What HOOPS AI tools are available?
```

```
"C:\temp\helloworld.stp" — please display this 3D CAD file.
```

```
"C:\temp\Flange287.stp" — show this model and give me its B-Rep information.
```

```
Tell me about the manufacturing feature recognition dataset.
```

```
"C:\temp\nist_ftc_06_asme1_rd_sw1802.SLDPRT" — run manufacturing feature recognition and colorize by feature type.
```

```
"C:\temp\idler_sprocket.step" — search for similar parts to this component.
```

```
この2つのSTEPファイルはどれくらい似ている？ C:\temp\partA.stp と C:\temp\partB.stp
```

```
Compare these three parts and tell me which two are most similar:
C:\temp\bracket_v1.step, C:\temp\bracket_v2.step, C:\temp\bracket_v3.step
```

```
ZIPに入っているCADファイルの類似度マトリクスを出して。ファイルは C:\temp\parts.zip
```

```
Compute the shape embedding for C:\temp\flange.stp and tell me the embedding dimension and model name.
```

```
Create a named index called "my-brackets" and register all STEP files in C:\temp\brackets.zip.
```

```
Search my-brackets index for parts similar to C:\temp\new_bracket.step and show me the top 5 results.
```

```
Generate a 3D shape space map for these parts: C:\temp\partA.stp, C:\temp\partB.stp, C:\temp\partC.stp
```

```
Query the shape map <map_id> with C:\temp\new_part.step and show me the nearest parts.
```
