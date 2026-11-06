# First use

This guide takes you from source code to your own local workspace. Python 3.11 or 3.12 is recommended.

## 1. Environment and command

Enter the source directory containing `cecropis/`, `scripts/`, `examples/` and `pyproject.toml`. Store datasets and results in their own directory, either outside the checkout or in its ignored `data/` subdirectory.

Windows PowerShell:

```powershell
$Source = 'C:\Projects\Cecropis'
$Data = 'E:\Cecropis data'
Set-Location -LiteralPath $Source
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install numpy scipy pyarrow
python -m cecropis --version
```

If the Python launcher is unavailable, use the full path to your Python 3.11/3.12 executable for `-m venv`. On subsequent visits, enter the source directory and activate the existing environment with `.\.venv\Scripts\Activate.ps1`; do not recreate it or reinstall dependencies. Set the data variables again when using commands that refer to them.

Linux / macOS, with a suitable Python and `venv` available:

```sh
SOURCE="$HOME/Projects/Cecropis"
DATA="$HOME/Cecropis data"
cd "$SOURCE"
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install numpy scipy pyarrow
python -m cecropis --version
```

Use your installed `python3.12` instead if appropriate. On subsequent visits, activate the existing environment. For an existing suitable environment, skip creation and use that environment's Python.

NumPy, SciPy and PyArrow are the runtime dependencies. Once they are available, use `python -m cecropis` from the source root for all command-line operations. Keep using the same environment and source directory when opening another terminal to inspect or stop the service.

Activation is optional. You can replace `python` with `.\.venv\Scripts\python.exe` in PowerShell or `.venv/bin/python` on Linux/macOS to use the environment directly. This leaves the shell unchanged, so no `deactivate` is needed afterward unless you previously activated an environment in that terminal.

## 2. Data and workspace

Recommended layout:

```text
Cecropis data/
  raw/                                  required Feather files
  processed/global-index/               connection index
  cases/                                saved calculation scopes
  results/                              results, tasks and analysis sessions
  geometry/male-cns-em-precomputed/      optional source skeletons
  geometry-cache/precomputed/           optional derived cache
  workspace.json
```

The example data directory can also be `Cecropis/data/`. The download and preparation commands create their output directories as needed; saved scopes and results are created when you use those features. Each location can instead be an absolute path on a different drive. Relative paths inside workspace JSON are resolved from the JSON's directory; command-line paths are resolved from the current directory.

The required connection and annotation files total **1,065,725,260 bytes**, excluding processing and temporary space. Read [Downloads](downloads.md) before transferring. Existing files can be reused.

PowerShell:

```powershell
python scripts/download_data.py plan --dataset connectivity --target "$Data/raw"
python scripts/download_data.py start --dataset connectivity --target "$Data/raw"
$Workspace = Join-Path $Data 'workspace.json'
python scripts/prepare_data.py check --raw "$Data/raw" --index "$Data/processed/global-index" --cases "$Data/cases" --runs "$Data/results" --output $Workspace
# Only when check reports can_build and you need a new index:
python scripts/prepare_data.py build --raw "$Data/raw" --index "$Data/processed/global-index" --cases "$Data/cases" --runs "$Data/results" --output $Workspace
```

POSIX shell:

```sh
python scripts/download_data.py plan --dataset connectivity --target "$DATA/raw"
python scripts/download_data.py start --dataset connectivity --target "$DATA/raw"
WORKSPACE="$DATA/workspace.json"
python scripts/prepare_data.py check --raw "$DATA/raw" --index "$DATA/processed/global-index" --cases "$DATA/cases" --runs "$DATA/results" --output "$WORKSPACE"
# Only when check reports can_build and you need a new index:
python scripts/prepare_data.py build --raw "$DATA/raw" --index "$DATA/processed/global-index" --cases "$DATA/cases" --runs "$DATA/results" --output "$WORKSPACE"
```

`plan` and `status` inspect the download; `start` transfers the files. After downloading, `check` reports whether the local data is ready to use or needs an index.

`build` creates the connection index and workspace configuration. Allow additional disk space for processing and the resulting index.

**Existing compatible index:** skip download/build and use `configure`. It checks readiness and creates workspace.json without rebuilding the index or requiring you to write JSON.

PowerShell, using the data location from step 1:

```powershell
$Workspace = Join-Path $Data 'workspace.json'
python scripts/prepare_data.py configure --index "$Data/processed/global-index" --cases "$Data/cases" --runs "$Data/results" --output $Workspace
```

POSIX shell:

```sh
WORKSPACE="$DATA/workspace.json"
python scripts/prepare_data.py configure --index "$DATA/processed/global-index" --cases "$DATA/cases" --runs "$DATA/results" --output "$WORKSPACE"
```

Use your actual index location if it differs. An existing workspace with the same locations is reused; a conflicting file is not silently overwritten.

After an interrupted build, run `check` again. Use `resume` in place of `build` if the reported state permits resuming; otherwise choose a new index destination and build there.

For custom layouts, the generated workspace file has the following structure. Ordinary setup uses the commands above; editing JSON is optional:

```json
{
  "kind": "workspace_config",
  "version": 1,
  "paths": {
    "raw": "raw",
    "index": "processed/global-index",
    "cases": "cases",
    "runs": "results",
    "skeletons": "geometry/male-cns-em-precomputed",
    "skeleton_cache": "geometry-cache/precomputed"
  }
}
```

`index`, `cases` and `runs` are required; the skeleton fields are optional. Preparation-generated configurations use absolute paths. Handwritten relative paths can move with a data directory. `~` is expanded, but strings such as `$HOME` are not evaluated as shell code.

## 3. Start, inspect and stop

From the source root, with the configured Python environment selected, this complete command starts a workspace stored in the sibling `cecropis-data` directory:

```sh
python -m cecropis --workspace ../cecropis-data/workspace.json start --port 8501
```

Replace the workspace path with your own JSON file. `start` launches the web service; `--port` selects the port used in the browser URL. Running only `python -m cecropis` reports a missing subcommand and does not launch the service.

If you followed this guide's custom `$Data`/`DATA` examples, use the workspace variable created in step 2 instead:

PowerShell:

```powershell
python -m cecropis --workspace $Workspace start --port 8501
```

POSIX shell:

```sh
python -m cecropis --workspace "$WORKSPACE" start --port 8501
```

Open **http://127.0.0.1:8501/** and keep the terminal running. `serve` is an equivalent command. The service listens on your machine only. Choose another port if 8501 is occupied.

In another terminal, enter the source directory and use the same environment, OS user and settings location:

```sh
python -m cecropis status --port 8501
python -m cecropis stop --port 8501
```

Both return JSON with a status. Before stopping, finish, pause or cancel active work and save your comparisons and drafts. A service started with a custom `CECROPIS_CONFIG_HOME` must be controlled with the same setting.

You can also press Ctrl+C in the service terminal. Closing a browser tab or deactivating an environment does not stop the process. Restart with the same start command and reopen a saved result or session. Resume any paused computation separately.

The ASCII wordmark appears only in an interactive terminal. `start --no-banner` suppresses it; redirected streams do not receive it. Startup URL and stop instructions go to stderr. Normal CLI JSON stays on stdout.

Successful HTTP requests are quiet by default. Add `--access-log` to the start command when you need the full request log for troubleshooting.

## 4. Binding and language preferences

With a valid index, the workbench opens directly, even without an initial calculation scope. Otherwise data settings let you check and bind existing locations and enter the workbench on the same port. The page does not download, build or silently overwrite configurations.

Explicit CLI paths override corresponding `--workspace` paths. Remembered locations apply when no workspace or explicit data binding is supplied. When specifying paths directly, include all locations needed for that workspace.

When no workspace or applicable explicit paths supply `cases`/`runs`, their defaults are `workspace/cases` and `workspace/results` under the OS user data directory:

| OS | Default data directory |
| --- | --- |
| Windows | `%LOCALAPPDATA%/cecropis` |
| Linux | `$XDG_DATA_HOME/cecropis`, otherwise `~/.local/share/cecropis` |
| macOS | `~/Library/Application Support/cecropis` |

These defaults are not inferred from the chosen index. To keep all results on your data drive, specify them as in the workspace examples.

**Remember location** stores only data locations, not an experiment or draft. **Forget location** removes the dedicated binding without deleting data, results or your workspace JSON. An explicit `--workspace` still applies. CLI equivalents are `python scripts/prepare_data.py remember --workspace <file>` and `python scripts/prepare_data.py forget`.

Settings use `%LOCALAPPDATA%/cecropis` on Windows, `$XDG_CONFIG_HOME/cecropis` (otherwise `~/.config/cecropis`) on Linux, and `~/Library/Application Support/cecropis` on macOS. An absolute `CECROPIS_CONFIG_HOME` overrides settings and default data into its `settings/` and `data/` subdirectories.

New browser profiles default to **English** regardless of browser language. Select any of the six supported languages in the interface; a valid saved preference is retained. Brand names, user names, body IDs and original annotations remain unchanged. Browser preferences do not change calculations; HTML reports use the explicitly selected export language.

## 5. First experiment and troubleshooting

Follow [the browser workflow](usage.md#browser-workflow). Querying and selecting do not run the propagation model; creating a scope writes data, and running a comparison performs computation. Start with a small scope and a fixed comparison.

| Problem | Action |
| --- | --- |
| `No module named cecropis` | Enter the source directory containing `cecropis/`, and use `python -m cecropis` with the configured environment. |
| PowerShell blocks Activate.ps1 | Use `.\.venv\Scripts\python.exe` in place of `python` in the commands, or use an environment you can activate. |
| Missing NumPy/SciPy/PyArrow | Install the missing dependency into your own environment, not an unrelated global Python. |
| Incompatible/incomplete index | Run `prepare_data.py check` with your paths and follow the reported issue. Use `resume` when eligible, or build into a new destination. |
| Result identity mismatch | Open the original scope; do not edit identity fields to force compatibility. |
| Skeletons missing | Check source and published cache paths; downloading is not cache preparation. See [Geometry](geometry.md). |
| Save failed | Inspect permissions, free space or name conflicts; retain the unsaved content and retry. |
| Stop reports busy | Finish, pause or cancel the active operation; then retry. |
