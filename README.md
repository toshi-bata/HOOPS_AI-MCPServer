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

Claude Desktop can call these 17 tools using natural language.

> **Note:** Tools that mutate server state (named similarity indexes, embedding-model
> switching) or run long-running jobs (Shape Space Map) live in a separate, private
> `HOOPS_AI-MCPServer-demo` companion repository and are not included here. See that
> repo's README if you have access, or register it alongside this one in Claude
> Desktop for the full tool set.

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
| `get_brep_attributes` | Extract raw per-face and per-edge attributes (types, areas, lengths, dihedral angles, etc.) from a CAD file. For individual-entry questions, not counting. |
| `get_brep_type_counts` | Return face and edge counts grouped by type, aggregated server-side. Use for any counting question ("how many faces", "faces by type", totals). |

### Manufacturing Feature Recognition (MFR)

| Tool | Description |
|---|---|
| `run_MFR_inference` | Run MFR inference on a CAD file. Returns predictions, probabilities, `viewer_url`, and `image_url`. |

### Shape Similarity Search

| Tool | Description |
|---|---|
| `search_similar_shapes` | Find the top-k most similar parts using HOOPS Embeddings and a FAISS index. Returns match IDs, similarity scores, and `image_url`. |
| `get_similar_part_image` | Return the URL of the pre-generated PNG thumbnail for a part filename returned by `search_similar_shapes`. |
| `get_similar_search_index_info` | Return metadata about the loaded FAISS index: status, entry count, embedding model name, vector dimension, file path, last-modified timestamp, and auxiliary metadata. Read-only. |
| `search_similarity_index` | Search a named similarity index (created/managed via the private demo MCP server) for the top-k most similar parts to a query CAD file. Returns hits with `id`, `score`, `metadata`, and an `image_url` result-grid PNG. |
| `embed_cad_shape` | Compute the shape embedding for a single CAD part (no FAISS index or training required). Returns `file_id`, `filename`, `dim`, `model_name`, `num_bodies`, and `cached`. Embeddings are cached server-side for fast repeated calls. |
| `compare_cad_shapes` | Compute pairwise cosine-similarity scores for 2+ CAD parts (no FAISS index or training required). Returns an N×N similarity matrix, a ranked pair list, and per-file error details. Accepts local paths, existing `file_id`s, and/or a ZIP path. ZIP files are processed server-side (no large upload). Uses the server-wide active embedding model. |

### Part Classification

| Tool | Description |
|---|---|
| `run_part_classification_inference` | Run Part Classification inference on a CAD file. Returns the top-k predicted part classes with confidence scores (1–45 classes). |
| `get_part_classification_labels` | Return the full 45-class part label dictionary with IDs and descriptions. |
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
この部品の材料とコストを、似ている部品の実績から予測して
```

```
Predict the missing material and cost for this part based on similar parts' history.
```

```
"C:\temp\Flange287.stp" — show this model and give me its B-Rep information.
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

> **Note — ZIP file processing:** When a ZIP path is passed to `compare_cad_shapes`,
> the WebAPI server reads the file directly from the given path.  This requires the MCP
> client and the WebAPI server to be on the **same machine** (the default local setup).
> For remote setups (WebAPI on a separate host), use `upload_cad_model` to upload
> individual files first, then pass their `file_id`s.
