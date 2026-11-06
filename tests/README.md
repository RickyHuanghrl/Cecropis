# Tests

Run from the source root with your Python environment. Tests use small synthetic datasets and temporary directories. Service tests start local HTTP listeners and child processes.

Choose checks for the behavior being changed:

```sh
python -B -m unittest tests.test_core tests.test_intervention_events tests.test_evaluation_windows
python -B -m unittest tests.test_preparation tests.test_service_control
python -B -m unittest tests.test_task_definition tests.test_offline_report
node tests/js/check_default_language.cjs
node tests/js/check_display_boundaries.cjs
```

For all included Python tests:

```sh
python -B -m unittest discover -s tests -p 'test_*.py'
```

To check that generated language resources match their source messages:

```sh
python scripts/compile_ui_languages.py --check
```
