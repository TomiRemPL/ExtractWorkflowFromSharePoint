# ExtractWorkflowFromSharePoint

Narzędzie wspierające migrację workflow Nintex ze środowiska SharePoint 2019 do Oracle APEX. Program:

1. **pobiera** z witryny SharePoint metadane list, kolumny witryny i definicje workflow Nintex (`.nwf`),
2. **analizuje** workflow i generuje raporty Markdown z diagramami Mermaid,
3. **przygotowuje** materiały wdrożeniowe dla Oracle APEX: procedury PL/SQL `SHP_API`, pakiet dyspozytora ORDS oraz przewodnik APEX Workflow Designer,
4. **buduje** interaktywny portal HTML do przeglądania przepływów i planowania migracji.

Wszystkie funkcje są dostępne z wiersza poleceń oraz z graficznego interfejsu (GUI).

Autor: REMBIASZ GRC Tech Solutions Tomasz Rembiasz, NIP: 8871550162
Aplikacja powstała dla Credit-Agricole Bank Polska S.A.
Wersja: 3.0

## Wymagania i instalacja

- Windows z dostępem do witryny SharePoint 2019 (dla ekstrakcji; uwierzytelnienie Windows SSO/SSPI lub NTLM),
- Python 3.14 oraz menedżer [`uv`](https://docs.astral.sh/uv/).

Instalacja zależności (tworzy `.venv` na podstawie `pyproject.toml` i `uv.lock`):

```powershell
uv sync
```

Wszystkie polecenia poniżej uruchamiaj z katalogu głównego repozytorium.

## Tryb graficzny (GUI)

### Uruchomienie

```powershell
uv run python tools\gui.py
```

Alternatywnie dwuklik na [run_gui.bat](run_gui.bat) — uruchamia GUI bez okna konsoli, korzystając z `.venv\Scripts\pythonw.exe` (jeśli `.venv` nie istnieje, używa systemowego `pythonw`). Przed pierwszym użyciem wykonaj `uv sync`.

### Budowa okna

- **Nagłówek** z tytułem aplikacji i przyciskiem **O aplikacji** (autor, przeznaczenie, wersja).
- **Zakładka „1. Ekstrakcja z SharePoint”** — pobieranie danych z witryny.
- **Zakładka „2. Generowanie raportów i portalu”** — generowanie raportów, pakietu PL/SQL i portalu HTML.
- **Dziennik zdarzeń** — logi operacji w czasie rzeczywistym.
- **Pasek stanu** — bieżący status i wskaźnik postępu.

Operacje działają w tle, więc okno pozostaje responsywne; przycisk uruchomionej operacji jest zablokowany do jej zakończenia. Błędy są pokazywane w oknie komunikatu i w dzienniku.

### Krok 1 — ekstrakcja z SharePoint

1. W polu **Adres URL witryny SharePoint** wpisz adres witryny (np. `https://sp.domena.local/sites/dora`).
2. **Katalog docelowy**: pozostaw zaznaczone **Automatycznie numeruj (DaneZeSkryptu_nnn)**, aby utworzyć kolejny katalog `DaneZeSkryptu_001`, `DaneZeSkryptu_002`, … albo odznacz opcję i wpisz własną nazwę katalogu (względem katalogu repozytorium).
3. Opcje:
   - **Pobierz dane list (20_dane_*.json)** — dodatkowo eksportuje wiersze list (dane biznesowe; domyślnie wyłączone),
   - **Ignoruj certyfikat SSL (--insecure)** — tylko dla środowisk z certyfikatem niezaufanym.
4. Kliknij **Rozpocznij pobieranie z SharePoint**. GUI uwierzytelnia się bieżącym kontem Windows (SSO/SSPI).
5. Po sukcesie zakładka 2 zostanie automatycznie uzupełniona: katalog wejściowy `DaneZeSkryptu_nnn` i wyjściowy `out_nnn`.

Logowanie innym kontem (NTLM) jest dostępne tylko w [wierszu poleceń](#ekstrakcja-z-sharepoint).

### Krok 2 — generowanie raportów i portalu

1. **Katalog z danymi (.nwf i JSON)** — katalog z eksportem (np. `DaneZeSkryptu_002`); przycisk **Przeglądaj...** pozwala go wskazać. Po wyborze katalogu z sufiksem `_nnn` katalog wyjściowy ustawia się automatycznie na `out_nnn`.
2. **Katalog wyjściowy raportów** — katalog na wyniki (np. `out_002`).
3. Kliknij **Generuj raporty i portal HTML**.
4. **Otwórz portal w przeglądarce** — otwiera `workflow-migration-manual.html` z katalogu wyjściowego.
5. **Otwórz katalog w Eksploratorze** — otwiera katalog wyjściowy z raportami.

Przy starcie GUI automatycznie podpowiada najnowszy istniejący katalog `DaneZeSkryptu*` i odpowiadający mu katalog `out*`.

## Wiersz poleceń (CLI)

### Ekstrakcja z SharePoint

```powershell
# Windows SSO, automatyczny katalog DaneZeSkryptu_nnn
uv run python tools\sp_extractor\cli.py https://sp.domena.local/sites/dora

# NTLM, własny katalog, z danymi list
uv run python tools\sp_extractor\cli.py --url https://sp.domena.local/sites/dora -u login -p haslo -d DOMENA -o DaneZeSkryptu_test --include-data
```

| Opcja | Znaczenie |
|---|---|
| `URL` / `--url` | adres witryny SharePoint (wymagany) |
| `-o`, `--output` | katalog docelowy; domyślnie kolejny `DaneZeSkryptu_nnn` |
| `--base-dir` | katalog, w którym szukane są istniejące `DaneZeSkryptu_nnn` (domyślnie `.`) |
| `-u`, `-p`, `-d` | login, hasło i domena NTLM; bez nich używane jest Windows SSO/SSPI |
| `--include-data` | eksport wierszy list (`20_dane_*.json`) |
| `--include-permissions` | zarezerwowane — obecnie tylko odnotowywane w manifeście, eksport uprawnień `30_*` nie jest jeszcze zaimplementowany |
| `--insecure` | wyłączenie weryfikacji certyfikatu SSL |
| `-v`, `--verbose` | szczegółowe logi |

Hasła nie należy przekazywać w skryptach ani zapisywać w repozytorium.

### Generowanie raportów

```powershell
uv run python tools\nwf_report\generate_report.py --input DaneZeSkryptu_002 --output out_002
```

## Co powstaje

### Katalog eksportu `DaneZeSkryptu*`

| Plik | Zawartość |
|---|---|
| `00_wlasciwosci.json`, `00_kolumny_witryny.json` | właściwości i kolumny witryny |
| `10_00_wszystkie_listy.json`, `10_lista_*.json` | lista list oraz definicje i schematy pól |
| `20_dane_*.json` | wiersze list (tylko z opcją danych) |
| `*.nwf` | definicje workflow Nintex |
| `Workflow-Inventory.csv` | inwentaryzacja workflow |
| `extraction_manifest.json` | podsumowanie ekstrakcji |

Konwencje nazw są zgodne z [manualem eksportu SharePoint](manual-sharepoint-2019-dla-poczatkujacych-v3%20(1).md). Generator raportów korzysta z plików `.nwf`, `00_kolumny_witryny.json` i `10_lista_*.json`.

### Katalog wyników `out*`

- **Raport Markdown dla każdego workflow**: podstawowe informacje i listy, diagram Mermaid, kroki workflow ze szczegółami technicznymi, zmienne, pola odczytywane/zapisywane ze słownikiem `InternalName`, przewodnik Oracle APEX (*Shared Components > Workflows*: parametry, zmienne, aktywności), kompletna procedura PL/SQL oparta na `SHP_API` oraz opis integracji wyzwalacza SharePoint z ORDS.
- `index.md` — lista workflow oraz typy akcji bez dedykowanego opisu.
- `walkthrough.md` — statystyki przetwarzania, liczba akcji, źródła i statusy.
- `pkg_shp_dispatcher.sql` — pakiet PL/SQL dyspozytora ORDS kierujący wywołania do procedur workflow.
- `workflow-migration-manual.html` — interaktywny portal migracji (poniżej).

## Portal HTML

Pojedynczy plik otwierany lokalnie w przeglądarce, bez serwera. Zawiera:

1. pulpit inwentaryzacji (liczba workflow, akcji, list i pól),
2. eksplorator przepływu z diagramem Mermaid (zoom, przesuwanie, reset) i inspektorem kafelka: warunki, odczyty/zapisy pól, wskazówki i kod PL/SQL do skopiowania,
3. słownik pól i identyfikatorów technicznych (GUID list, `InternalName`, lookupy),
4. kontrakt integracyjny SharePoint (`workflow.xaml`) ↔ ORDS REST API,
5. architekturę wdrożenia w Oracle APEX i pakiet `SHP_API`,
6. przewodnik APEX Workflow Designer,
7. kryteria odbioru i checklistę wdrożenia.

W belce pod nagłówkiem znajduje się tylko wyszukiwarka (bez przycisków nawigacji sekcji). Filtruje zakładki workflow i wiersze słownika pól po nazwach, opisach akcji i `InternalName`; po wyczyszczeniu pola przywraca wszystkie wyniki. Filtr pozostaje aktywny przy zmianie workflow i motywu. W nagłówku dostępne są przełącznik trybu jasnego/ciemnego oraz okno **O aplikacji**. Diagramy Mermaid są renderowane biblioteką z CDN (wymaga dostępu do sieci); wyszukiwanie i pozostała zawartość działają offline.

## Analiza workflow Nintex

- Parsowanie plików `.nwf` — zewnętrzny XML z escapowanym wewnętrznym XML workflow.
- Analiza zagnieżdżonych akcji pod `ChildActivities/NWActionConfig`: warunki i gałęzie `Tak/Nie`, sekwencje, akcje równoległe.
- Parametry proste i złożone (m.in. `Variable`, `ListLookup`), odczyty i zapisy pól SharePoint.
- Rozwiązywanie `InternalName` na nazwy biznesowe z zachowaniem kontekstu listy (te same nazwy techniczne na różnych listach nie kolidują).
- 22 wpisy `TYPE_HANDLERS` w katalogu akcji, w tym handlery strukturalne. Typy bez dedykowanego handlera otrzymują opis awaryjny, nie przerywają generowania i są raportowane w `index.md`.
- Błąd pojedynczego pliku `.nwf` nie zatrzymuje przetwarzania pozostałych.

## Ochrona danych

Katalogi `DaneZeSkryptu*` i `out*` zawierają dane i konfigurację biznesową. Są ignorowane przez Git (`.gitignore`) i **nie mogą** być publikowane w repozytorium — nie dodawaj ich przez `git add -f`.

## Struktura projektu

```text
tools/
  gui.py                       Interfejs graficzny (Tkinter)
  sp_extractor/                Ekstraktor SharePoint 2019
    cli.py                     Interfejs wiersza poleceń
    client.py                  Klient REST (SSO/SSPI, NTLM)
    extractor.py               Eksport list, kolumn, workflow i manifestu
    naming.py                  Nazwy plików i katalogi DaneZeSkryptu_nnn
    tests/
  nwf_report/                  Generator raportów i portalu
    generate_report.py         Interfejs wiersza poleceń
    nwf_parser.py              Parser podwójnie kodowanego XML .nwf
    metadata_loader.py         Metadane list i pól SharePoint
    action_catalog.py          Katalog opisów akcji Nintex
    report_builder.py          Raport Markdown, Mermaid i PL/SQL
    apex_workflow_guide.py     Przewodnik APEX Workflow Designer
    html_builder.py            Portal HTML
    app_info.py                Autor i wersja aplikacji
    tests/
run_gui.bat                    Uruchamianie GUI bez konsoli
PROJECT_CONTEXT.md             Szczegółowa dokumentacja techniczna
AGENTS.md                      Instrukcje dla agentów AI
```

## Testy i rozwój

```powershell
uv run pytest
```

Zależności dodawaj przez `uv add <pakiet>` (produkcyjne) lub `uv add --dev <pakiet>` (deweloperskie).

## Ograniczenia

- Eksport Nintex zawiera triggery SharePoint (utworzenie, zmiana elementu, uruchomienie ręczne), ale nie zawiera publicznego endpointu do wywołania z zewnątrz.
- Materiały APEX/ORDS opisują docelową warstwę integracyjną i wymagają weryfikacji w środowisku docelowym — w szczególności uwierzytelnienie Oracle APEX/ORDS do SharePoint (NTLM/Kerberos) wymaga osobnego POC.
- GUI obsługuje wyłącznie uwierzytelnienie bieżącym kontem Windows; NTLM z innym kontem jest dostępny w CLI.

## Dokumentacja

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — format `.nwf`, architektura, decyzje i otwarte tematy.
- [AGENTS.md](AGENTS.md) — zasady pracy agentów AI w repozytorium.
- [Manual SharePoint 2019](manual-sharepoint-2019-dla-poczatkujacych-v3%20(1).md) — ręczna procedura eksportu danych SharePoint.
