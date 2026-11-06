# Source tools

Run these tools from the source root with your configured Python environment. To start the workbench after preparing the example workspace:

```sh
python -m cecropis --workspace ../cecropis-data/workspace.json start --port 8501
```

| Tool | Purpose |
| --- | --- |
| `prepare_data.py` | Check/build/resume a local index, configure paths, remember/forget a binding, or open the workbench |
| `download_data.py` | Explicit download plans and resumable transfers to a required user-selected target |
| `download_precomputed_skeletons.py` | Transfer implementation used by the download tool; retains a standalone entry with required target |
| `compile_ui_languages.py` | Validate author dictionaries and regenerate the six runtime dictionaries and browser message bundle |
| `check_installation.py` | Check an installed distribution's API, CLI and bundled resources from outside the source tree |

Start with [first use](../docs/guides/first-use.md) and [downloads](../docs/guides/downloads.md). Each tool provides command details through `--help`.

For development checks, see [tests/README.md](../tests/README.md).
