#!/usr/bin/env bash
#
# Rename references to the old shared test helper module `git_file_utils`
# to its current name `file_utils`.
#
# Background: the starter-repo-template renamed tests/git_file_utils.py to
# tests/file_utils.py. Propagation ships the new module and removes the old
# one (it is listed in meta/propagation/deprecated_tests.txt), but
# consumer-authored tests and docs that referenced the old name by hand are
# not rewritten by propagation. Run this once from a consumer repo root to fix
# those local references.
#
# Usage (run from the consumer repo root; this script may live in the
# template checkout):
#   cd <consumer-repo-root>
#   bash /path/to/starter-repo-template/meta/tools/rename_git_file_utils.sh
#
# Rewrites tests/*.py and docs/*.md in the current directory, skipping
# CHANGELOG files whose history legitimately records the old name. Requires
# GNU sed. Idempotent: a second run finds no references and does nothing.

set -euo pipefail

old="git_file_utils"
new="file_utils"

# Missing glob matches expand to nothing instead of a literal pattern.
shopt -s nullglob

changed=0
for target in tests/*.py docs/*.md; do
	# Skip changelog files: their history mentions the old name on purpose,
	# and rewriting it would corrupt the historical record.
	case "$(basename "$target")" in
		CHANGELOG.md|CHANGELOG-*.md) continue ;;
	esac
	# Only rewrite files that actually mention the old module name.
	if grep -q "$old" "$target"; then
		sed -i "s/$old/$new/g" "$target"
		echo "rewrote: $target"
		changed=$((changed + 1))
	fi
done

if [ "$changed" -eq 0 ]; then
	echo "no references to $old found"
else
	echo "done: $changed file(s) updated"
fi
