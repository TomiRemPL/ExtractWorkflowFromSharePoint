# Kontekst projektu dla LLM — generator raportów z Nintex Workflow (.nwf)

Ten plik jest przeznaczony dla modelu/agenta AI kontynuującego pracę nad tym projektem.
Zawiera wszystkie ustalone fakty, decyzje i szczegóły techniczne, żeby nie trzeba było
ich odkrywać/weryfikować od nowa. Aktualny na: 2026-09-19.

## 1. Cel projektu

Katalog `DaneZeSkryptu/` zawiera zrzut konfiguracji witryny SharePoint 2019
(wyeksportowany wg procedury opisanej w [manual-sharepoint-2019-dla-poczatkujacych-v3 (1).md](manual-sharepoint-2019-dla-poczatkujacych-v3%20(1).md))
oraz pliki `.nwf` — zrzuty konfiguracji przepływów pracy Nintex Workflow.

Zbudowano narzędzie w Pythonie (`tools/nwf_report/`), które na podstawie pliku `.nwf`
i metadanych JSON generuje **czytelny raport Markdown** opisujący krok po kroku,
co dany workflow odczytuje i zmienia (pola, listy, warunki), w języku biznesowym
+ sekcja techniczna, wraz z diagramem Mermaid.

**Status: zaimplementowane, przetestowane na 4 przykładowych plikach `.nwf`, działa poprawnie.**

Utworzono również pojedynczy manual HTML `out/workflow-migration-manual.html` opisujący
docelową integrację z Oracle APEX. Manual zawiera karty wszystkich 4 workflow, diagramy
Mermaid, źródło każdego diagramu, identyfikatory list i pól, legendę typów obiektów oraz
kontrakt REST sync/async z przykładami APEX/ORDS.

Portal jest generowany przez `tools/nwf_report/html_builder.py` i zawiera interaktywny
przełącznik workflow, inspektor kroków oraz wyszukiwarkę (od 2026-11-05 bez przycisków nawigacji sekcji). Diagram ma
ograniczony viewport z przesuwaniem pointer/touch, zoomem kółkiem/przyciskami i resetem;
kliknięcie węzła mapuje identyfikator Mermaid do `steps[node_id]` i aktualizuje inspektor.
Zmiany z 2026-09-19 zostały wygenerowane do `out/workflow-migration-manual.html`.

## 2. Jak uruchomić

Zarządzanie środowiskiem i zależnościami odbywa się przez `uv` (`pyproject.toml`, `.venv`).

```powershell
cd C:\Users\torembiasz\Desktop\prace\202609_DORA
uv run python tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out
# lub z użyciem launchera py:
py tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out
```

Uruchomienie testów:
```powershell
uv run pytest
```

- Python / środowisko: Python 3.14.7, pakiety zarządzane przez `uv`.
- Wynik: pliki `out/<Nazwa Workflow>.md` (jeden na workflow), `out/index.md` (spis + lista
  typów akcji bez dedykowanego opisu) oraz `out/walkthrough.md` (tabela podsumowująca statystyki, liczbę akcji i statusy).
- Zasada bibliotek: Kod i testy mają korzystać z najbardziej dopasowanych, wydajnych i odpowiednich bibliotek.
  Brak ograniczenia do samej biblioteki standardowej. Wszelkie potrzebne pakiety instalujemy przez `uv add` / `uv add --dev`.

## 3. Struktura katalogu `DaneZeSkryptu/`

Konwencja nazw (opisana w manualu, część A3):

| Prefiks | Zawartość |
|---|---|
| `00_` | Konfiguracja witryny: kolumny witryny, funkcje, nawigacja, property bag, typy zawartości |
| `10_` | Definicje list (schemat + kolumny) |
| `20_` | Dane list (wiersze elementów) |
| `30_` | Uprawnienia, użytkownicy, poziomy uprawnień |
| `60_` | Custom actions, event receivers |
| (bez prefiksu) | Pliki `.nwf` (workflow) i `Workflow-Inventory.csv` |

Kluczowe pliki JSON i ich dokładny format (zweryfikowane na realnych danych):

- **`00_kolumny_witryny.json`** — tablica obiektów kolumn (site columns), klucze m.in.:
  `Title` (nazwa wyświetlana), `InternalName`/`StaticName` (nazwa techniczna), `Id` (GUID),
  `TypeAsString`, `Formula` (dla kolumn obliczeniowych), `Group`.
- **`10_00_wszystkie_listy.json`** — tablica list, top-level klucze: `Id` (GUID listy, bez klamer),
  `Title`, `BaseTemplate`, `EntityTypeName`, itd.
- **`10_lista_<Nazwa>.json`** — obiekt o strukturze:
  ```json
  {
    "lista": { "Id": "...", "Title": "...", ... },
    "schemaXml": "<List ...>",
    "kolumny": [ { "Title": "...", "InternalName": "...", "TypeAsString": "...", "Formula": "...", "Id": "..." }, ... ]
  }
  ```
- **`20_dane_<Nazwa>.json`** — tablica elementów listy, klucze = `InternalName` kolumn
  (np. `"Us_x0142_uga_x0020_kwalifikowana": "Tak"`).
- **`Workflow-Inventory.csv`** — plik **UTF-16** (BOM), NIE UTF-8. Trzeba czytać z
  `encoding="utf-16"`. Został odczytany i potwierdził 4 rekordy odpowiadające 4 plikom `.nwf`;
  generator raportów nadal nie wczytuje go automatycznie.

## 4. Format pliku `.nwf` (najważniejsza część researchu)

Plik `.nwf` to XML z podwójnym poziomem kodowania:

```
<ExportedWorkflowWithListMetdata>          <!-- root, literówka "Metdata" jest w oryginale -->
  <ExportedWorkflowSeralized>              <!-- string z ESCAPED (HTML-entity) XML-em w środku! -->
    &lt;ExportedWorkflow&gt;
      &lt;Title&gt;...&lt;/Title&gt;
      &lt;Description&gt;...&lt;/Description&gt;
      &lt;Configurations&gt;
        &lt;ActionConfigs&gt;
          &lt;NWActionConfig&gt; ... &lt;/NWActionConfig&gt;   <!-- powtarzalne, to sa akcje workflow -->
        &lt;/ActionConfigs&gt;
      &lt;/Configurations&gt;
    &lt;/ExportedWorkflow&gt;
  </ExportedWorkflowSeralized>
  <ListReferences>                          <!-- METADANE POL - kluczowe dla resolvera nazw -->
    <ListReference>
      <ListName>...</ListName>
      <ListId>{GUID}</ListId>
      <IsSourceList>true|false</IsSourceList>   <!-- true = lista, na ktorej dziala workflow -->
      <Fields>
        <FieldReference>
          <InternalName>...</InternalName>
          <DisplayName>...</DisplayName>
          <FieldType>...</FieldType>
        </FieldReference>
        ...
      </Fields>
    </ListReference>
    <!-- moze byc wiecej niz jedna ListReference: lista zrodlowa + listy z lookupow/cross-list actions -->
  </ListReferences>
  <Version>...</Version>
  <WorkflowType>...</WorkflowType>
  <WorkflowId>...</WorkflowId>
</ExportedWorkflowWithListMetdata>
```

Parsowanie w kodzie: `ET.fromstring(path.read_text(encoding="utf-8-sig"))` na zewnętrznym XML,
potem `ET.fromstring(serialized_el.text)` na wewnętrznym (biblioteka `xml.etree.ElementTree`
sama odkodowuje encje przy odczycie `.text`, więc nie trzeba ręcznego `html.unescape`).

### 4.1. Struktura pojedynczej akcji `<NWActionConfig>`

Każda akcja ma (niepełna lista, tylko istotne):
- `<Type>` — pełna nazwa klasy .NET, np. `Nintex.Workflow.Activities.Adapters.SPUpdateItemWithKeyAdapter`.
  W kodzie używamy tylko ostatniego segmentu po kropce (`_short_type()`).
- `<Enabled>` — `true`/`false`.
- `<ConditionUse>` — `None` / `Child` (child = akcja ma warunek/gałęzie).
- `<TLabel>`, `<BLabel>`, `<LLabel>`, `<RLabel>` — **etykiety nadane w projektancie Nintex**,
  bardzo cenne źródło opisu biznesowego "po ludzku" (deweloper często wpisuje tu np. nazwę
  zmiennej albo tytuł kroku). Przykład: dla `SPSetVariableAdapter` `BLabel` = wartość ustawiana
  (np. "Tak"/"Nie"), `TLabel` = opis biznesowy kroku (np. "DT-01-01-34 Usługa ICT?").
- `<Parameters><Parameter Name="X"><PrimitiveValue Value="..." /></Parameter>...` — proste
  parametry akcji. Ale **niektóre parametry zamiast `PrimitiveValue` mają złożone struktury**:
  - `<Variable Name="..." .../>` — referencja do zmiennej workflow (np. `VariableName`
    w `SPSetVariableAdapter`).
  - `<ListLookup LookupType="ThisItemLookup|CrossItemLookup">` — wyrażenie odczytujące
    wartość pola, patrz sekcja 4.3.
- `<FieldReferences><FieldReference Name="..." Value="internal_name" Type="..." />...` —
  pola docelowe akcji (np. które pola są aktualizowane przez `SPUpdateItemWithKeyAdapter`).
  `Name` = etykieta użyta w tym konkretnym działaniu (może być pusta), `Value` = InternalName.
- `<Condition xsi:type="ConditionPair" Operator="And|Or">` (dla `WFIfElseAdapter`) —
  patrz sekcja 4.2.
- `<ChildActivities><NWActionConfig>...</NWActionConfig>...</ChildActivities>` — **JEDYNE
  miejsce, gdzie znajdują się zagnieżdżone akcje** (warunki, pętle, sekwencje równoległe).
  WAŻNE: to NIE są tagi "Then"/"Else" ani "Actions" — zawsze `ChildActivities`.

### 4.2. Struktura warunku (`WFIfElseAdapter`)

```xml
<NWActionConfig>
  <Type>...WFIfElseAdapter</Type>
  <LLabel>Nie</LLabel>   <!-- etykieta lewej galezi (zwykle "Nie") -->
  <RLabel>Tak</RLabel>   <!-- etykieta prawej galezi (zwykle "Tak") -->
  <Condition xsi:type="ConditionPair" Operator="Or">
    <Left xsi:type="NWConditionConfig" Name="Jeśli wartość pola bieżącego elementu jest równa">
      <Params>
        <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
        <Param Name="left"><ListLookup LookupType="ThisItemLookup"><Field Name="DT_x002e_01" Type="Choice" /></ListLookup></Param>
        <Param Name="right"><PrimitiveValue Value="Tak" ValueType="Choice" /></Param>
      </Params>
    </Left>
    <Right xsi:type="NWConditionConfig" ...>...</Right>  <!-- moze byc zagniezdzony ConditionPair -->
  </Condition>
  <ChildActivities>
    <NWActionConfig><Type>...WFIfElseBranchAdapter</Type><ChildActivities>...</ChildActivities></NWActionConfig>  <!-- branch 0 = LEWA (Nie) -->
    <NWActionConfig><Type>...WFIfElseBranchAdapter</Type><ChildActivities>...</ChildActivities></NWActionConfig>  <!-- branch 1 = PRAWA (Tak) -->
  </ChildActivities>
</NWActionConfig>
```

- `ChildActivities` warunku zawsze ma dokładnie 2 dzieci typu `WFIfElseBranchAdapter`.
  Kolejność: **pierwsze dziecko = gałąź LLabel (zwykle "Nie"), drugie = gałąź RLabel
  (zwykle "Tak")** — zweryfikowane empirycznie, ale nie ma twardej gwarancji z dokumentacji
  Nintex, więc traktować jako założenie robocze potwierdzone na próbce.
- Każdy `WFIfElseBranchAdapter` ma własne `ChildActivities` z faktycznymi akcjami danej gałęzi
  (może być pusty = brak akcji w tej gałęzi).
- Operator warunku: `Equal`, `NotEqual`, `GreaterThan`, `LessThan`, `GreaterThanOrEqual`,
  `LessThanOrEqual`, `Contains`, `NotContains`, `IsEmpty`, `IsNotEmpty` (słownik `_OPERATOR_PL`
  w `action_catalog.py` tłumaczy je na polski, niepełna lista — do rozszerzenia w razie
  napotkania nowych operatorów).

### 4.3. Struktura `ListLookup` (odczyt wartości pola, użyte w warunkach i `SPSetVariableAdapter`)

Dwa warianty:

**ThisItemLookup** (odczyt z bieżącego elementu, na liście źródłowej workflow):
```xml
<ListLookup LookupType="ThisItemLookup">
  <Field Name="InternalName" Type="Choice" />
</ListLookup>
```

**CrossItemLookup** (odczyt z INNEGO elementu, na INNEJ liście, dopasowanego przez pole
lookup na bieżącym elemencie):
```xml
<ListLookup LookupType="CrossItemLookup">
  <Lookup LookupType="ThisItemLookup">
    <ListId>{GUID biezacej listy}</ListId>
    <Field Name="NazwaKolumnyLookupNaBiezacejLiscie" Type="Lookup" />  <!-- kolumna typu Lookup wskazujaca ID elementu w innej liscie -->
  </Lookup>
  <Coercion>LookupIdOnlyAsInteger</Coercion>
  <ListId>{GUID listy docelowej}</ListId>          <!-- lista, z ktorej faktycznie czytamy wartosc -->
  <Field Name="PoleDoOdczytu" Type="Text" />         <!-- pole na liscie docelowej -->
  <CompareField Name="ID" Type="Counter" />          <!-- pole uzyte do dopasowania (zwykle ID) -->
</ListLookup>
```

**WAŻNA PUŁAPKA odkryta i naprawiona:** ta sama `InternalName` może istnieć na WIELU listach
z INNYM znaczeniem (SharePoint "site columns" są reużywane między listami). Np.
`Us_x0142_uga_x0020_kwalifikowana` na liście "Kwalifikacja Usług" to pole tekstowe
"Usługa ICT wg DORA?", ale na liście "Rejestr Usług ICT" ta sama nazwa techniczna może
oznaczać kolumnę typu Lookup wskazującą na inny element. **Resolver nazw pól MUSI być
świadomy kontekstu listy** (patrz sekcja 5) — inaczej dostaniemy błędne tłumaczenie nazwy.

## 5. Architektura kodu (`tools/nwf_report/`)

```
tools/nwf_report/
├── __init__.py            (pusty)
├── nwf_parser.py           parse_nwf() -> WorkflowModel
├── metadata_loader.py      load_site_metadata() -> SiteMetadata, FieldResolver
├── action_catalog.py       describe_action() -> ActionDescription
├── report_builder.py       build_report() -> str (Markdown)
└── generate_report.py      CLI (main())
```

### `nwf_parser.py`

Dataclassy:
- `FieldRef(name, internal_name, field_type="")`
- `ActionNode(type, enabled, condition_use, params: dict[str,str], param_elements: dict[str,ET.Element],
  field_refs: list[FieldRef], children: list[ActionNode], branch_label, t_label, b_label, l_label,
  r_label, condition_el: ET.Element|None)`
  - `params` — proste wartości tekstowe (dla `PrimitiveValue`; dla innych typów węzłów pusty string).
  - `param_elements` — **surowy element XML** pierwszego dziecka każdego `<Parameter>` (może to być
    `<PrimitiveValue>`, `<Variable>`, `<ListLookup>` itd.) — używane przez `action_catalog.py` do
    generycznego renderowania złożonych wartości.
- `ListReference(list_name, list_id, is_source_list, fields: list[FieldRef])`
- `WorkflowModel(title, description, list_references, actions, source_path)` z property
  `source_list` (pierwsza `ListReference` z `is_source_list=True`, albo `None`).

Funkcje:
- `parse_nwf(path) -> WorkflowModel` — główny punkt wejścia.
- `iter_actions(actions) -> Generator[(ActionNode, depth)]` — płaskie przejście po drzewie
  z zachowaniem głębokości (uwaga: NIE jest używane bezpośrednio w `report_builder.py` do
  numeracji Mermaid — tam jest osobny licznik, patrz niżej, potencjalna niespójność ID między
  sekcją "Kroki workflow" a diagramem — **nieblokujące, ale do ew. ujednolicenia**).
- Prywatne: `_parse_action`, `_branch_labels` (etykiety Tak/Nie dla `WFIfElseAdapter`),
  `_parse_parameters`, `_parse_param_elements`, `_parse_field_refs`, `_parse_list_references`.

### `metadata_loader.py`

- `ColumnInfo` przechowuje m.in. `InternalName`, `EntityPropertyName`, identyfikator pola,
  `LookupField`, `LookupList` i `SchemaXml` potrzebne do mapowania odczytów REST.
- `ListInfo(title, list_id, columns: dict[internal_name_lower -> ColumnInfo])`
- `SiteMetadata(lists_by_id, lists_by_title, site_columns)` — wypełniane przez
  `load_site_metadata(dane_dir)` z plików `00_kolumny_witryny.json` i `10_lista_*.json`.
  To jest **fallback**, używany tylko gdy dany `.nwf` nie ma własnego wpisu w `ListReferences`
  dla danej listy.
- `FieldResolver(list_references, site_metadata=None, source_list_id="")`:
  - `self._by_list_and_name: dict[list_id_lub_nazwa_lower -> dict[internal_name_lower -> title]]`
    — **główne, list-aware źródło prawdy** (zbudowane z `ListReferences` samego pliku `.nwf`).
  - `self._by_internal_name` — fallback bez kontekstu listy (gdy nie podano `list_hint`
    albo lista nie jest znaleziona).
  - `resolve(internal_name, list_hint="") -> str` — zwraca `"Tytuł (nazwa_techniczna)"` albo
    samą `internal_name`, jeśli nierozpoznane. `list_hint` może być GUID-em (z klamrami lub bez,
    normalizowane przez `_norm_guid`) albo nazwą listy.
  - `source_list_id` — atrybut przechowujący GUID listy źródłowej workflow (ustawiany
    z `wf.source_list.list_id` w `generate_report.py`), używany przez `action_catalog.py`
    do rozstrzygania, do której listy odnoszą się pola w `ThisItemLookup`.

### `action_catalog.py`

- `ActionDescription(summary, reads: list[FieldRef], writes: list[FieldRef], technical_lines: list[str], is_structural: bool)`
- `TYPE_HANDLERS: dict[str_krotki_typ -> Callable]` — zaimplementowane typy (wszystkie
  napotkane w 4 przykładowych plikach):
  - `NWWorkflowVariablesAdapter` → opis startu workflow (wyzwalacze: ręcznie/utworzenie/zmiana).
  - `WFIfElseAdapter` → "Warunek: JEŻELI ...", `reads` = pola użyte w warunku.
  - `WFIfElseBranchAdapter` → strukturalny (bez własnego opisu, `is_structural=True`).
  - `NWWriteToHistoryListAdapter` → wpis do historii przepływu (log).
  - `SPUpdateItemWithKeyAdapter` → aktualizacja elementu (pola z `FieldReferences`), `writes`.
  - `SPSetFieldWithKeyAdapter` → ustawienie jednego pola (`LookupField`/`LookupFieldValue`), `writes`.
  - `SPSetVariableAdapter` → zapis do zmiennej workflow (`VariableName`/`Value` z `param_elements`,
    NIE z `params` — `Value` bywa `ListLookup`), `reads` = pola użyte w wyrażeniu wartości.
  - `NWRunIf2Adapter` → "Wykonaj TYLKO JEŻELI ..." (warunek bez jawnego "else"), `reads`. Dzieci (zawsze
    opakowane w `WFSequenceAdapter`) są rozpisywane w Mermaid (krawędzie `Tak`/`Nie`), otrzymują `node_id`,
    a `plsql_code` zawiera pełny blok `IF ... THEN <kod dzieci> END IF;` (sekcja 22).
  - `NWCommitAdapter` → "Zapisz (zatwierdź) zebrane zmiany" (commit zmian zebranych przez
    wcześniejsze `SetField`/`UpdateItem` w tej samej "transakcji").
  - `NWBuildStringAdapter` → dynamiczne łączenie ciągów tekstowych/zmiennych (`Input` -> `Output`).
  - `NWBusinessProcessAdapter` → wydzielone etapy procesu biznesowego (`StageName`), kontener podrzędnych akcji.
  - `NWCalculateDateAdapter` → przesunięcia dat o dni/miesiące/godziny (`Date`, `Days`, `Months`, `Hours` -> `Output`).
  - `NWCollectionAdapter` → operacje na kolekcjach (Get, Count, Join, etc.).
  - `NWCreateSiteSpecificItemAdapter` → tworzenie nowych rekordów na listach SharePoint (`SHP_API.add_list_item`;
    pola z `FieldReferences`, ID do zmiennej `Output` typu `Variable`).
  - `NWDelayForAdapter` → opóźnienia i wstrzymania wykonania (`DBMS_SESSION.SLEEP`).
  - `NWForEachLoopAdapter` → iteracje po elementach kolekcji (`Target`, `Value`), kontener pętli.
  - `NWQueryListAdapter` → kwerendy CAML po listach SharePoint z mapowaniem do zmiennych (`ValueStorage`).
  - `NWSendMessageAdapter` → wysyłka wiadomości e-mail (`apex_mail.send`).
  - `NWStartWorkflow2Adapter` → wywołanie podprocesów / innych workflow (`process_wf_*`).
  - `NWUpdateMultipleItemAdapter` → masowa aktualizacja rekordów wg filtru CAML (`shp_api.update_list_item`).
  - `WFParallelAdapter`, `WFSequenceAdapter` → strukturalne kontenery (rozwijane bez własnego węzła).
- `_render_value_expr(el, resolver) -> str` — generyczny renderer wartości parametru:
  obsługuje `PrimitiveValue`, `Variable`, `ListLookup` (oba warianty z sekcji 4.3, poprawnie
  przekazuje `list_hint` — dla `ThisItemLookup` używa `resolver.source_list_id`, dla
  `CrossItemLookup` używa `<ListId>` z samego `ListLookup` dla pola docelowego i
  `resolver.source_list_id` dla pola dopasowującego). Fallback dla nieznanych tagów: `el.text`
  albo `f"[{tag}]"`.
- `_render_condition(cond_el, resolver) -> str` — rekurencyjnie renderuje `ConditionPair`
  (And/Or → "ORAZ"/"LUB") i `NWConditionConfig` (operator + lewa/prawa strona przez
  `_render_value_expr`).
- `_extract_condition_fields(cond_el) -> list[FieldRef]` — zbiera wszystkie `<Field Name=...>`
  wewnątrz dowolnego poddrzewa XML (używane też do zbierania `reads` z `ListLookup` w
  `SPSetVariableAdapter`, nazwa funkcji jest myląca — działa na dowolnym elemencie, nie tylko
  warunkach).
- `describe_action(node, resolver) -> ActionDescription` — punkt wejścia, fallback dla
  nieznanych typów (`_describe_fallback`) rejestruje typ w `UNKNOWN_TYPES_SEEN` (moduł-level
  `set`, czytany przez `generate_report.py` do sekcji "do uzupełnienia" w `index.md`).

### `report_builder.py`

- `Step` dataclass, `_collect_steps()` — spłaszcza drzewo akcji z zachowaniem `depth`
  (do generowania listy zagnieżdżonej w Markdown, pomija `is_structural` przy renderowaniu).
- `_build_mermaid(actions, resolver) -> str` — generuje `flowchart TD`. Algorytm rekurencyjny
  `walk(nodes, entry_ids, entry_label="") -> list[str]` (zwraca "otwarte końce" — id węzłów
  bez wychodzącej strzałki, do których podłączy się kolejny krok). Obsługuje:
  - `WFSequenceAdapter`/`WFParallelAdapter`/`WFIfElseBranchAdapter` → transparentne (rozwijane
    in-line, przekazują `entry_label` dalej tylko dla PIERWSZEGO kroku w gałęzi).
  - `WFIfElseAdapter` → węzeł-romb, dwie gałęzie z etykietami `branch_label` (Tak/Nie), oba
    końce gałęzi zbierane do `branch_ends` i zwracane jako nowe "otwarte końce" (czyli obie
    gałęzie automatycznie się łączą z kolejnym krokiem po warunku — **UWAGA: to jest
    uproszczenie, w realnym Nintex gałęzie łączą się w jednym punkcie "join", tutaj po prostu
    oba końce niezależnie łączą się z następnym węzłem, co wizualnie daje ten sam efekt**).
  - Etykiety węzłów obcinane do 60 znaków przez `_mermaid_label()` (żeby diagram się renderował
    czytelnie), `"` zamieniane na `'`, `\n` na spację.
- `build_report(wf, resolver) -> str` — składa całość: nagłówek, opis, sekcja "Podstawowe
  informacje" (lista źródłowa, plik, inne listy), diagram Mermaid, "Kroki workflow" (lista
  zagnieżdżona z `<details>` na szczegóły techniczne), tabela "Pola odczytywane / zapisywane"
  (zbiera `reads`/`writes` ze wszystkich kroków, sortowane po `internal_name`).

### `generate_report.py`

CLI z `argparse`: `--input <dir_z_nwf_i_json>`, `--output <dir_docelowy>`. Skanuje `*.nwf`,
dla każdego: `parse_nwf` → `FieldResolver(wf.list_references, site_metadata, source_list_id=...)`
→ `build_report` → zapis `out/<bezpieczna_nazwa_workflow>.md`. Generuje `out/index.md` ze
spisem + (jeśli wystąpiły) listą nierozpoznanych typów akcji. Błędy parsowania pojedynczego
pliku NIE przerywają całego batcha (`try/except` per plik, log na `stderr`).

Uwaga implementacyjna: plik ma fallback importu (`if __package__ in (None, ""): sys.path.insert...`),
żeby dało się go uruchomić zarówno jako `py tools\nwf_report\generate_report.py` (bezpośrednio)
jak i jako moduł pakietu — sprawdzone, działa w obu trybach.

## 5.1. Zaimplementowany manual HTML

Plik `out/workflow-migration-manual.html` jest pojedynczym artefaktem dokumentacyjnym,
otwieranym lokalnie w przeglądarce. Zawiera:

- sekcję zakresu, stanu obecnego i ograniczenia, że eksport nie dokumentuje publicznego API Nintex;
- kontrakt REST dla uruchomienia workflow w trybie synchronicznym i asynchronicznym;
- przykłady request/response, `Idempotency-Key`, `correlationId`, statusu `202` i endpointu statusu;
- macierz błędów HTTP oraz szkice `APEX_WEB_SERVICE` i handlera ORDS/PLSQL;
- mapowanie akcji Nintex na PL/SQL i SharePoint REST;
- pełne karty czterech workflow wraz z listami źródłowymi, lookupami, polami i GUID-ami;
- diagram Mermaid dla każdego workflow oraz rozwijane źródło diagramu jako fallback tekstowy;
- kolorową legendę: lista, pole, lookup, workflow, zmienna i APEX/REST;
- wyszukiwanie, filtrowanie po liście, nawigację sekcji, `details`, kopiowanie przykładów i CSS do wydruku.

Mermaid jest ładowany z CDN jako moduł ES, więc wizualne renderowanie diagramów wymaga dostępu
do sieci. Kod diagramów pozostaje osadzony w HTML i można go odczytać bez sieci. Manual nie jest
jeszcze generowany automatycznie z raportów Markdown; przy zmianie parsera trzeba zaktualizować
go świadomie i porównać z `out/*.md`.

## 6. Wyniki weryfikacji (stan na 2026-09-19)

Wygenerowano `out/*.md` dla 4 plików z `DaneZeSkryptu`:
1. `DT01 Mechanizm Kwalifikacji Usługi.md` (lista źródłowa: Kwalifikacja Usług) —
   **zweryfikowano ręcznie**: tabela "Pola odczytywane / zapisywane" poprawnie pokazuje
   dokładnie 3 pola zapisu (DT.01.01.34, DT.01.01.38, DT.01.02.01), zgodnie z opisem
   workflow w jego własnym `<Description>`. ✅
2. `DT01 Wypełnienie pól Nr RKU oraz Nazwa.md` (Kwalifikacja Usług).
3. `RT0202 Pobranie danych z Kwalifikacji Usługi.md` (lista źródłowa: Rejestr Usług ICT,
   czyta z listy Kwalifikacja Usług przez `CrossItemLookup`) — **zweryfikowano poprawność
   rozwiązywania nazw pól w kontekście różnych list** po naprawie bugu z sekcji 7.
4. `RT0701 Pobranie danych z Kwalifikacji Usługi do RT0701.md` (lista źródłowa: Rejestr Ocen).

`UNKNOWN_TYPES_SEEN` jest puste dla tych 4 plików — wszystkie napotkane typy akcji mają
dedykowany handler.

## 7. Napotkane i naprawione bugi (historia, przydatna żeby nie powtórzyć błędu)

1. **Zagnieżdżone akcje**: pierwotne założenie że gałęzie warunku są pod tagami `Then`/`Else`
   było błędne — poprawiono na uniwersalne `ChildActivities` (patrz sekcja 4.1/4.2).
2. **Nazwa zmiennej w `SPSetVariableAdapter`**: `BLabel` zawiera WARTOŚĆ (np. "Tak"/"Nie"),
   NIE nazwę zmiennej. Prawdziwa nazwa zmiennej jest w `Parameters/Parameter[@Name='VariableName']/Variable/@Name`.
   Trzeba było dodać `param_elements` (surowe elementy XML) do `ActionNode`, bo pierwotny
   `_parse_parameters` (tylko `PrimitiveValue`) zwracał pusty string dla `Variable`/`ListLookup`.
3. **Kolizja nazw pól między listami**: `FieldResolver` musiał stać się list-aware (klucz =
   list_id/list_name + internal_name), inaczej ta sama `InternalName` na różnych listach
   dawała błędne tłumaczenie (patrz przykład w sekcji 4.3). Naprawiono przez dodanie
   `_by_list_and_name` i przekazywanie `list_hint`/`resolver.source_list_id` we wszystkich
   miejscach `action_catalog.py`, które renderują pola.
4. **Narzędzia do eksploracji dużych plików XML**: `read_file` obcina wyświetlanie bardzo
   długich linii do ~2000 znaków (niezależnie od zakresu linii), a `grep_search` zwraca tylko
   1 dopasowanie na linię (nawet przy wielu wystąpieniach wzorca w tej samej linii) — pliki
   `.nwf` to często pojedyncza linia XML (dziesiątki KB). Do eksploracji takich plików trzeba
   pisać krótkie skrypty Python (`xml.etree.ElementTree`) i uruchamiać je przez terminal,
   NIE polegać na `read_file`/`grep_search` bezpośrednio na surowej treści.

## 8. Otwarte tematy / możliwe następne kroki (nieblokujące, do decyzji z użytkownikiem)

- **Testy interakcji HTML w przeglądarce** nie są jeszcze automatyczne. `uv run pytest`
  przechodzi (65 testów na 2026-11-03), ale testy sprawdzają generator i dane, nie rzeczywiste drag/zoom/
  kliknięcia SVG ani scrollowanie sekcji. Warto dodać testy Playwright.
- **Ręczna walidacja portalu** pozostaje do wykonania w Chromium/Edge na szerokim i wąskim
  viewportcie: kliknięcia węzłów, przesuwanie, zoom, reset, wyszukiwarka i nawigacja górna.
- **`Workflow-Inventory.csv`** (UTF-16) nie jest jeszcze wczytywany/wykorzystywany w raportach —
  jego układ został sprawdzony, a 4 rekordy odpowiadają 4 eksportom `.nwf`. Można go w przyszłości
  włączyć do `index.md` i manuala, aby dodać autora, wersję, datę modyfikacji, URL i GUID-y.
- **Automatyczne generowanie manuala HTML** — obecny HTML został przygotowany ręcznie na podstawie
  raportów i eksportów. W przyszłości warto dodać generator danych HTML albo szablon, aby diagramy,
  pola i workflow nie rozjechały się po zmianach parsera.
- **Numeracja węzłów Mermaid vs. lista kroków**: obie części raportu numerują węzły niezależnie
  (osobne liczniki w `_collect_steps` i `_build_mermaid`) — wizualnie działa dobrze, ale jeśli
  w przyszłości potrzebne będzie krzyżowe odwoływanie się (np. link z kroku do węzła diagramu),
  trzeba będzie ujednolicić numerację.
- **Operator warunku**: słownik `_OPERATOR_PL` w `action_catalog.py` zawiera tylko podstawowe
  operatory Nintex — jeśli pojawią się nowe pliki `.nwf` z innymi operatorami, funkcja
  `_render_condition` zwróci pusty string dla operatora (nie wywali się, ale opis będzie mniej
  czytelny) — do rozszerzenia w razie potrzeby.
- **Nowe typy akcji**: jeśli pojawią się kolejne pliki `.nwf` spoza tego zestawu, mogą zawierać
  akcje spoza `TYPE_HANDLERS` (np. wysyłka maila `NWSendMailAdapter`, akcje na zadaniach/task,
  pętle `LoopingActionAdapter`, wywołania web service). Fallback (`_describe_fallback`) obsłuży
  je awaryjnie (pokaże surowe parametry + zarejestruje w `UNKNOWN_TYPES_SEEN` →
  `index.md`), ale dla pełnej czytelności warto dopisać dedykowane handlery gdy się pojawią —
  najszybciej sprawdzić przez `UNKNOWN_TYPES_SEEN`/sekcję w `index.md` po uruchomieniu na
  nowych plikach.
- **Diagram Mermaid dla pętli** (`LoopingActionAdapter` czy podobne) nie został przetestowany
  (nie występuje w 4 przykładowych plikach) — obecny algorytm `_build_mermaid` nie ma
  specjalnej obsługi cykli/pętli, potraktuje taki węzeł przez fallback jako zwykły krok
  sekwencyjny (bez strzałki powrotnej).

## 10. Stan na koniec sesji 2026-09-19

- Dodano `AGENTS.md` z preferencją używania `lean-ctx` i regułami pracy z repozytorium.
- Dodano `README.md` opisujący obecną funkcjonalność programu.
- Utworzono i rozbudowano `out/workflow-migration-manual.html` o diagramy Mermaid dla każdego
  workflow, źródła diagramów, identyfikatory list/pól oraz legendę kolorów obiektów.
- Rozbudowano `tools/nwf_report/html_builder.py`: diagram ma ograniczony viewport, panowanie
  pointer/touch, zoom i reset; kliknięcia węzłów otwierają dane w inspektorze; działa nawigacja
  sekcji oraz reset filtrowania po wyczyszczeniu wyszukiwarki.
- `uv run pytest` przechodzi: 24 testy. Portal został ponownie wygenerowany dla 4 workflow.
- Nie wykonano automatycznej walidacji Node.js, ponieważ Node nie jest dostępny w środowisku.
  Diagnostyka pliku Python nie zgłasza błędów; pozostaje ręczna walidacja interakcji w Chromium/Edge.
- Uruchomienie `py tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out`
  zakończyło się poprawnie dla wszystkich 4 workflow.
- Ostatni commit zsynchronizowany z GitHub: `acd6105 Document project and expand workflow manual`.
- Na kolejną sesję: ręcznie zweryfikować portal w szerokim i wąskim viewportcie, a następnie
  zdecydować, czy dodać testy Playwright dla drag/zoom, kliknięć SVG, wyszukiwania i nawigacji.

## 11. Integracja z pakietem SHP_API (2026-09-24)

> **Zastąpione przez sekcję 20** (2026-11-06): kod używa `LCDT.SHP_API` i bindów APEX; procedury `process_wf_*` usunięto.

- **Pakiet źródłowy**: `shp_api.sql` — pakiet PL/SQL do bezpośredniej integracji z SharePoint SE 2019 (NTLMv2, endpointy REST `_api/web/lists`).
- **Zastąpienie pseudokodu**: Teoretyczny pseudokod (`UPDATE tabela SET ...`) został zastąpiony konkretnymi wywołaniami funkcji pakietu:
  - `shp_api.get_list_item(p_site_url, p_list_title, p_item_id)` — pobranie rekordu i odczyt przez `json_value(l_item_json, '$.data.<InternalName>')`.
  - `shp_api.update_list_item(p_site_url, p_list_title, p_item_id, p_fields_json)` — aktualizacja pól SharePoint za pomocą `json_object('<InternalName>' value <expr>)`.
  - Warunki logiczne generują rzeczywiste wyrażenia PL/SQL (`IF json_value(...) IS NULL THEN ...`).
  - Logowanie historii używa `apex_debug.info(...)`.
- **Kompletna procedura PL/SQL**: Każdy raport Markdown (`out/<wf>.md`) zawiera dedykowaną sekcję z kompletną, gotową do kompilacji procedurą `process_wf_<nazwa>(p_item_id IN NUMBER)` orkiestrującą workflow.
- **Portal HTML**: Inspektor kafelka pokazuje dokładny kod wywołania `shp_api` dla wybranego kroku z przyciskiem „Kopiuj”, a pod diagramem dodano kartę prezentującą pełną procedurę PL/SQL wybranego workflow z przyciskiem „Kopiuj całą procedurę PL/SQL”.
- **Testy**: Zestaw testów rozszerzono do 27 testów jednostkowych (`uv run pytest`), weryfikujących generowanie wywołań `shp_api` i procedury PL/SQL.

## 12. Narzędzie automatycznej ekstrakcji metadanych z SharePoint 2019 (`sp_extractor`) (2026-09-25)

- **Lokalizacja**: `tools/sp_extractor/` (`cli.py`, `client.py`, `extractor.py`, `naming.py`).
- **Cel**: Automatyczne pobieranie metadanych list, kolumn globalnych, spisu procesów i definicji `.nwf` bezpośrednio z witryny SharePoint bez konieczności ręcznego wklejania skryptów JS w konsoli DevTools przeglądarki.
- **Parametry CLI**:
  - `URL` / `--url`: Adres URL witryny SharePoint (np. `https://sp.bank.local/sites/dora`).
  - `-o` / `--output`: Katalog docelowy. W przypadku pominięcia narzędzie automatycznie skanuje katalog roboczy i tworzy kolejny folder z auto-inkrementacją: `DaneZeSkryptu_nnn` (`DaneZeSkryptu_001`, `DaneZeSkryptu_002`, ...).
  - `-u` / `--username`, `-p` / `--password`, `-d` / `--domain`: Opcjonalne poświadczenia NTLM. W przypadku pominięcia narzędzie wykorzystuje bieżący kontekst użytkownika Windows (Single Sign-On / SSPI via `requests-negotiate-sspi`).
  - `--include-data`: Opcjonalny zrzut wierszy danych list (`20_dane_*.json`).
  - `--include-permissions`: Opcjonalny zrzut uprawnień (`30_*`).
- **Protokoły**:
  - SharePoint REST API (`application/json;odata=nometadata` z fallbackiem do `verbose`): pobieranie `00_kolumny_witryny.json`, `10_00_wszystkie_listy.json`, `10_lista_<Nazwa>.json` ze schematami `schemaXml`, kolumnami, typami zawartości i widokami.
  - Nintex Workflow SOAP Web Service (`/_vti_bin/NintexWorkflow/Workflow.asmx` - `ExportWorkflow`): eksport czystych definicji procesów do plików `.nwf`.
  - Inwentaryzacja: generowanie `Workflow-Inventory.csv` oraz `extraction_manifest.json`.
- **Kompatybilność**: Struktura wygenerowanego katalogu jest w 100% kompatybilna z wejściem generatora raportów `tools/nwf_report/generate_report.py`.
- **Testy**: Łączna liczba testów w projekcie wzrosła do 45 (wszystkie zielone w `uv run pytest`), w tym testy end-to-end zasilające raporty z wygenerowanych przez mock metadanych.

## 13. Rozszerzenie katalogu akcji Nintex (2026-10-31)

- Rozszerzono `tools/nwf_report/action_catalog.py` o 11 nowych handlerów akcji. Aktualnie `TYPE_HANDLERS` zawiera 22 wpisy, w tym handlery strukturalne; typy bez dedykowanego handlera są obsługiwane przez fallback i raportowane przez `UNKNOWN_TYPES_SEEN`.
  Nowe handlery obejmują m.in. operacje na kolekcjach, zapytania do list, opóźnienia, pętle i wysyłanie wiadomości.
- Dodano testy jednostkowe w `tools/nwf_report/tests/test_action_catalog_expanded.py`.
- Zapewniono pełne mapowanie parametrów akcji oraz wywołań `shp_api` / operacji bazodanowych w raportach Markdown i portalu HTML.

## 14. Integracja z wyzwalaczem SharePoint (workflow.xaml) i ORDS REST (2026-11-02)

> **Częściowo zastąpione przez sekcję 20**: kontrakt 17 pól jest aktualny, ale dyspozytor uruchamia teraz workflow APEX (`apex_workflow.start_workflow`) zamiast procedur `process_wf_*`.

- **Analiza kontraktu wyzwalacza**: Na podstawie `.___SP/workflow.xaml` (SharePoint Designer 2013 WF4) oraz pakietu `shp_api.sql` zidentyfikowano 17 pól JSON wysyłanych przez SharePoint w wywołaniu POST na endpoint ORDS:
  `POST https://ilapex.{Environment}.creditagricole:8082/ords/shp/nintex/main`
  Pola: `id`, `guid`, `title`, `url2`, `association`, `associator`, `initiator`, `instance`, `list`, `list_name`, `url`, `url_site`, `created`, `created_by`, `updated`, `updated_by`, `content_type`.
- **Dynamiczne parametry procedur PL/SQL**: Procedury `process_wf_<nazwa>` przyjmują dynamiczne parametry:
  `p_item_id IN NUMBER, p_site_url IN VARCHAR2 DEFAULT NULL, p_list_title IN VARCHAR2 DEFAULT NULL, p_initiator IN VARCHAR2 DEFAULT NULL, p_payload IN CLOB DEFAULT NULL`.
  W przypadku braku `p_site_url` lub `p_list_title` procedura dynamicznie cofa się do stałych z metadanych workflow (`c_site_url`, `c_list_title`).
- **Pakiet dyspozytora (`pkg_shp_dispatcher.sql`)**:
  - `tools/nwf_report/report_builder.py` (`build_dispatcher_package`): generuje pakiet `pkg_shp_dispatcher` z procedurą `dispatch_event(p_payload IN CLOB)`.
  - Parsuje 17 pól payloadu z JSON (`json_value`), odrzuca foldery (`content_type = 'Folder'`), routuje zdarzenia wg `l_association` / `l_list_title` do procedur `process_wf_*` i rejestruje logi przez `apex_debug.info`.
  - `tools/nwf_report/generate_report.py` automatycznie generuje i zapisuje `pkg_shp_dispatcher.sql` w katalogu wyjściowym raportów (`out/`, `out_002/`).
- **Rozbudowa portalu HTML**:
  - Sekcja 04: Kompletny kontrakt webhooka ORDS (tabela 17 pól, filtrowanie folderów, przykłady payloadu).
  - Sekcja 05: Architektura dyspozytora i wzorzec integracyjny PL/SQL.

## 15. Aplikacja okienkowa GUI (`tools/gui.py`, `run_gui.bat`) (2026-11-02)

- **Cel**: Uruchamianie ekstrakcji i generowania raportów w prostym interfejsie graficznym dla użytkowników nietechnicznych.
- **Implementacja**:
  - `tools/gui.py`: Desktopowa aplikacja Tkinter (nowoczesny motyw `clam`, zakładki `Ekstrakcja (sp_extractor)` oraz `Generator raportów (nwf_report)`).
  - Podgląd logów na żywo (`LogViewer` z obsługą wielowątkowości `threading.Thread`), przyciski przeglądania katalogów, otwieranie wygenerowanego portalu HTML w przeglądarce (`webbrowser.open`).
  - Automatyczne wykrywanie kolejnego folderu `DaneZeSkryptu_nnn`.
  - `run_gui.bat`: Skrypt startowy uruchamiający GUI za pomocą interpretera Python ze środowiska `.venv` (`.venv\Scripts\pythonw.exe tools\gui.py`).
- **Testy**: Dodano `tools/nwf_report/tests/test_gui.py` testujący inicjalizację okna i formularza (58 przechodzących testów w całym projekcie).

## 16. Przewodnik Oracle APEX Shared Components > Workflows (2026-11-03)

> **Rozszerzone w sekcji 20**: parametry `P_ITEM_ID..P_PAYLOAD` zastąpił jeden `P_PAYLOAD_BODY`, a zmienne `SP_*` są zasilane w krokach standardowych 3–4.

- `tools/nwf_report/apex_workflow_guide.py` buduje specyfikację definicji workflow, parametrów,
  zmiennych, typów aktywności, przejść i instrukcji PL/SQL dla aktywności z każdego pliku `.nwf`.
- `report_builder.py` dołącza przewodnik do raportów Markdown i do danych serializowanych dla portalu;
  `html_builder.py` wyświetla osobny panel APEX Workflow Designer oraz szczegóły w inspektorze.
- Zmienne procesu są dostępne w kodzie aktywności przez bindy `:STATIC_ID`. Nie generuj wywołań
  `apex_workflow.get_variable` ani `apex_workflow.set_variable`: dokumentacja APEX 24.2 opisuje
  `GET_VARIABLE_VALUE(p_instance_id, p_variable_static_id)` i `UPDATE_VARIABLES`, które jest
  administracyjną operacją na instancjach zawieszonych lub błędnych ([API reference](https://docs.oracle.com/en/database/oracle/apex/24.2/aeapi/APEX_WORKFLOW.html)).
- Wygenerowane zmienne `SP_<InternalName>` są mapowaniem wymagającym zasilenia z SharePoint przez
  `SHP_API` lub odpowiedni parametr wejściowy; przed wdrożeniem należy potwierdzić mapowanie i
  identyfikatory elementów dla akcji cross-list. Przewodnik pokazuje również syntetyczną aktywność
  `Workflow End` i przenosi źródłowe triggery do instrukcji uruchamiania procesu.
- Testy: `tools/nwf_report/tests/test_apex_workflow_guide.py` (przypisania zmiennych, Switch i
  przejścia, aktualizacja SharePoint, Wait, lookup cross-list, wyjście Markdown/HTML).

## 17. Stan przekazania (handoff) — 2026-11-03

Punkt startowy dla kolejnego agenta/LLM:

1. Przeczytaj `AGENTS.md`, potem ten plik (sekcje 4–5 format i architektura, 11–16 kolejne funkcje).
2. Weryfikacja środowiska: `uv run pytest -q` → **233 passed** (akcje warunkowe i blokady migracji, sekcja 22).
3. Regeneracja wyników: `uv run python tools\nwf_report\generate_report.py --input DaneZeSkryptu --output out`
   — tworzy 4 raporty `.md`, `index.md`, `walkthrough.md`, `pkg_shp_dispatcher.sql`, `nintex_params.sql`
   i `workflow-migration-manual.html`.
   Wyniki są wyłącznie lokalne. Katalogi `DaneZeSkryptu/`, `DaneZeSkryptu_nnn/`, `out/`
   i `out_nnn/` są ignorowane i usunięte z publikowanej historii Git; nie dodawaj ich do Git,
   również przez `git add -f`.
4. Smoke test portalu: otwórz `out/workflow-migration-manual.html`, sekcja APEX Workflow Designer
   powinna pokazywać aktywności (w tym syntetyczne `Workflow End`), a kliknięcie węzła Switch na
   diagramie aktualizuje inspektor.

Dane lokalne nieśledzone w git: `DaneZeSkryptu/`, `DaneZeSkryptu_nnn/`, `out/` i `out_nnn/` (wyniki `sp_extractor` z
prawdziwej witryny, w tym wiersze list `20_dane_*.json` z danymi biznesowymi). Są ignorowane w
`.gitignore` i nie mogą trafić do repozytorium.

Otwarte kroki (priorytetowo):

- **APEX**: potwierdzić w docelowej wersji APEX, że bindy `:STATIC_ID` zmiennych workflow są
  zapisywalne w aktywnościach „Execute Code”; skompilować wygenerowany PL/SQL na środowisku.
- **Mapowanie `SP_<InternalName>`**: zrealizowane w krokach standardowych 3–4 (sekcja 20);
  pozostaje potwierdzić identyfikatory elementów dla akcji cross-list z kluczem innym niż ID.
- **Sygnatury `SHP_API`**: wywołania są zgodne z `SHP_API_spec.sql`; skompilować wygenerowany kod
  na środowisku z pakietem `LCDT.SHP_API` (sekcja 20, „Do potwierdzenia”).
- **Kolizje Static ID**: identyfikatory są wyprowadzane z tytułów; dwa tytuły normalizujące się do
  tego samego ID mogą kolidować — dodać deduplikację (sufiks) w `apex_workflow_guide.py`.
- **Testy przeglądarkowe** (Playwright) dla drag/zoom/kliknięć SVG/wyszukiwania/kopiowania.
- Pozostałe tematy z sekcji 8 (`Workflow-Inventory.csv`, pętle w Mermaid, nowe operatory).

## 18. Tytuł i informacje „O aplikacji” — 2026-11-05

- Tytuł okna Tkinter: `Migracja Nintex Workflow -> Oracle APEX` (usunięto wyłącznie
  prefiks `DORA - `). Wewnętrzny nagłówek `DORA: Migracja SharePoint 2019 -> Oracle APEX`
  oraz tytuły portalu HTML pozostają bez zmian.
- Przycisk „O aplikacji” w nagłówku Tkinter otwiera `messagebox.showinfo` z głównym oknem
  jako rodzicem. W portalu przycisk obok przełącznika motywu otwiera natywny `<dialog>`.
- Oba interfejsy korzystają ze wspólnych stałych w `tools/nwf_report/app_info.py`:
  `REMBIASZ GRC Tech Solutions Tomasz Rembiasz, NIP: 8871550162`,
  `Aplikacja powstała dla Credit-Agricole Bank Polska S.A.` oraz `Wersja: 3.0`.
  To wersja wyświetlana; wersja pakietu w `pyproject.toml` pozostaje bez zmian.
- Moduł informacji należy do pakietu `nwf_report`, aby działały zarówno importy GUI,
  jak i bezpośrednie uruchamianie `tools\nwf_report\generate_report.py`.
- Dialog HTML działa niezależnie od Mermaid, obsługuje oba motywy, zawijanie tekstu,
  zamknięcie przyciskiem lub Escape i przywrócenie fokusu na przycisk „O aplikacji”.
- Weryfikacja: 11 testów GUI, HTML i przewodnika APEX przeszło poprawnie. Test CLI
  sprawdza uruchamianie skryptu z katalogu innego niż repozytorium.
- Kontrole wykonawcze: brak nakładania się przycisku i nagłówka Tkinter przy szerokości
  800 i 950 px; dialog portalu przy 375 i 1280 px w obu motywach, klawiatura i brak Mermaid.
  Sprawdzono również nawigację, wyszukiwanie i zoom diagramu oraz lokalną regenerację 4 raportów.

## 19. Belka wyszukiwania portalu HTML — 2026-11-05

- Usunięto siedem przycisków nawigacji sekcji z belki pod nagłówkiem, wraz z ich stylami
  i listenerami. W belce pozostało tylko pole `global-search`; wszystkie sekcje treści
  (inwentaryzacja, diagram, słownik, REST, APEX, Workflow Designer i checklista) pozostają.
- `renderTabs` ponownie nakłada filtr na zakładki workflow, a `renderFieldsTable` na
  wiersze słownika za pomocą `filterFieldsTable`. Filtr nie znika po automatycznym
  lub ręcznym przełączeniu workflow ani po zmianie motywu.
- Zakładki i dane workflow są inicjalizowane niezależnie od pobrania Mermaid z CDN.
  Wyszukiwanie działa offline; diagram jest renderowany po zdarzeniu `mermaidReady`.
- Weryfikacja w przeglądarce: tytuł, typ akcji, `InternalName`, wielkość liter i skrajne
  spacje, brak dopasowań, wyczyszczenie pola, przełączenie workflow oraz motywu.
  Sprawdzono działanie bez Mermaid oraz z wyrenderowanym diagramem, bez błędów JavaScript.
- `uv run pytest tools\nwf_report\tests\test_html_builder.py tools\nwf_report\tests\test_apex_workflow_guide.py`
  → 10 passed. Test belki potwierdza brak przycisków i zachowanie siedmiu sekcji.
  Zregenerowano lokalne `out/` dla 4 workflow; katalog pozostaje poza synchronizacją Git.

## 20. Standardowy proces APEX Workflow (NINTEX_PARAMS, kroki 1–4, ścieżki A/B) — 2026-11-06

Wszystkie wyjścia generatora (raporty Markdown, portal HTML, `pkg_shp_dispatcher.sql`, nowy
`nintex_params.sql`) odwzorowują proces tworzenia workflow w APEX ustalony przez użytkownika.

- **Kroki standardowe** (`apex_workflow_guide._standard_activities`, id `std_start`, `std_payload`,
  `std_get_item`, `std_parse`):
  1. *Workflow Start* + *Additional Data* (SQL Query na `NINTEX_PARAMS` złączonej z `apex_workflows`
     po `workflow_def_static_id`, `WHERE w.workflow_id = :APEX$WORKFLOW_ID`) → parametry `P_*`.
     `P_*` są niezmienne w czasie trwania przepływu, a `V_*`/`SP_*` można zmieniać.
  2. *Execute Code „Retrieve Payload”* (`RETRIEVE_PAYLOAD_CODE`, kod użytkownika 1:1) — `:P_PAYLOAD_BODY`
     → `V_ITEM_ID`, `V_SITE_URL`, `V_LIST_TITLE`, `V_EDITOR`; puste wartości → `-20010` (FAULTED).
  3. *Invoke API* `LCDT` → `SHP_API` → `GET_LIST_ITEM`. Ręcznie wpisywany jest tylko `p_query`, który
     `build_shp_query` buduje automatycznie z pól czytanych przez workflow. Wynik trafia do `V_SHP_ANSWER`.
     - Pola proste trafiają do `$select` pod `EntityPropertyName`, jeśli dostępne.
     - User: `F/Title,F/EMail,F/Name` + `$expand`.
     - Lookup: `F/Id,F/<LookupField>` + `$expand`; kolumna dodatkowa korzysta z relacji
       głównej wskazanej przez GUID `FieldRef` w `SchemaXml` (szczegóły w sekcji 23).
     - Bez pól: `$select=Id`.
     - `SendMessage` dodaje pole `Editor`.
  4. *Execute Code „Parse”* (`build_parse_code`) — `data.<pole>` z `V_SHP_ANSWER` do `SP_<InternalName>`.
     - User: `SP_F` (Title), `SP_F_EMAIL`, `SP_F_NAME`.
     - Lookup: `SP_F` (wartość skonfigurowanego pola docelowego) i `SP_F_ID` (NUMBER).
     - Number: `get_number`.
     - DateTime: `TIMESTAMP WITH TIME ZONE` (UTC).
- **Ścieżka A**: aktywność na każdą akcję Nintex (`spec.activities`, przejście „Ścieżka A” z `std_parse`).
  **Ścieżka B**: `spec.path_b` — jedna aktywność Execute Code z kodem z `action_catalog.build_path_b_code`
  (`generate_plsql_statements` + `wrap_plsql_block`, deklaruje `l_resp`/`l_ref_json` tylko gdy użyte).
- **Konwencje nazw** (`tools/nwf_report/apex_naming.py`):
  - Static ID workflow: `WF_<TYTUŁ>` (mapowanie `ł`→`l`).
  - Zmienne pól: `SP_<INTERNALNAME>[_ID|_EMAIL|_NAME]`.
  - Stałe adresy e-mail: `P_EMAIL_<localpart>` (≤ 30 znaków), nadawca `P_EMAIL_FROM`.
  - Pakiet zawsze w pełni kwalifikowany: `LCDT.SHP_API`.
- **Kod akcji** (`action_catalog.py`):
  - Bindy `:STATIC_ID` zamiast zmiennych lokalnych `l_*`.
  - Bieżący element to `:V_LIST_TITLE`/`:V_ITEM_ID`. Także `SPUpdateItemWithKey` bez `ListId` lub z `ListId` listy źródłowej.
  - Lookup jest zapisywany jako `'<pole>Id'`.
  - User jest zapisywany przez `LCDT.SHP_API.ensure_user_id`.
  - Cross-list lookup z kluczem ID → `get_list_item`; z innym kluczem lub nierozpoznaną listą → blokada i ręczna migracja (sekcja 22).
  - `Coercion` `LookupId…` na polu Lookup/User czyta `F/Id` zamiast wartości pola docelowego.
  - `Delay` → natywna aktywność *Wait* (bez `DBMS_SESSION.SLEEP`).
  - `StartWorkflow` bez oczekiwania → `apex_workflow.start_workflow` z `P_PAYLOAD_BODY`; oczekiwanie blokuje ścieżkę B i wymaga konfiguracji `Invoke Workflow` w ścieżce A.
  - `SendMessage` → `apex_mail.send` z `p_to => :P_EMAIL_*`, `p_from => :P_EMAIL_FROM`.
- **`metadata_loader.FieldResolver.get_field_type(name, list_hint)`** — typ pola z uwzględnieniem
  listy. Kolejność źródeł: ListReferences, potem kolumny listy z metadanych witryny, potem kolumny witryny.
- **`nintex_params.sql`** (`build_nintex_params_script`):
  - Zakomentowany, referencyjny DDL tabeli zgodny z podaną definicją: `ID` jako identity i klucz główny,
    unikalny `WORKFLOW_STATIC_ID VARCHAR2(500)`, pola audytowe i `RESPONSIBLE`. Bazowe pola parametrów
    to `P_VAR_01..04`, `P_NUM_01..04`, `P_DATE_01..04` i `P_CLOB_01..02`; wszystkie `C_*` mają typ
    `VARCHAR2(4000)` (także `C_NUM_*`, `C_DATE_*` i `C_CLOB_*`).
  - Zakomentowany DDL triggera `NINTEX_PARAMS_BIU` uzupełniającego obowiązkowe pola audytu przy `INSERT`
    i `UPDATE`. Trigger musi być włączony przed uruchomieniem `MERGE`.
  - `MERGE` dla każdego workflow, na końcu `COMMIT`. `WHEN MATCHED` aktualizuje tylko znane wartości,
    więc nie nadpisuje pustych wartości (np. nadawcy) uzupełnionych przez administratora.
  - Nowe wiersze otrzymują domyślne `IS_ACTIVE = 0`; `MERGE` nie zmienia tej flagi, a Additional Data
    jej nie filtruje. Generator nie decyduje o aktywacji workflow.
  - Obecnie automatycznie wykrywane są stałe adresy e-mail i mapowane kolejno do `P_VAR_nn` bez limitu.
    Jeśli kolumny nie ma w bazowym DDL, raport i skrypt ostrzegają o wymaganym rozszerzeniu przed `MERGE`
    i użyciem Additional Data. Administrator weryfikuje schemat i dodaje potrzebne kolumny lub typy;
    generator nie odczytuje schematu bazy i nie wykonuje `ALTER TABLE`.
- **`pkg_shp_dispatcher.sql`** (`report_builder.build_dispatcher_package`):
  - Odczytuje 17 pól payloadu i ignoruje foldery.
  - `CASE l_association WHEN '<tytuł>' THEN l_static_id := 'WF_…'`; nieznane `association` zwraca 200 z ostrzeżeniem.
  - Wywołuje `apex_session.create_session` → `apex_workflow.start_workflow(p_parameters => P_PAYLOAD_BODY (CLOB), p_initiator, p_detail_pk => id)` → `delete_session` (także w obsłudze wyjątku).
  - Stała `c_app_id` jest do uzupełnienia (TODO).
- **Raport Markdown**: sekcja APEX zawiera kolejno Parameters, Additional Data, Variables, Kroki standardowe (1–4),
  Ścieżkę A i Ścieżkę B. Sekcję `process_wf_*` zastąpił fragment routingu dyspozytora; klucz `plsql_procedure`
  w danych portalu zastąpił `apex_workflow_spec.path_b`.
- **Portal HTML**:
  - Sekcja 05: przebieg standardowy, P_ vs V_, dyspozytor `start_workflow`, zapytanie NINTEX_PARAMS.
  - Sekcja 06: Additional Data, karty kroków 1–4 (tabela mapowania Invoke API), przełącznik Ścieżka A / Ścieżka B.
  - Karta pod diagramem pokazuje kod ścieżki B.
  - Checklista obejmuje NINTEX_PARAMS, `EXECUTE` na `LCDT.SHP_API`, `c_app_id` i test błędu -20010.
- **Weryfikacja**:
  - `uv run pytest` → 81 passed; nowe testy w `tools/nwf_report/tests/test_apex_process.py`.
  - Regeneracja `out/` dla 4 workflow.
  - Portal sprawdzony w headless Edge (`uv run --with playwright`): brak błędów JS, 4 karty kroków standardowych, działający przełącznik A/B.
- **Do potwierdzenia na środowisku**:
  - Kolumna `apex_workflows.workflow_def_static_id` (przyjęta za zapytaniem użytkownika).
  - Nazwa aktywności „Invoke Workflow” w APEX 24.2.
  - Kompilacja wygenerowanego PL/SQL.
  - Kolekcje/pętle JSON w CLOB i ich ograniczenia opisuje sekcja 21; kod wymaga testów na docelowej wersji Oracle/APEX.

## 21. Eksport 008 — akcje Nintex, blokady i bezpieczeństwo raportów

- Katalog `tools/nwf_report/action_catalog.py` zawiera 28 handlerów, w tym
  `NWRunSqlAdapter`, `NWCreateItemWithContentTypesAdapter`, `SPMathAdapter`,
  `NWDeleteMultipleItemAdapter`, `NWCollectDataAdapter` i `NWCancelWorkflowAdapter`.
  Rozpoznanie typu nie oznacza gotowości do wykonania. Nieznane typy nadal używają fallbacku,
  a `UNKNOWN_TYPES_SEEN` jest zerowany przy każdym uruchomieniu generatora.
- Parser zachowuje `WorkflowType`, wielowartościowe parametry, metadane list i powiązania
  kolumna–kolekcja. `tools/nwf_report/sensitive_data.py` usuwa rozpoznane poświadczenia z kopii
  XML akcji przed budowaniem modelu; pominięcie jest widoczne i blokuje wykonanie. Ochrona jest
  heurystyczna: nietypowe nazwy lub formaty sekretów wymagają dodatkowej kontroli.
- SQL Server pozostaje źródłem danych. Wymagany jest uzgodniony Oracle Database Gateway,
  uprawnienia i zweryfikowany przez administratora database link. Mapowanie wyników następuje
  po nazwie lub aliasie projekcji `SELECT`, nie po kolejności XML. Dla wystąpień w eksporcie 008
  rozpoznano 34 i 5 kolumn; w pierwszym 30 pozycji mapowań ma inną kolejność niż projekcja.
  Raport i inspektor HTML zawierają **niewykonywalny szablon referencyjny** z jednym kursorem,
  obsługą `NULL` i zamknięciem kursora również przy błędzie. Nie zawiera surowego SQL ani
  poświadczeń; nazwa linku i zapytanie są placeholderami. Typy, wiązania, puste ciągi, uprawnienia
  i zgodność Gateway wymagają ręcznej konfiguracji i testów integracyjnych. Akcja pozostaje zablokowana.
- Tworzenie z typem zawartości opisuje listę, `Overwrite`, pola i konwersje oraz dostarcza
  blokowany szablon payloadu. Nie zakłada zgodności typu zawartości ani `Overwrite` z istniejącym
  `LCDT.SHP_API`; daty i liczby wymagają ręcznej konwersji. Pusta zmienna wyjściowa nie powoduje
  wymyślenia ID. `mod` jest generowany tylko dla nieujemnych liczb całkowitych i dodatniego
  dzielnika, z jawnym błędem dla pozostałych wartości.
- `Query List`, masowa aktualizacja i usuwanie są zablokowane do potwierdzenia filtru,
  mapowań i pełnej paginacji (`next_url`). Publiczne `SHP_API` nie udostępnia usuwania.
  Nie generuje się niezawężonej aktualizacji ani wywołania nieistniejącego API.
- `Collect Data` wymaga zadania APEX, formularza, mapowania odpowiedzi i wznowienia po jego
  ukończeniu; synchroniczna ścieżka B nie udaje oczekiwania. `Cancel Workflow` dotyczy innych
  instancji na bieżącym elemencie i wymaga potwierdzenia doboru instancji, uprawnień oraz
  semantyki Nintex wykonywanej przy commit. Obie operacje są zablokowane.
- Kolekcje `ArrayList` są modelowane jako tablice JSON w CLOB, indeksowane od zera. Tekstowe
  `Get` i pętla ścieżki B zachowują `NULL`, kontrolują zakres i odrzucają nieobsługiwane typy
  oraz pusty tekst, którego Oracle nie odróżnia bezpośrednio od `NULL`. `DateTime Get`,
  niepotwierdzony `Break` i pętla ścieżki A wymagają ręcznej migracji lub weryfikacji.
  Wygenerowane fragmenty nie zostały uruchomione na Oracle/APEX.
- Blokady wspólne są umieszczane przed akcjami standardowymi, a dla blokady samej ścieżki A
  używany jest osobny guard. Zablokowana ścieżka B zawiera wyłącznie błąd przed zapisami.
  Kolizje znormalizowanych Static ID zmiennych, parametrów i pól także blokują obie ścieżki;
  wymagają ręcznego mapowania. Kolizje Static ID samych aktywności pozostają otwartym tematem.
- Workflow `Site` oraz brakujący lub nierozpoznany `WorkflowType` mają ręczną migrację startu,
  nie są włączane do dyspozytora list i nie otrzymują standardowego kroku `GET_LIST_ITEM`.
  Dla `Site` nie wywnioskowano harmonogramu. Tożsamość pól w raportach uwzględnia listę
  i `InternalName`. Portal zabezpiecza osadzony JSON oraz renderowanie nazw pól jako tekst.
- Testy: `uv run pytest` → **140 passed**; `python -m compileall` dla generatora zakończony
  poprawnie. Lokalna kontrola eksportu 008 potwierdziła 8 workflow, 0 nieznanych typów, mapowania
  SQL i pól oraz blokady A/B. Testy Edge offline na danych syntetycznych i wygenerowanym portalu
  008 sprawdziły przełączanie A/B, status, `Site` i bezpieczne renderowanie pól; nie obejmowały
  zewnętrznego skryptu Mermaid.
- Wyniki dla 008 generuj do nowego ignorowanego katalogu, nie nadpisuj `out_008/`.
  Istniejący eksport i starsze raporty mogą zawierać dane uwierzytelniające: ogranicz dostęp
  i rozważ rotację zgodnie z polityką organizacji. Nie commituj danych ani katalogów wynikowych.
  Testów integracyjnych Oracle, SQL Server, APEX i SharePoint nie wykonano; przed wdrożeniem
  wymagają uzgodnionego środowiska, syntetycznych danych i odpowiednich uprawnień.

## 22. Akcje warunkowe, operatory warunków i tokeny `Common` — 2026-11-07

- **Błąd naprawiony:** `report_builder._build_mermaid_with_steps.walk` nie miał gałęzi dla
  `NWRunIf2Adapter`, więc dzieci RunIf nie trafiały do Mermaid, nie dostawały `node_id` (brak `[nX]`
  w raporcie, puste cele przejść ``True → `` `` w przewodniku APEX ścieżki A), a `plsql_code` zawierał
  tylko placeholder `-- Akcje warunkowe`. `node_id` kroków pochodzą WYŁĄCZNIE z `walk`.
- `walk` zwraca końce jako pary `(id, etykieta)`: RunIf = romb, dzieci z krawędzią `Tak`, obejście `Nie`;
  puste gałęzie IfElse zachowują etykietę; nieznane kontenery także rozpisują dzieci.
  Strukturalne `WFSequenceAdapter` nie dostają `node_id` (tak jak gałęzie IfElse).
- `action_catalog._conditional_plsql` generuje pełne `IF/ELSE/END IF` z kodem dzieci dla RunIf i IfElse
  (używane przez `describe_action` i ścieżkę B). Blokady dzieci NIE są agregowane w rodzicu
  (`collect_blocking_reasons` rekurencyjnie zbiera je z dzieci).
- Warunki `NWConditionConfig` (`_plsql_condition`, `_condition_parts` pomija `<Coercion>`):
  `IsEmpty`/`Equal ''` → `IS NULL`; `NotIsEmpty`/`NotEqual ''` → `IS NOT NULL`;
  `NotEqual` z niepustym literałem → `(l IS NULL OR l != r)`; `Contains`/`NotContains` → `INSTR`,
  `StartsWith` → `INSTR = 1`, `EndsWith` → `SUBSTR`. Brakujący lub nierozpoznany operator,
  typ warunku albo nieobsługiwana wartość blokują migrację. Semantyka NULL dla wszystkich
  dynamicznych porównań nie została potwierdzona.
- Wartości specjalne: `SpecialReference` (nazwa w tekście elementu) `CurrentDate` → `TRUNC(SYSDATE)`,
  `CurrentTime` → `SYSDATE`; `WorkflowContextData Name="StartDate"` / `{Common:StartDate}` →
  `SYSTIMESTAMP /* przybliżenie */` (czas kroku, nie startu workflow). `{Common:WebUrl}` →
  `:V_SITE_URL`, `{Common:ItemUrl}` → URL `listform.aspx?PageType=4&ListId=..&ID=` listy źródłowej;
  adres wymaga potwierdzenia integracyjnego. Daty w tekście są formatowane przez `TO_CHAR`.
  Nieprzetłumaczone tokeny `{...:...}` w kodzie, poza komentarzami, blokują akcję.
- `SPUpdateItemWithKeyAdapter`: klucz jest czytany z `param_elements["LookupFieldValue"]` (`params`
  przechowuje tylko `PrimitiveValue`). Klucz ID → bind/`TO_NUMBER`; tekstowy lub liczbowy klucz
  innego pola → `SHP_API.get_list_items` z `$select=Id&$top=2&$filter=<pole>%20eq%20...`.
  Tekst jest escapowany dla OData i kodowany `UTL_URL.escape`, a liczby używają `TO_CHAR(..., 'TM9', ...)`.
  Brak definicji klucza blokuje migrację; pusty klucz w czasie wykonania lub brak elementu → `-20094`;
  wiele wyników lub `next_url` → `-20095`. Nieznana lista, typ albo nieobsługiwana nazwa pola filtru
  blokują migrację.
- `CrossItemLookup` po ID korzysta z `get_list_item`; nierozpoznana lista docelowa oraz klucz
  inny niż ID blokują obie ścieżki. Ten drugi wariant wymaga osobnego odwzorowania kodowania OData,
  typu, pustego klucza i semantyki wielu wyników; nie używaj starego przykładu z `$top=1`.
- `SPSetFieldWithKeyAdapter` czyta `Variable`/`ListLookup` z `param_elements`; brak wartości blokuje
  akcję, a jawna pusta wartość jest dozwolona. Aktualizowanie i tworzenie elementów rozróżnia pola listy
  źródłowej i docelowej; brak mapowania pól blokuje oba typy akcji, a brak ustalonej listy blokuje tworzenie.
  `NWBuildStringAdapter` używa rzeczywistej zmiennej `Output` albo blokuje akcję.
- `SP_*` jest zasilane podczas początkowego pobrania elementu i nie jest automatycznie odświeżane
  po jego aktualizacji. `collect_blocking_reasons` blokuje obie ścieżki, gdy wykryje możliwy odczyt
  pola bieżącego elementu po jego zapisie; uwzględnia gałęzie, kolejne iteracje, równoległość oraz
  kontekst listy. Aktualizacja po kluczu w tej samej liście jest traktowana zachowawczo jako możliwa
  modyfikacja bieżącego elementu. Nie wykrywa wszystkich pośrednich zmian powodowanych przez SharePoint
  lub inne procesy. Docelowe rozwiązanie wymaga ponownego `GET_LIST_ITEM` i parsowania pól po zapisie
  oraz testów integracyjnych; blokady nie należy pomijać bez ręcznej weryfikacji.
- `nwf_parser.collect_workflow_variables` dostarcza wspólną listę zmiennych raportom i przewodnikowi
  APEX: obejmuje parametry, `ValueStorage`, mapowania pól, warunki oraz tokeny w wiadomościach.
  Źródłowy typ Nintex pozostaje w raporcie, a przewodnik mapuje go na typ APEX.
- `NWStartWorkflow2Adapter` wymaga ustalonego celu i rozpoznanej wartości `WaitForComplete`
  (`true`/`false` lub `1`/`0`). Gdy oczekiwanie jest włączone, ścieżka A wymaga jego konfiguracji
  w `Invoke Workflow`, natomiast ścieżka B jest zablokowana (samo `start_workflow` nie czeka).
  Workflow `Site` ma zablokowane obie ścieżki. Przykładowy `Invoke Workflow` może zawierać w tym
  kontekście niezadeklarowane bindy `P_PAYLOAD_BODY` i `V_ITEM_ID`; wymaga ręcznego odwzorowania,
  a blokady startu nie wolno usuwać przed potwierdzeniem kontekstu.
- Testy: `tools/nwf_report/tests/test_conditional_actions.py` i pozostałe testy projektu;
  `uv run pytest -q` → **233 passed**. Nie wykonano integracyjnych testów Oracle/APEX ani SharePoint.
- Otwarte: `NWQueryListAdapter`, pętla ForEach w ścieżce A, kolekcje `DateTime`, bezpieczny
  `CrossItemLookup` po kluczu innym niż ID oraz potwierdzenie semantyki dat, URL i typów danych.

## 23. Pola Lookup w zapytaniach REST — 2026-11-09

- `FieldResolver.resolve_rest_field` korzysta z metadanych konkretnej listy. Nazwę REST bierze
  z `EntityPropertyName`, a wartość Lookup z `LookupField` / `ShowField` i `EntityPropertyName`
  odpowiedniej kolumny listy docelowej.
- Dodatkowa kolumna Lookup ma w `SchemaXml` atrybut `FieldRef` zawierający GUID pola głównego.
  `$select` i `$expand` używają jego nazwy REST, a `Parse` odczytuje właściwe pole z tej relacji.
  Zmienne `SP_*` nadal powstają z oryginalnego `InternalName` kolumny Nintex. Wspólne relacje
  i pola `Id` są deduplikowane. Ta sama reguła dotyczy `CrossItemLookup`.
- Nieguidowe wartości `FieldRef` pól systemowych (np. `ID` lub `DocId`) nie oznaczają relacji
  dodatkowej: zachowane jest dotychczasowe mapowanie i raport zawiera ostrzeżenie.
- Brak lub niejednoznaczność pola głównego, niespójne listy, brak pola docelowego dodatkowego
  Lookup albo błędny `SchemaXml` blokują migrację i pomijają niepoprawne pole w zapytaniu.
  Brak niektórych metadanych REST skutkuje ostrzeżeniem i zachowuje wcześniejszy fallback.
- Testy regresyjne: `tools/nwf_report/tests/test_rest_lookup_fields.py`. Odczyty wymagają
  nadal testu integracyjnego na docelowym SharePoint. Zapisy pól, w tym przypadki, w których
  `EntityPropertyName` różni się od `InternalName`, oraz pola wielowartościowe wymagają
  osobnej weryfikacji.
