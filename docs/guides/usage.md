# Using Cecropis

Start with [First use](first-use.md) and bind your own data. The browser and CLI share the computation core. Display preferences and selections do not change an experiment.

## Browser workflow

The following steps use the English interface labels. Start with a small scope and a short run.

1. In **Find nodes**, search for a neuron type or body ID. Click an ID to inspect annotations and directed neighbors. Use row checkboxes to select scope seeds; clicking an ID only opens its details.
2. Click **Build a scope from selected nodes** to open **Paths & scope**, then expand **Scope & roles**. Check the seed IDs, direction, expansion hops and compute node limit. Click **Preview scope** and check that the intended input, candidate and output members are included. If the node limit truncated the selection or a required member is missing, adjust the scope and preview again.
3. Enter a **Scope name** and fill the input and output body-ID fields with members of the previewed scope. The current form requires an input group and both **Output A** and **Output B**, with distinct output names and at least one member in each. Choose **Candidate node scope**: the default uses calculation nodes outside the input and output groups; **All calculation nodes** uses the whole scope; **Exact body IDs** lets you specify members. The candidate group must also be nonempty. Click **Save & open scope**. Creating the scope saves its data; it does not run the propagation model.
4. In **Inputs & interventions**, set **Update count**, input events, observation sets and evaluation windows. Use **Edit members** to enter body IDs. Configure a node or edge intervention. For a multi-event plan, use **Check plan & overlaps** before adding the condition. To define a no-intervention control, choose **Multi-event plan** and remove its intervention event rows, keeping the input events.
5. Open **Compare conditions**, expand **Conditions to compare**, enter a **Condition name** and click **Add current condition**. This copies the current configuration into the pending list without running it. Return to **Inputs & interventions** to edit the draft, then add each further condition under a different name. All conditions in one comparison must share the update count, model parameters α and ρ, and observation names, members and evaluation windows. Input events and interventions may differ. If adding fails, read the message below the add button. To revise a pending condition, remove it from the list and add the corrected draft.
6. Click the **Compare conditions** button within the page to calculate the pending list; the sidebar item with the same name only opens the page. Select a result condition to view its curves, metrics and any configured constraints. Click **Save comparison results** and check the saved status. To edit a result's configuration, use **Replace current draft with this condition**; simply viewing it leaves the draft unchanged. Completed conditions that fail constraints can still be inspected and saved.
7. To export the comparison, stay on **Compare conditions**, choose the report conditions and interface language, then click **Preview report** and **Export HTML & CSV**. Download the files from the links that appear. A change of language or report selection requires a new preview. Saving an analysis session is optional and is not required for this export.

For differences and replay, select a result condition and click **Analyze this condition**. In **Analysis & replay**, open **Dynamic replay** → **Recording and preparation** when recordings are needed. Set the replay IDs and budgets, click **Check replay scope**, then **Prepare replay** and **Save replay**. Preparation may run the baseline and intervention again; playing a prepared recording or changing its colors uses the saved states. Existing recordings can be reused. A search report contains multiple plans: select a plan, request its curves if needed, then analyze a condition of the resulting comparison.

To retain an analysis view, expand **Save analysis session** in **Analysis & replay** and click the button with the same name. In the **Save scene** dialog, enter an **Analysis session name**, choose whether to include the current valid draft, and click **Save scene**. **Spatial browser** has its own **Save scene** button for the current spatial view. Reopen saved sessions through **Workspace & history**; keep their referenced results and data available. See [3D morphology](geometry.md) for skeleton preparation and spatial controls.

Scope size, intervention size, recording budget and display budget are different. An exhausted search budget describes the evaluated subset, not a global optimum.

### Configuring and reading a comparison

- Time is measured in model update steps, not milliseconds. An event from `start` to `stop` acts on updates `start` through `stop - 1`; an observation window `[4, 20)` evaluates the 16 resulting states `x(5)` through `x(20)`.
- Input amplitude applies to each selected member. Overlapping input events add. Intervention gain is between 0 and 1: 1 leaves activity unchanged and 0 blocks the targeted node's new state or the selected edge's transmission. Node gains act after the state update; edge gains act on that edge's input contribution. Overlapping intervention gains multiply.
- An observation curve is the mean activity of its members. Each intervention is compared with a baseline using the same input protocol. Window metrics summarize only the chosen evaluation window.
- Delta means intervention minus baseline. Relative change divides this difference by the baseline response. A near-zero baseline gives an undefined relative value, not zero percent; use an absolute metric for that case.
- Search target loss means a decrease in the target response. Each protected observation has its own maximum allowed decrease. Relative thresholds are percentages in the interface and fractions in JSON; absolute thresholds use mean activity.

## CLI walkthrough

Run from the source root with the environment and data variables from [First use](first-use.md). These commands create a scope, condition definitions and results. Choose unused destination names; do not overwrite your own work.

Copy `examples/lc4-selection.template.json` to `lc4-selection.json` in the source root. Query LC4, DNp04 and DNp01 in your local index, inspect their connections, and replace all three ID placeholders in the copy. The template uses a two-hop outgoing neighborhood with a 120-node limit; adjust it if the intended input and observation members are outside the scope. See [example definitions](../../examples/README.md).

In the commands below, replace `INPUT_BODY_ID` with the input ID you chose. Each query reads your local index.

PowerShell:

```powershell
python -m cecropis --workspace $Workspace find --query LC4 --limit 10
python -m cecropis --workspace $Workspace neighbors --id "INPUT_BODY_ID" --direction outgoing --limit 20
$Case = Join-Path $Data 'cases/lc4-intro'
python -m cecropis --workspace $Workspace case --selection lc4-selection.json --destination $Case
$Conditions = Join-Path $Data 'lc4-conditions.json'
python examples/lc4_conditions.py --case $Case --preview
python examples/lc4_conditions.py --case $Case --output $Conditions
$Saved = python -m cecropis --workspace $Workspace --case $Case compare --config $Conditions | ConvertFrom-Json
$Result = $Saved.folder
python -m cecropis comparison-read --source $Result
python -m cecropis report-preview --source $Result --language en
python -m cecropis report-export --source $Result --language en --destination "$Data/lc4-report-en"
```

POSIX shell:

```sh
python -m cecropis --workspace "$WORKSPACE" find --query LC4 --limit 10
python -m cecropis --workspace "$WORKSPACE" neighbors --id "INPUT_BODY_ID" --direction outgoing --limit 20
CASE="$DATA/cases/lc4-intro"
python -m cecropis --workspace "$WORKSPACE" case --selection lc4-selection.json --destination "$CASE"
CONDITIONS="$DATA/lc4-conditions.json"
python examples/lc4_conditions.py --case "$CASE" --preview
python examples/lc4_conditions.py --case "$CASE" --output "$CONDITIONS"
RESULT=$(python -m cecropis --workspace "$WORKSPACE" --case "$CASE" compare --config "$CONDITIONS" | python -c 'import json,sys; print(json.load(sys.stdin)["folder"])')
python -m cecropis comparison-read --source "$RESULT"
python -m cecropis report-preview --source "$RESULT" --language en
python -m cecropis report-export --source "$RESULT" --language en --destination "$DATA/lc4-report-en"
```

Use `lc4_conditions.py` to turn the `lc4-run.json` parameter template into conditions for your saved scope; do not pass the template directly to `run --config`. The generated comparison contains two conditions: unchanged gain 1 and attenuated gain 0.2, for 40 steps with shared inputs and observations. Preview checks the definition without writing or simulating. `--output` writes a new conditions file. `compare` runs and saves the comparison; use its returned `folder` for later commands.

Reports support `en`, `zh-CN`, `ja`, `fr`, `de` and `es`; the CLI defaults to `en`. Repeat `--condition <exact saved name>` to select conditions, or omit it for all. Preview reports export details and size; export creates `report.html`, `metrics.csv` and `curves.csv` in a new destination using the saved results. HTML stays in the generated language; CSV/JSON keys and numeric values remain stable.

Global options (`--workspace`, `--case`, `--runs`, etc.) precede the subcommand. Use `python -m cecropis --help` and `python -m cecropis <command> --help` for exact arguments. `python -m cecropis start`/`serve` run the local workbench; `status` and `stop` control the specified port.

## Other task entry points

Use the following subcommands after `python -m cecropis`. Each command's `--help` lists its arguments. A preview-capable command is non-computing only when its explicit preview option is used. `--context` baseline inspection does propagate.

| Task | CLI subcommands |
| --- | --- |
| Scope selection and boundaries | `scope`, `scope-boundary`, `scope-external` |
| Nested expansion and fixed comparisons | `scope-expand`, `compare-scopes`, `compare-scope-plans` |
| Grouped connectivity and real edges | `group-analyze/read/features/similar/members/pair` (separate commands) |
| Pathways and forward runs | `pathways`, `forward`, `run` |
| Node-set search | `sensitivity`, `search`, `joint-search`, `joint-evaluate` |
| Timing, withdrawal and reduction | `timing-explore`, `reduction-analyze` |
| Node/edge operations and combinations | `operations-compare`, `operation-search` |
| Batch input response | `responses`, `responses-read`, `responses-nodes`, `responses-curves` |
| Differences, replay and sessions | `difference-prepare/read`, `replay-prepare/read`, `session-read` |
| Fixed task sharing | `task-export/read/preview/prepare/run` |
| Persistent local tasks | `local-submit/list/read/check/run/pause/cancel/copy` |
| Locations and skeletons | `spatial-overview/locate/geometry`, `skeleton-*` |

Slash-separated table entries denote individual command names, not literal shell syntax. `scope --config` takes the scope-selection object (`body_ids`, `hops`, `direction`, `max_nodes`, `category`), not the enclosing case-creation document with `scope` and `groups`. Some structural operations save artifacts even though they perform no propagation; check the command's role.

## Results and state

- Drafts become calculation definitions only through explicit run/add-condition actions. Viewing a result, focusing a node, selecting members and adopting a draft are separate operations.
- Unrecorded, missing-coordinate, unrun, cancelled, failed and undefined near-zero relative values are not zero. Update step `t` produces state `t+1`; state zero is the initial state.
- All calculation-scope nodes propagate. Interventions modify only specified items; recording and geometry budgets limit storage/display, not the computation scope.
- Persistent pause/resume applies to `response_exploration` and `operation_search` local tasks. A readable old report without a trustworthy checkpoint is not resumable. Resume does not enlarge an exhausted budget. Cancelling another background operation does not promise resumability.
- Analysis sessions reference local results and recordings; they do not carry raw data or matrices. Sharing a fixed task is a separate action, with explicit content verification across independent indexes.
- HTML reports let recipients read exported results without running the workbench. Save an analysis session when you want to return to a working view and its draft.
