# Data downloads

Downloading and subsequent index/geometry processing are separate actions. See [First use](first-use.md) for environment and workspace setup and [Data sources](../reference/data-sources.md) for attribution. The workbench never downloads data automatically.

## Files and sizes

| Dataset | File or objects | Recorded size | Required |
| --- | --- | --- | --- |
| MaleCNS v1.0 minconf=0.5 connections | `connectome-weights-male-cns-v1.0-minconf-0.5.feather` | 1,051,241,946 B | Yes |
| Matching annotations | `body-annotations-male-cns-v1.0-minconf-0.5.feather` | 14,483,314 B | Yes |
| Unmirrored EM precomputed skeletons | 211,573 objects plus info | 5,553,228,864 B | Optional |

Use the download plan below to check file sizes before transferring. The [official download page](https://male-cns.janelia.org/download/) lists connectivity, annotations and skeleton coordinate spaces. Allow additional disk space for indexes, processing, morphology caches and results. Choose precomputed skeletons for the spatial view; the approximately 9.30 GB SWC collection is an alternative, not an additional required download.

## Plan and transfer

From the source root, use your configured Python environment and the data variable from [First use](first-use.md).

PowerShell:

```powershell
python scripts/download_data.py plan --dataset connectivity --target "$Data/raw"
python scripts/download_data.py status --dataset connectivity --target "$Data/raw"
python scripts/download_data.py start --dataset connectivity --target "$Data/raw"
```

POSIX shell:

```sh
python scripts/download_data.py plan --dataset connectivity --target "$DATA/raw"
python scripts/download_data.py status --dataset connectivity --target "$DATA/raw"
python scripts/download_data.py start --dataset connectivity --target "$DATA/raw"
```

| Operation | Effect |
| --- | --- |
| `plan` / `status` | Inspect existing manifests and complete/partial file lengths; no dataset-content transfer. |
| `plan --refresh-listing` | Explicitly fetch skeleton listing metadata and save a download control manifest. |
| `start` | Create target/control directories, transfer missing data and retain partial files and provenance. |
| `prepare_data.py check` | Inspect local schemas and index headers; no download or construction. |
| `prepare_data.py build` / `resume` | Scan sources or finalize retained staging and write the index. |
| `skeleton-update` | Process local skeletons and publish derived caches. |

For skeletons, obtain listing metadata first, review the total and your remaining bandwidth, then explicitly transfer. For example in PowerShell:

```powershell
python scripts/download_data.py plan --dataset skeletons --target "$Data/geometry/male-cns-em-precomputed" --refresh-listing
python scripts/download_data.py start --dataset skeletons --target "$Data/geometry/male-cns-em-precomputed" --workers 8
```

In POSIX shell use `$DATA` instead of `$Data`. `--target` is required; relative paths use the current directory. The downloader does not bind a workspace. Put the matching target into its `raw` or `skeletons` field. The sibling `<target-name>.download` directory contains download control information, not skeleton input.

## Interruptions and errors

Ctrl+C stops the transfer and retains incomplete files. Run `start` again with the same target to resume. A file becomes final only after the transfer and expected-length check complete. `status` checks lengths, not whole-file hashes. Downloads to one target use an exclusive lock; do not delete lock files to run competing writers.

Read stderr for HTTP, SSL and permission errors. If a partial file exceeds the expected size or a completed file conflicts with the listing, check the source and destination before replacing that file.

Data comes from the original storage; Cecropis does not rehost it. Keep dataset version, confidence threshold, license and provenance records, including the adjacent control directory, when relocating downloaded data. Continue with [index preparation](first-use.md#2-data-and-workspace) or [geometry preparation](geometry.md).
