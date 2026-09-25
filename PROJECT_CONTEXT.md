# Kontekst projektu dla LLM — generator raportów z Nintex Workflow (.nwf)

Ten plik jest przeznaczony dla modelu/agenta AI kontynuującego pracę nad tym projektem.
Zawiera wszystkie ustalone fakty, decyzje i szczegóły techniczne, żeby nie trzeba było
ich odkrywać/weryfikować od nowa. Aktualny na: 2026-09-25.

## 1. Cel projektu

Katalogi `DaneZeSkryptu/`, `DaneZeSkryptu_001/`, `DaneZeSkryptu_002/` zawierają zrzuty konfiguracji witryn SharePoint 2019
(wyeksportowane automatycznie narzędziem `sp_extractor` lub wg procedury w [manual-sharepoint-2019-dla-poczatkujacych-v3 (1).md](manual-sharepoint-2019-dla-poczatkujacych-v3%20(1).md))
oraz pliki `.nwf` — zrzuty konfiguracji przepływów pracy Nintex Workflow.

Zbudowano dwa główne narzędzia:
1. `tools/sp_extractor/` — automatyczny ekstraktor konfiguracji i workflow z SharePoint 2019 przez REST API + SSPI (Windows SSO) + truststore (Windows cert store), tworzący kolejne katalogi `DaneZeSkryptu_nnn`.
2. `tools/nwf_report/` — generator raportów Markdown i portalu HTML, analizujący pliki `.nwf` i metadane JSON, mapujący akcje Nintex na procedury PL/SQL pakietu `shp_api` i Oracle APEX oraz generujący diagramy Mermaid.

**Status (2026-09-25): w pełni zaimplementowane i przetestowane (56 testów unit/e2e przechodzących pomyślnie).**
- Obsługa 11 dodatkowych typów akcji Nintex (`NWBuildStringAdapter`, `NWBusinessProcessAdapter`, `NWCalculateDateAdapter`, `NWCollectionAdapter`, `NWCreateSiteSpecificItemAdapter`, `NWDelayForAdapter`, `NWForEachLoopAdapter`, `NWQueryListAdapter`, `NWSendMessageAdapter`, `NWStartWorkflow2Adapter`, `NWUpdateMultipleItemAdapter`).
- Weryfikacja na witrynie ITMM (`DaneZeSkryptu_002`, 10 workflows): **0 nierozpoznanych typów akcji**.
- Wygenerowano raporty i portal do `out/` oraz `out_002/`.

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

- `ColumnInfo(title, internal_name, type_as_string="", formula="")`
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
  - `NWRunIf2Adapter` → "Wykonaj TYLKO JEŻELI ..." (warunek bez jawnego "else"), `reads`.
  - `NWCommitAdapter` → "Zapisz (zatwierdź) zebrane zmiany" (commit zmian zebranych przez
    wcześniejsze `SetField`/`UpdateItem` w tej samej "transakcji").
  - `NWBuildStringAdapter` → dynamiczne łączenie ciągów tekstowych/zmiennych (`Input` -> `Output`).
  - `NWBusinessProcessAdapter` → wydzielone etapy procesu biznesowego (`StageName`), kontener podrzędnych akcji.
  - `NWCalculateDateAdapter` → przesunięcia dat o dni/miesiące/godziny (`Date`, `Days`, `Months`, `Hours` -> `Output`).
  - `NWCollectionAdapter` → operacje na kolekcjach (Get, Count, Join, etc.).
  - `NWCreateSiteSpecificItemAdapter` → tworzenie nowych rekordów na listach SharePoint (`shp_api.create_list_item`).
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
  przechodzi (24 testy), ale testy sprawdzają generator i dane, nie rzeczywiste drag/zoom/
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

