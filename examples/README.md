# Example definitions

These configuration templates use a prepared MaleCNS v1.0 index. Follow the [usage guide](../docs/guides/usage.md) to create and compare conditions.

1. Query an LC4 input and the intended DNp04/DNp01 observation neurons in your index. Inspect their directed connections and choose the members you want.
2. Copy `lc4-selection.template.json` to `lc4-selection.json` in the source root. Replace `INPUT_BODY_ID`, `TARGET_BODY_ID` and `PROTECTED_BODY_ID` everywhere in the copy with decimal-string IDs from your query. Keep the group labels aligned with `lc4-run.json`.
3. Preview the scope before creating it. The 120-node limit is an initial budget; adjust the scope if your chosen members are absent.
4. After creating the scope, use `python examples/lc4_conditions.py --case <your-case> --preview` to validate the experiment. Use `--output <new-file>` to write the two fixed conditions, then run the comparison through the CLI.

`lc4_conditions.py` generates conditions for your saved scope without running a simulation. `lc4-run.json` supplies the example parameters and group labels.
