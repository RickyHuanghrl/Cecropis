# 3D morphology

Skeletons are optional. With prepared local skeletons, **Spatial browser** shows a global morphology overview, on-demand detail and recorded model activity. Connectivity alone is sufficient for structural analysis and model calculations.

## Locations and preparation

Use the environment and variables from [First use](first-use.md). The download target must match the workspace's `skeletons` field; see [Downloads](downloads.md). Recommended layout:

```text
<data>/processed/global-index
<data>/geometry/male-cns-em-precomputed
<data>/geometry-cache/precomputed
```

Without an explicit source path, Cecropis derives `geometry/male-cns-em-precomputed` from two levels above the bound index. Thus `<data>/processed/global-index` maps to the layout above. For a custom index layout, set `skeletons` explicitly. For an explicit source, the default cache is `geometry-cache/precomputed` under two levels above that source. Set `skeleton_cache` explicitly for other layouts. Its internal `spatial-v2` subdirectory must not be repeated in the configured root.

Workspace-relative paths use the JSON directory; CLI-relative paths use the current directory. Raw skeletons may be on read-only storage and the cache on another writable drive. Source and cache must not overlap. To reuse an existing cache, set `skeleton_cache` to its root.

After downloading, explicitly process local morphology. PowerShell:

```powershell
python -m cecropis --workspace $Workspace skeleton-status --directory "$Data/geometry/male-cns-em-precomputed" --cache "$Data/geometry-cache/precomputed"
python -m cecropis --workspace $Workspace skeleton-update --directory "$Data/geometry/male-cns-em-precomputed" --cache "$Data/geometry-cache/precomputed" --max-files 100 --max-input-mib 512 --max-cache-mib 2048 --progress
```

POSIX shell:

```sh
python -m cecropis --workspace "$WORKSPACE" skeleton-status --directory "$DATA/geometry/male-cns-em-precomputed" --cache "$DATA/geometry-cache/precomputed"
python -m cecropis --workspace "$WORKSPACE" skeleton-update --directory "$DATA/geometry/male-cns-em-precomputed" --cache "$DATA/geometry-cache/precomputed" --max-files 100 --max-input-mib 512 --max-cache-mib 2048 --progress
```

`skeleton-status` reports preparation progress. The example `skeleton-update` processes up to 100 objects within its input and cache budgets, not the whole dataset. Repeat it to process remaining files; valid prepared objects are reused. Cancellation retains completed work. Use `skeleton-update --help` to adjust the limits.

Once configured, start the workbench as described in [First use](first-use.md#3-start-inspect-and-stop). `--skeleton-directory` and `--skeleton-cache` after `start`/`serve` override the configured paths. Opening the page does not process unprepared skeleton files.

## Coordinates and meaning

| Source | Current conversion to micrometres |
| --- | --- |
| MaleCNS v1.0 annotation positions | Unmirrored EM, 8 nm voxel coordinates × 0.008 |
| Precomputed binary skeletons | Unmirrored EM, 1 nm units × 0.001 |
| Legacy SWC reader | Unmirrored EM, 8 nm units × 0.008; verify provenance for other sources |

Annotation points use a valid soma location or, where available, a truncated endpoint toward the soma. The latter is not a measured soma. Nodes without coordinates remain accessible in tables. Do not mix mirrored or template coordinates with the unmirrored EM data.

The global overview simplifies branches; more detail loads for the current view and selection within display budgets. Tube width is a display setting because these skeletons do not provide measured radii. Directed connections come from the connectivity table, not proximity between branches.

## Selection and replay

Rotate, zoom or pan to explore the scene. Focus a node to inspect it, or add it to the shared selection before sending members to a scope or intervention. Camera and layer changes do not run the model.

Activity colors use the selected result. A window mean is a summary; replay uses recorded time steps. One model value colors a whole neuron, rather than simulating activity along individual branches. Missing recordings are not zero activity; prepare the required recording explicitly before replaying it.

Save an analysis session to retain the camera, layers, selection and result references. Keep the referenced data and caches available for restoration. Tables and 2D analysis remain available when WebGL cannot be used.

## Command-line access and SWC

Use `python -m cecropis skeleton-status`, `skeleton-query`, `skeleton-node` and `skeleton-update`; each command has `--help`. A node export reads prepared detail without processing source files.

For local SWC files, use filenames `<body ID>.swc` and set the workspace `geometry` field to their directory. This field is separate from `skeletons`, which points to precomputed binary files. Confirm the SWC coordinate convention before using another source. Requests exceeding display limits report an error; reduce the selection or use prepared precomputed skeletons for global browsing.
