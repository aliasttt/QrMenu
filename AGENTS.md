# Graphify query-first (managed)
For architecture, dependency, data-flow, or implementation-location questions, use Graphify before broad search when the project graph exists. If it is missing or source changed after the graph, run an incremental `graphify extract . --code-only --no-viz` from the workspace root; do not rebuild an unchanged graph. For a new root append `--exclude '.tmp-*/' --exclude '.vscode/extensions/' --exclude '.pnpm-store/' --exclude '.yarn/cache/' --exclude '.gradle/' --exclude 'staticfiles/' --exclude 'vendor/' --exclude '_cleanup_review/' --exclude 'e_config.py'`; keep Graphify defaults and `.gitignore` enabled.

Use focused `graphify query "..." --budget 1200`, `graphify explain "..."`, or `graphify path "A" "B"`. Never load `graphify-out/graph.json` or the whole `GRAPH_REPORT.md` into context. After Graphify identifies relevant locations, read only the needed source ranges and verify current code before editing.

Skip Graphify for a simple change whose file path is already known. If the graph is missing, stale, incomplete, or a query fails, continue with narrow `rg` and targeted source reads instead of stopping.

Graphify policy: local code AST only. Never use semantic document/media extraction, deep mode, `label`, LLM-backed `cluster-only`, API keys, persistent watchers, wiki, or extra exports. Keep `.gitignore` enabled; Graphify's sensitive-file and dependency/build/cache exclusions must remain active.
# End Graphify query-first

# Main branch release workflow (managed)
- Use `main` as the normal working and release branch, with upstream `origin/main`. Before changing files, inspect `git status`, the current branch, remotes, and upstream, then fetch `origin/main`. Preserve all unrelated uncommitted changes and WIP; never delete, discard, or include them automatically.
- Base work on the latest `origin/main`, not a fixed historical SHA. If local `main` is only behind and the worktree permits it, fast-forward it. If it has unpublished local commits, inspect them and rebase them onto the new `origin/main`; resolve clear conflicts by preserving both intended changes and rerun relevant checks. Ask only when a conflict requires a genuine product decision.
- Implement the requested change and run proportionate checks and tests. Stage only the files or hunks belonging to that task, commit with a clear message, and push to `origin main`. Never commit secrets, `.env` files, temporary output, or unrelated WIP.
- If push is rejected as non-fast-forward, fetch again, reconcile unpublished commits with the updated `origin/main`, repeat relevant checks, and retry a bounded number of times. Never use force-push, `reset --hard`, or delete other contributors' commits to resolve it.
- Distinguish authentication, authorization, and branch-protection failures from history divergence. Do not bypass repository protections; when user action is truly required, report the exact action concisely.
- Keep Scalingo app `qrmenu` connected for automatic deployment from this repository's `main` branch, preserving all other settings. After a push, follow deployment to its final result, verify the active release matches the pushed commit, and check web health. A successful push alone is not a successful release.
- Use SHAs internally for comparison and audit; do not ask the user to copy or select one. Final reports should normally state the change, test result, and release status briefly; on failure, state the cause and next action.
- Production data changes and migrations still require the project's backup procedure. Do not create empty commits, fake changes, or unnecessary deployments merely to activate this workflow.
# End Main branch release workflow
