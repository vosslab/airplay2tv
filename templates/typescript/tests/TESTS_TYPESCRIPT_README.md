# TypeScript test suite

These tests ship to every `REPO_TYPE=typescript` consumer via `propagate_style_guides.py`. The canonical correctness gate for the TS toolchain (typecheck, lint, format, Node tests) is `bash check_codebase.sh` -- pytest under `tests/` is reserved for cross-ecosystem checks (markdown links, ASCII compliance, etc.) propagated from the template root, not for shadowing the JS/TS toolchain.

## History

Earlier revisions of this folder shipped pytest mirrors of the JS/TS toolchain (`test_typescript_tsc.py`, `test_typescript_eslint.py`, `test_tsconfig_canonical.py`, `test_package_json_schema.py`, `test_eslint_config_present.py`, `test_smoke.mjs`). Those were removed in the 2026-05-24 sweep: each one either invoked `npx` via subprocess inside the pytest fast lane (PYTEST_STYLE.md violation), asserted hardcoded tsconfig defaults, or duplicated a check that `check_codebase.sh` already runs natively. Using a Python test runner to assert TS-ecosystem shape routed verification through the wrong tool. The TS ecosystem owns its own gates: `tsc`, `eslint`, `prettier`, `node --test`. `check_codebase.sh` wires them all together.

## Run the gate

From a TS-typed consumer repo:

```bash
bash check_codebase.sh          # typecheck, typecheck:lint, lint, format:check, css:policy (if present), test:node (if present)
bash check_codebase.sh --help   # usage
```

Playwright walkthroughs are not part of `check_codebase.sh`; run them manually with `npm run test:playwright` after `bash run_web_server.sh`.

## Adding a Node test

Drop a `test_<name>.mjs` in this folder. Step 6 of `check_codebase.sh` picks them up automatically (`node --import tsx --test 'tests/test_*.mjs'`) when at least one matches.

## Adding a Python test

Resist. If the check belongs to the JS/TS ecosystem, extend `check_codebase.sh` instead. Pytest in a typescript consumer is intentionally thin.

## Vendored Python tests in this overlay

`test_test_naming_conventions.py` -- enforces naming conventions for `tests/e2e/` and
`tests/playwright/` subtrees. Five rules: no `test_*.py` under `tests/playwright/` or
`tests/e2e/` (since `collect_ignore` would silently skip them, mismatching the name);
Python files in `tests/e2e/` must use the `e2e_*.py` prefix; shell files there must use
`e2e_*.sh`; any `.mjs` file with a Playwright import must live under `tests/playwright/`.
On failure, writes `report_test_naming_conventions.txt` at the repo root.
This test ships only to TypeScript repos because `tests/e2e/` and `tests/playwright/` exist
only in those repos; the checks early-skip when neither directory is present.
