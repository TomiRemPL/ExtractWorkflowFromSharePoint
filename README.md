# ExtractWorkflowFromSharePoint

Narzędzie analizuje eksporty workflow Nintex ze środowiska SharePoint 2019 i generuje czytelne raporty Markdown opisujące logikę przepływów: warunki, pola odczytywane, pola zapisywane, listy SharePoint, zmienne oraz kolejność akcji.

## Obecna funkcjonalność

Program:

- parsuje pliki `.nwf` zawierające zewnętrzny XML oraz escapowany XML workflow wewnątrz;
- odczytuje tytuł, opis, identyfikator i konfigurację workflow;
- rozpoznaje listę źródłową oraz dodatkowe listy używane przez workflow;
- analizuje zagnieżdżone akcje znajdujące się pod `ChildActivities/NWActionConfig`;
- rozpoznaje warunki, gałęzie `Tak/Nie`, sekwencje i akcje równoległe;
- odczytuje parametry proste oraz złożone, w tym `Variable` i `ListLookup`;
- rozpoznaje odczyty i zapisy pól SharePoint;
- rozwiązuje nazwy techniczne `InternalName` na nazwy biznesowe;
- zachowuje kontekst listy przy rozwiązywaniu pól, aby uniknąć kolizji identycznych `InternalName` na różnych listach;
- tłumaczy znane akcje Nintex na opisy biznesowe w języku polskim;
- zachowuje fallback dla nieznanych typów akcji i zapisuje je w `out/index.md`;
- generuje diagram przepływu w składni Mermaid;
- generuje listę kroków workflow ze szczegółami technicznymi;
- generuje tabelę pól odczytywanych i zapisywanych;
- obsługuje błędy pojedynczych plików bez przerywania całego przetwarzania;
- zawiera interaktywny manual HTML dotyczący planowanej integracji z Oracle APEX;
- pokazuje pełny diagram Mermaid dla każdego z czterech workflow oraz rozwijane źródło Mermaid;
- prezentuje techniczne identyfikatory list, GUID-y, `InternalName` pól i relacje lookup;
- rozróżnia kolorami listy, pola, lookupy, workflow, zmienne i elementy APEX/REST.

## Uruchomienie generatora

W systemie Windows używany jest launcher `py`:

```powershell
py tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out
```

Po wykonaniu polecenia w katalogu `out/` powstają:

- osobny raport Markdown dla każdego pliku `.nwf`;
- `index.md` z listą workflow;
- lista typów akcji bez dedykowanego opisu, jeżeli takie wystąpią;
- `workflow-migration-manual.html` pozostaje osobnym manualem HTML i nie jest nadpisywany przez generator;
- raporty Markdown są źródłem weryfikacyjnym dla manuala HTML, ale manual nie jest obecnie generowany automatycznie z Markdown.

Program nie wymaga zewnętrznych zależności. Generator korzysta wyłącznie ze standardowej biblioteki Pythona, między innymi `xml.etree`, `json`, `argparse`, `dataclasses` i `pathlib`.

## Struktura projektu

```text
DaneZeSkryptu/                 Eksport SharePoint: JSON, CSV i pliki .nwf
tools/nwf_report/
  nwf_parser.py                Parser podwójnie kodowanego XML .nwf
  metadata_loader.py           Loader metadanych list i pól SharePoint
  action_catalog.py             Katalog opisów akcji Nintex
  report_builder.py             Generator raportu Markdown i Mermaid
  generate_report.py           Interfejs wiersza poleceń
out/                            Wygenerowane raporty i manual HTML
PROJECT_CONTEXT.md              Szczegółowa dokumentacja techniczna projektu
AGENTS.md                       Instrukcje dla agentów AI
```

## Obsługiwane akcje Nintex

W obecnych przykładach obsługiwane są między innymi:

- `NWWorkflowVariablesAdapter`;
- `WFIfElseAdapter` i `WFIfElseBranchAdapter`;
- `NWWriteToHistoryListAdapter`;
- `SPUpdateItemWithKeyAdapter`;
- `SPSetFieldWithKeyAdapter`;
- `SPSetVariableAdapter`;
- `NWRunIf2Adapter`;
- `NWCommitAdapter`;
- `WFParallelAdapter`;
- `WFSequenceAdapter`.

Nowe lub nieznane typy nie zatrzymują generowania. Otrzymują opis awaryjny i są raportowane w `index.md`.

## Obecnie przeanalizowane workflow

- **DT01 Mechanizm Kwalifikacji Usługi** — wylicza trzy pola kwalifikacyjne w liście `Kwalifikacja Usług`.
- **DT01 Wypełnienie pól Nr RKU oraz Nazwa** — uzupełnia `Nr RKU` i `Title`, jeżeli pola są puste.
- **RT0202 Pobranie danych z Kwalifikacji Usługi** — kopiuje dane z `Kwalifikacja Usług` do `Rejestr Usług ICT` przez lookup.
- **RT0701 Pobranie danych z Kwalifikacji Usługi do RT0701** — kopiuje dane z `Kwalifikacja Usług` do `Rejestr Ocen` przez lookup.

## Manual HTML

Plik [out/workflow-migration-manual.html](out/workflow-migration-manual.html) jest pojedynczym manualem działającym lokalnie w przeglądarce. Zawiera:

- opis obecnego stanu workflow SharePoint/Nintex;
- kontrakt REST dla wariantu synchronicznego i asynchronicznego;
- przykłady requestów i odpowiedzi;
- szkice `APEX_WEB_SERVICE` i ORDS/PLSQL;
- mapowanie akcji Nintex na APEX i SharePoint REST;
- karty czterech workflow;
- diagramy Mermaid i ich źródła;
- identyfikatory list, pól, lookupów i workflow;
- kolorową legendę obiektów `LISTA`, `POLE`, `LOOKUP`, `WORKFLOW`, `ZMIENNA` i `APEX/REST`;
- pełne diagramy Mermaid odpowiadające diagramom z raportów Markdown, z fallbackiem w postaci kodu źródłowego;
- wyszukiwanie, filtrowanie, rozwijane sekcje, kopiowanie przykładów i tryb wydruku.

Diagramy Mermaid są renderowane z użyciem CDN, dlatego ich wizualizacja wymaga dostępu do sieci. Pełny kod diagramów jest osadzony w pliku jako fallback i pozostaje dostępny offline. Sam manual otwiera się lokalnie bez serwera.

## Dane wejściowe

Najważniejsze konwencje katalogu `DaneZeSkryptu/`:

- `00_` — konfiguracja witryny i kolumny witryny;
- `10_` — definicje list i ich schematy;
- `20_` — dane elementów list;
- `30_` — użytkownicy i uprawnienia;
- `60_` — custom actions i event receivers;
- pliki `.nwf` — eksporty workflow;
- `Workflow-Inventory.csv` — inwentaryzacja workflow w kodowaniu UTF-16.

Generator korzysta przede wszystkim z plików `.nwf`, `00_kolumny_witryny.json` i `10_lista_*.json`. `Workflow-Inventory.csv` został odczytany i potwierdził cztery workflow odpowiadające eksportom `.nwf`, ale nie jest jeszcze automatycznie wczytywany przez generator. Pozostałe dane stanowią materiał referencyjny dla dalszej analizy i migracji.

## Ważne ograniczenia

- Eksport potwierdza obecne triggery SharePoint: utworzenie elementu, zmiana elementu i uruchomienie ręczne. Nie zawiera publicznego endpointu Nintex do wywołania zewnętrznego.
- Manual APEX opisuje docelową warstwę integracyjną, a nie gotowe wdrożenie produkcyjne.
- Połączenie Oracle APEX/ORDS z SharePoint, w szczególności uwierzytelnienie NTLM/Kerberos, wymaga osobnego POC w środowisku docelowym.
- `Workflow-Inventory.csv` jest odczytywany jako UTF-16.
- Duże pliki `.nwf` mogą zawierać bardzo długie lub pojedyncze linie XML; do ich analizy należy używać parsera XML albo małych skryptów, a nie polegać wyłącznie na podglądzie tekstu.
- Automatyczne testy jednostkowe nie zostały jeszcze utworzone. Dotychczasowa weryfikacja obejmuje cztery przykładowe workflow i ręczne porównanie raportów.

## Stan repozytorium

Ostatni zsynchronizowany commit na GitHub to `acd6105` (`Document project and expand workflow manual`). Zawiera README oraz rozbudowany manual HTML z diagramami Mermaid. Gałąź `master` śledzi `origin/master`.

## Dokumentacja

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — szczegółowe ustalenia techniczne, format `.nwf`, architektura i otwarte tematy.
- [AGENTS.md](AGENTS.md) — instrukcje pracy agentów AI w tym repozytorium.
- [manual SharePoint 2019](manual-sharepoint-2019-dla-poczatkujacych-v3%20(1).md) — procedura eksportu danych SharePoint.
- [raporty workflow](out/index.md) — indeks wygenerowanych raportów Markdown.
