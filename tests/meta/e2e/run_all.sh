#!/usr/bin/env bash
# run_all.sh -- Run all e2e_*.sh and e2e_*.py harnesses and report pass/fail.
# Usage: bash tests/meta/e2e/run_all.sh
# Python harnesses run via: source source_me.sh && python3 <script>
# Exits non-zero if any harness fails.
# Template-meta: lives under tests/meta/e2e/; never propagates; removed by reset.

# Resolve repo root via git, not by deriving from cwd
REPO_ROOT="$(git rev-parse --show-toplevel)"
E2E_DIR="${REPO_ROOT}/tests/meta/e2e"

pass_count=0
fail_count=0
overall_exit=0

# Run a single harness and record pass/fail.
# Usage: run_harness <label> <cmd> [args...]
run_harness() {
	local label="$1"
	shift
	printf "  [RUN] %s\n" "${label}"
	if "$@"; then
		printf "  [PASS] %s\n" "${label}"
		pass_count=$((pass_count + 1))
	else
		printf "  [FAIL] %s\n" "${label}"
		fail_count=$((fail_count + 1))
		overall_exit=1
	fi
}

printf "=== E2E test runner ===\n"
printf "E2E dir: %s\n\n" "${E2E_DIR}"

# Collect shell harnesses
sh_found=0
for sh_script in "${E2E_DIR}"/e2e_*.sh; do
	# Guard against empty glob expansion
	test -f "${sh_script}" || continue
	sh_found=$((sh_found + 1))
	run_harness "$(basename "${sh_script}")" bash "${sh_script}"
done

if [ "${sh_found}" -eq 0 ]; then
	printf "  (no e2e_*.sh scripts found)\n"
fi

# Collect Python harnesses
py_found=0
for py_script in "${E2E_DIR}"/e2e_*.py; do
	# Guard against empty glob expansion
	test -f "${py_script}" || continue
	py_found=$((py_found + 1))
	# Run python harnesses via source source_me.sh for correct environment
	run_harness "$(basename "${py_script}")" bash -c "source '${REPO_ROOT}/source_me.sh' && python3 '${py_script}'"
done

if [ "${py_found}" -eq 0 ]; then
	printf "  (no e2e_*.py scripts found)\n"
fi

printf "\n=== Results: %d passed, %d failed ===\n" "${pass_count}" "${fail_count}"
exit "${overall_exit}"
