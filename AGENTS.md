# Instructions for AI Agents

## Project context

- Read [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) before changing project code. It is the detailed source of truth for the `.nwf` format, verified behavior, implementation decisions, and open topics.
- Use [manual-sharepoint-2019-dla-poczatkujacych-v3 (1).md](manual-sharepoint-2019-dla-poczatkujacych-v3%20(1).md) for the SharePoint export procedure and the naming conventions in `DaneZeSkryptu/`.
- Current status (2026-09-17): the parser, metadata loader, action catalog, Markdown/Mermaid report builder, and CLI are implemented. Reports for four example workflows have been manually verified. Automated tests are still an open follow-up; do not claim that a test suite exists.

## Context and tool usage

- Prefer `lean-ctx` whenever it is available. Use `ctx_compose` for initial orientation, then the narrowest suitable `ctx_read`, `ctx_search`, `ctx_glob`, `ctx_tree`, `ctx_callgraph`, or `ctx_shell` operation.
- For shell commands, prefer `lean-ctx -c "<command>"` or `ctx_shell`. For file exploration, prefer `ctx_read`/`ctx_search` over broad dumps.
- Use `task` or `signatures` reads for orientation, `anchored` reads before edits, and `diff` reads after edits. Keep context local and recover omitted details with targeted searches or `ctx_expand` when available.
- Use `ctx_patch` when the lean-ctx profile exposes it. Otherwise use the workspace editor/apply-patch tooling. If lean-ctx is unavailable, continue with the narrowest native VS Code or PowerShell tool rather than blocking.
- The lean-ctx tool profile is set to `power` (full tool registry). Prefer `ctx_*` tools over native search/read/terminal equivalents whenever both are available.
- All network traffic goes through the local proxy `http://127.0.0.1:3001` (VS Code `http.proxy`, integrated-terminal `HTTP_PROXY`/`HTTPS_PROXY`, repo-local git config, lean-ctx MCP env). Do not bypass it or disable TLS verification.
- Before a change, identify the code path that directly controls the behavior and one cheap executable check that can disconfirm the hypothesis. After the first edit, run that focused check before broadening the work.

## Run and verify

Use the Python launcher available on this machine:

```powershell
py tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out
```

- Do not replace `py` with `python`; the latter is not the working interpreter here.
- The generator has no external dependencies and uses the Python standard library.
- After changes to the report generator, regenerate `out/` and inspect `out/index.md` plus at least one representative workflow report.
- Preserve existing generated-report formats unless the task explicitly changes them. Mention any unrelated pre-existing failures instead of repairing them incidentally.

## Domain constraints

- `.nwf` files contain an outer XML document and an escaped inner XML document. Parse both layers with the existing parser conventions.
- Nested Nintex actions are under `ChildActivities/NWActionConfig`; do not assume `Then`, `Else`, or another branch tag.
- Keep `FieldResolver` list-aware. The same SharePoint `InternalName` can have different meanings on different lists; pass the appropriate list context when resolving fields.
- Preserve the fallback for unknown action types and the `UNKNOWN_TYPES_SEEN` reporting path in `index.md`.
- Large `.nwf` files often contain very long or single-line XML. Inspect them with a small targeted Python script through `ctx_shell`/`lean-ctx -c` when normal file search output is truncated.

## Change conventions

- Keep changes minimal and aligned with the existing modules in `tools/nwf_report/`.
- Do not duplicate the detailed project documentation in this file; update [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) when verified technical facts change.
- Prefer standard-library solutions and existing helpers. Do not add dependencies without a concrete need.
- When adding behavior, add focused tests if the project test setup has been introduced; until then, use the existing four sample workflows for regression checks.
- Do not create commits or branches unless explicitly requested.

## Future customization

The next useful project customization would be a dedicated `.github/agents/nwf-report.agent.md` if workflow-report tasks become frequent enough to justify isolated context and specialized tooling. Use `/chronicle improve` after future sessions to refine these instructions from recurring friction.