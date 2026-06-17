# MERGE bucket specification

How the propagator's `merge_files` bucket works. Read alongside [PROPAGATION_RULES.md](PROPAGATION_RULES.md).

## Why MERGE exists

The propagator offers two basic file-copy policies:

- **OVERWRITE** -- unconditional copy on every sync. Template owns the file.
- **NOEXIST** -- copy only when missing. Consumer owns the file after first seed.

Neither fits a file that mixes template-shipped content with consumer-local content. `CLAUDE.md` is the canonical case: the template ships a small universal set of `@filename` imports (`@AGENTS.md`, `@docs/REPO_STYLE.md`, etc.), while each consumer typically adds repo-specific imports (`@docs/PRIMARY_DESIGN.md`, project-local notes) it wants preserved across syncs.

MERGE is the fifth file-copy bucket alongside `overwrite_files`, `noexist_files`, `devel_files`, `test_files`. Today it is implemented by a single helper, `propagate.files.merge_at_imports_safe`, that performs set-union merge on `@`-import lines.

## Set-union merge

Algorithm (see `propagate.files.merge_at_imports_safe`):

1. If consumer file missing: write template verbatim. Counter `created`.
2. Load the strip list from `meta/propagation/deprecated_claude_md.txt` (one entry per line, `#`-comments and blanks ignored).
3. Drop every consumer line whose stripped form matches the strip list.
4. Compute `@`-import additions: any `@`-line in the template that the consumer does not already contain.
5. Splice additions after the last surviving `@`-line in the consumer (or at the top after leading blanks if none). Preserve trailing-newline state.
6. If the merged result equals the existing consumer file byte-for-byte: counter `unchanged`. Otherwise counter `merged`.

The strip list is the only way to remove an `@`-import from existing consumers. Adding a line to `deprecated_claude_md.txt` strips it from every consumer on the next sync; the line stays in the strip list forever (a retired import never comes back).

Set-union has no error mode beyond "source file missing". Consumer state is always acceptable: fenced or plain, with or without consumer-local imports, with or without non-`@` content.

## Outcomes

| Consumer state | Outcome | Counter |
| --- | --- | --- |
| Missing | Write template verbatim | `created` |
| Already contains every template `@`-import, no deprecated lines | No change | `unchanged` |
| Missing one or more template `@`-imports, or carries deprecated lines | Add missing, strip deprecated | `merged` |
| Source file missing | Refuse to modify; surface error | `error` |

## Bucket dispatch

`compute_propagation_plan` emits `merge_files` as a list of repo-relative paths, parallel to `overwrite_files` / `noexist_files` / `devel_files` / `test_files`. The dispatcher in `propagate_style_guides.py:apply_file_bucket` calls `merge_at_imports_safe(source, dest, dry_run, counters)` for every entry. The helper returns one of `created | merged | unchanged | error` and shares the `merged_count` / `created_count` counters.

`MERGE_FILES` currently contains a single entry: `CLAUDE.md`. The bucket exists as a separate plan key so adding a future file that needs set-union semantics is a one-line manifest change.

META rules still win: `assert_not_meta()` runs at plan-append time and at dispatcher entry. A MERGE-tagged META file fails loud.

## Precedent

- `CLAUDE.md` previously used a fenced-region merge with HTML comment markers (`<!-- === TEMPLATE-MANAGED START === -->` / `END`). Migrated to set-union after fences proved to be bureaucracy with no payoff on a flat `@`-import list: every existing consumer would have needed a one-time hand edit before the propagator would touch their file. Strip list seeded with the two fence comment lines so existing consumers get cleaned on next sync.
- `.gitignore` uses a managed-block merge with its own fence markers (`# === UNIVERSAL ===` ... `# === END UNIVERSAL ===`) via a separate code path (`gitignore_block` plan key, not `merge_files`). Kept separate because it composes multiple template sources (universal + typed overlay) into one consumer file.
