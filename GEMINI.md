# Configuration & Agent Instructions

- **Zasada nadrzędna**: O ile jest to możliwe, ZAWSZE korzystaj z serwera MCP `lean-ctx` (narzędzia `ctx_*`) oraz poleceń CLI `lean-ctx` (np. `lean-ctx -c "<command>"`). Narzędzia `lean-ctx` mają bezwzględne pierwszeństwo przed standardowymi narzędziami odczytu, wyszukiwania i powłoki.
- **Zarządzanie środowiskiem i bibliotekami**: Projekt korzysta z `uv`. Zawsze instaluj potrzebne biblioteki poprzez `uv add` lub `uv add --dev`. Nie ma ograniczenia do biblioteki standardowej — kod i testy mają korzystać z najbardziej dopasowanych, nowoczesnych i odpowiednich bibliotek. Jeśli cokolwiek jest potrzebne do rozwiązania problemu lub testów, zainstaluj to przez `uv`.
- Szczegółowe wytyczne techniczne oraz zasady pracy w repozytorium znajdują się w plikach [AGENTS.md](AGENTS.md) oraz [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

