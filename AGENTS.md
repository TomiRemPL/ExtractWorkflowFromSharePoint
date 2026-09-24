# Instructions for AI Agents

## Project context

- Read [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) before changing project code. It is the detailed source of truth for the `.nwf` format, verified behavior, implementation decisions, and open topics.
- Use [manual-sharepoint-2019-dla-poczatkujacych-v3 (1).md](manual-sharepoint-2019-dla-poczatkujacych-v3%20(1).md) for the SharePoint export procedure and the naming conventions in `DaneZeSkryptu/`.
- Current status (2026-09-19): the parser, metadata loader, action catalog, Markdown/Mermaid report builder, CLI, and generated interactive HTML portal are implemented. Reports for four example workflows have been manually verified. The Python test suite contains 24 passing tests; browser-level Playwright coverage for drag/zoom/SVG clicks/search/navigation remains an open follow-up.

## Context and tool usage

- Prefer `lean-ctx` whenever it is available. Use `ctx_compose` for initial orientation, then the narrowest suitable `ctx_read`, `ctx_search`, `ctx_glob`, `ctx_tree`, `ctx_callgraph`, or `ctx_shell` operation.
- For shell commands, prefer `lean-ctx -c "<command>"` or `ctx_shell`. For file exploration, prefer `ctx_read`/`ctx_search` over broad dumps.
- Use `task` or `signatures` reads for orientation, `anchored` reads before edits, and `diff` reads after edits. Keep context local and recover omitted details with targeted searches or `ctx_expand` when available.
- Use `ctx_patch` when the lean-ctx profile exposes it. Otherwise use the workspace editor/apply-patch tooling. If lean-ctx is unavailable, continue with the narrowest native VS Code or PowerShell tool rather than blocking.
- The lean-ctx tool profile is set to `power` (full tool registry). Prefer `ctx_*` tools over native search/read/terminal equivalents whenever both are available.
- All network traffic goes through the local proxy `http://127.0.0.1:3001` (VS Code `http.proxy`, integrated-terminal `HTTP_PROXY`/`HTTPS_PROXY`, repo-local git config, lean-ctx MCP env). Do not bypass it or disable TLS verification.
- Before a change, identify the code path that directly controls the behavior and one cheap executable check that can disconfirm the hypothesis. After the first edit, run that focused check before broadening the work.

## Run and verify

Use `uv` or the Python launcher available on this machine:

```powershell
uv run python tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out
# lub alternatywnie:
py tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out
```

Uruchamianie testów:
```powershell
uv run pytest
```

- Środowisko i pakiety są zarządzane przez `uv` (`pyproject.toml`, `.venv`).
- ZASADA DOTYCZĄCA BIBLIOTEK: Kod ma korzystać z najbardziej dopasowanych i odpowiednich bibliotek. Nie ma ograniczenia do samej biblioteki standardowej. Jeśli do realizacji zadania, testów lub usprawnienia kodu potrzebna jest biblioteka zewnętrzna, należy ją zainstalować za pomocą `uv add` (lub `uv add --dev`).
- Po zmianach w generatorze raportów zregeneruj `out/` i sprawdź `out/index.md` oraz przynajmniej jeden reprezentatywny raport.
- Zachowaj istniejące formaty generowanych raportów, chyba że zadanie jawnie wymaga ich zmiany.

## Domain constraints

- `.nwf` files contain an outer XML document and an escaped inner XML document. Parse both layers with the existing parser conventions.
- Nested Nintex actions are under `ChildActivities/NWActionConfig`; do not assume `Then`, `Else`, or another branch tag.
- Keep `FieldResolver` list-aware. The same SharePoint `InternalName` can have different meanings on different lists; pass the appropriate list context when resolving fields.
- Preserve the fallback for unknown action types and the `UNKNOWN_TYPES_SEEN` reporting path in `index.md`.
- Large `.nwf` files often contain very long or single-line XML. Inspect them with a small targeted Python script through `ctx_shell`/`lean-ctx -c` when normal file search output is truncated.

## Change conventions

- Pakiety instaluj zawsze przez `uv add` / `uv add --dev`.
- Dobieraj najlepsze i najbardziej optymalne biblioteki do problemu (np. `pytest`, biblioteki do parsowania XML/HTML, typowania, walidacji).
- Keep changes minimal and aligned with the existing modules in `tools/nwf_report/`.
- Do not duplicate the detailed project documentation in this file; update [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) when verified technical facts change.
- Do not create commits or branches unless explicitly requested.

## Future customization

The next useful project customization would be a dedicated `.github/agents/nwf-report.agent.md` if workflow-report tasks become frequent enough to justify isolated context and specialized tooling. Use `/chronicle improve` after future sessions to refine these instructions from recurring friction.