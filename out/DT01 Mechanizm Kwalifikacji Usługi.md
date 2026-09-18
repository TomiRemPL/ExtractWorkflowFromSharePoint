# DT01 Mechanizm Kwalifikacji Usługi

> Wyliczenie wartości pól w formularzu DT.01.01.01:
> 1. Usługa ICT wg DORA? (DT.01.01.34)
> 2. Usługa krytyczna wg DORA? (DT.01.01.38)
> 3. Zwiększone ryzyko koncentracji? (DT.01.02.01)

## Podstawowe informacje

- **Lista źródłowa:** Kwalifikacja Usług
- **Plik źródłowy:** `DT01_Mechanizm_Kwalifikacji_Usługi (1).nwf`
- **Inne listy używane przez workflow:** Zadania przepływu pracy

## Diagram przepływu

```mermaid
flowchart TD
  start((Start))
  n1["Start workflow 'DT01 Mechanizm Kwalifikacji Usługi'. Urucha…"]
  start --> n1
  n2{"Warunek: JEŻELI (wartość pola Telefonia analogowa? (DT.01.0…"}
  n1 --> n2
  n3{"Warunek: JEŻELI wartość pola Usługa cykliczna? (DT.01.01.33…"}
  n2 -- Nie --> n3
  n4["DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34'…"]
  n3 -- Nie --> n4
  n5{"Warunek: JEŻELI wartość pola Typ usługi ICT (DT.01.01):Symb…"}
  n3 -- Tak --> n5
  n6["DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34'…"]
  n5 -- Nie --> n6
  n7["DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34'…"]
  n5 -- Tak --> n7
  n8["DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34'…"]
  n2 -- Tak --> n8
  n9{"Warunek: JEŻELI {WorkflowVariable:zm_DT-01-01-34} jest równ…"}
  n4 --> n9
  n6 --> n9
  n7 --> n9
  n8 --> n9
  n10["zm_DT-01-01-38: Zapisz w zmiennej 'zm_DT-01-01-38' wartość:…"]
  n9 -- Nie --> n10
  n11{"Warunek: JEŻELI (wartość pola Usługa krytyczna wg EBA? (DT.…"}
  n9 -- Tak --> n11
  n12["zm_DT-01-01-38: Zapisz w zmiennej 'zm_DT-01-01-38' wartość:…"]
  n11 -- Nie --> n12
  n13["zm_DT-01-01-38: Zapisz w zmiennej 'zm_DT-01-01-38' wartość:…"]
  n11 -- Tak --> n13
  n14{"Warunek: JEŻELI (wartość pola Dostawca (DT.01.01.03) (Dosta…"}
  n13 --> n14
  n15["zm_DT-01-02-01: Zapisz w zmiennej 'zm_DT-01-02-01' wartość:…"]
  n14 -- Tak --> n15
  n16["Zapisz wpis w historii przepływu: „DT-01-01-34 Usługa DORA …"]
  n10 --> n16
  n12 --> n16
  n14 --> n16
  n15 --> n16
  n17["Zaktualizuj element w bieżącym elemencie: ustaw pola Usługa…"]
  n16 --> n17
  stop((Koniec))
  n17 --> stop
```

## Kroki workflow

- `[n1]` Start workflow 'DT01 Mechanizm Kwalifikacji Usługi'. Uruchamiane: ręcznie, przy utworzeniu elementu, przy zmianie elementu.
  > **Wskazówka migracji**: Wyzwalacz procesu (Triggers: ręcznie, przy utworzeniu elementu, przy zmianie elementu). Punkt wejścia przyjmujący parametr itemId. (APEX: `Wywołanie z endpointu REST / ORDS lub trigger bazodanowy / start procesu w Flows for APEX.`)
  <details><summary>Szczegóły techniczne</summary>

  ```
  StartManually = true
  StartOnCreate = true
  StartOnChange = true
  WorkflowName = DT01 Mechanizm Kwalifikacji Usługi
  WorkflowDescription = Wyliczenie wartości pól w formularzu DT.01.01.01:
1. Usługa ICT wg DORA? (DT.01.01.34)
2. Usługa krytyczna wg DORA? (DT.01.01.38)
3. Zwiększone ryzyko koncentracji? (DT.01.02.01)
  WorkflowDuration = -1
  TaskListId = {2DC84853-CA02-4D4C-8521-8A3C2CD72A3A}
  StartPage = _layouts/15/NintexWorkflow/StartWorkflow.aspx
  VerboseLogging = false
  Category = List
  ContentType = 
  StartOnCreateCondition = false
  StartOnChangeCondition = false
  HistoryLogging = true
  RequireManagePermission = false
  HistoryListName = NintexWorkflowHistory
  ChangeComments = 
  Id = {0076FF37-500D-4E62-A445-D54959D8E0C3}
  SkipValidation = false
  ContentTypeName = Wszystkie
  DisplayStatusColumn = false
  StartFromMenu = false
  StartFromMenuLabel = 
  EcbId = 00000000-0000-0000-0000-000000000000
  CustomActionSequence = 0
  CustomActionIcon = _layouts/15/NintexWorkflow/Images/StartWorkflowECB.png
  UsesConditionalStart = false
  ```
  </details>
- `[n2]` Warunek: JEŻELI (wartość pola Telefonia analogowa? (DT.01.01.31) (DT_x002e_01) z bieżącego elementu jest równe Tak) LUB (wartość pola Model kontraktowania (DT.01.01.10) (Model_x0020_kontraktowy_x0020__x) z bieżącego elementu jest równe ATU)
  > **Wskazówka migracji**: Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: (wartość pola Telefonia analogowa? (DT.01.01.31) (DT_x002e_01) z bieżącego elementu jest równe Tak) LUB (wartość pola Model kontraktowania (DT.01.01.10) (Model_x0020_kontraktowy_x0020__x) z bieżącego elementu jest równe ATU). (APEX: `Instrukcja IF ... THEN ... ELSIF w PL/SQL lub Exclusive Gateway w Flows for APEX.`)
  <details><summary>Szczegóły techniczne</summary>

  ```
  ConditionUse=Child
  ```
  </details>
    - `[n3]` Warunek: JEŻELI wartość pola Usługa cykliczna? (DT.01.01.33) (DT_x002e_03) z bieżącego elementu jest równe Tak
      > **Wskazówka migracji**: Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: wartość pola Usługa cykliczna? (DT.01.01.33) (DT_x002e_03) z bieżącego elementu jest równe Tak. (APEX: `Instrukcja IF ... THEN ... ELSIF w PL/SQL lub Exclusive Gateway w Flows for APEX.`)
      <details><summary>Szczegóły techniczne</summary>

      ```
      ConditionUse=Child
      ```
      </details>
        - `[n4]` DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34' wartość: Nie.
          > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-01-34'. (APEX: `l_zm_DT_01_01_34 := Nie; lub flow_process.set_var(p_process_id, 'zm_DT-01-01-34', ...);`)
          <details><summary>Szczegóły techniczne</summary>

          ```
          ValueType = Text
          VariableName = 
          Value = Nie
          ```
          </details>
        - `[n5]` Warunek: JEŻELI wartość pola Typ usługi ICT (DT.01.01):Symbol usługi (Typ_x0020_us_x0142_ugi_x0020_ICT0) z bieżącego elementu jest równe eba_TA:S00
          > **Wskazówka migracji**: Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: wartość pola Typ usługi ICT (DT.01.01):Symbol usługi (Typ_x0020_us_x0142_ugi_x0020_ICT0) z bieżącego elementu jest równe eba_TA:S00. (APEX: `Instrukcja IF ... THEN ... ELSIF w PL/SQL lub Exclusive Gateway w Flows for APEX.`)
          <details><summary>Szczegóły techniczne</summary>

          ```
          ConditionUse=Child
          ```
          </details>
            - `[n6]` DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34' wartość: Tak.
              > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-01-34'. (APEX: `l_zm_DT_01_01_34 := Tak; lub flow_process.set_var(p_process_id, 'zm_DT-01-01-34', ...);`)
              <details><summary>Szczegóły techniczne</summary>

              ```
              ValueType = Text
              VariableName = 
              Value = Tak
              ```
              </details>
            - `[n7]` DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34' wartość: Nie.
              > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-01-34'. (APEX: `l_zm_DT_01_01_34 := Nie; lub flow_process.set_var(p_process_id, 'zm_DT-01-01-34', ...);`)
              <details><summary>Szczegóły techniczne</summary>

              ```
              ValueType = Text
              VariableName = 
              Value = Nie
              ```
              </details>
    - `[n8]` DT-01-01-34 Usługa ICT?: Zapisz w zmiennej 'zm_DT-01-01-34' wartość: Nie.
      > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-01-34'. (APEX: `l_zm_DT_01_01_34 := Nie; lub flow_process.set_var(p_process_id, 'zm_DT-01-01-34', ...);`)
      <details><summary>Szczegóły techniczne</summary>

      ```
      ValueType = Text
      VariableName = 
      Value = Nie
      ```
      </details>
- `[n9]` Warunek: JEŻELI {WorkflowVariable:zm_DT-01-01-34} jest równe Tak
  > **Wskazówka migracji**: Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: {WorkflowVariable:zm_DT-01-01-34} jest równe Tak. (APEX: `Instrukcja IF ... THEN ... ELSIF w PL/SQL lub Exclusive Gateway w Flows for APEX.`)
  <details><summary>Szczegóły techniczne</summary>

  ```
  ConditionUse=Child
  ```
  </details>
    - `[n10]` zm_DT-01-01-38: Zapisz w zmiennej 'zm_DT-01-01-38' wartość: Nie.
      > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-01-38'. (APEX: `l_zm_DT_01_01_38 := Nie; lub flow_process.set_var(p_process_id, 'zm_DT-01-01-38', ...);`)
      <details><summary>Szczegóły techniczne</summary>

      ```
      ValueType = Text
      VariableName = 
      Value = Nie
      ```
      </details>
    - `[n11]` Warunek: JEŻELI (wartość pola Usługa krytyczna wg EBA? (DT.01.01.37) (Us_x0142_uga_x0020_krytyczna_x00) z bieżącego elementu jest równe Tak) LUB (wartość pola Czy usługa związana z funkcją krytyczną (DT.01.01.35) (Funkcja_x0020_krytyczna) z bieżącego elementu nie zawiera F0)
      > **Wskazówka migracji**: Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: (wartość pola Usługa krytyczna wg EBA? (DT.01.01.37) (Us_x0142_uga_x0020_krytyczna_x00) z bieżącego elementu jest równe Tak) LUB (wartość pola Czy usługa związana z funkcją krytyczną (DT.01.01.35) (Funkcja_x0020_krytyczna) z bieżącego elementu nie zawiera F0). (APEX: `Instrukcja IF ... THEN ... ELSIF w PL/SQL lub Exclusive Gateway w Flows for APEX.`)
      <details><summary>Szczegóły techniczne</summary>

      ```
      ConditionUse=Child
      ```
      </details>
        - `[n12]` zm_DT-01-01-38: Zapisz w zmiennej 'zm_DT-01-01-38' wartość: Nie.
          > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-01-38'. (APEX: `l_zm_DT_01_01_38 := Nie; lub flow_process.set_var(p_process_id, 'zm_DT-01-01-38', ...);`)
          <details><summary>Szczegóły techniczne</summary>

          ```
          ValueType = Text
          VariableName = 
          Value = Nie
          ```
          </details>
        - `[n13]` zm_DT-01-01-38: Zapisz w zmiennej 'zm_DT-01-01-38' wartość: Tak.
          > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-01-38'. (APEX: `l_zm_DT_01_01_38 := Tak; lub flow_process.set_var(p_process_id, 'zm_DT-01-01-38', ...);`)
          <details><summary>Szczegóły techniczne</summary>

          ```
          ValueType = Text
          VariableName = 
          Value = Tak
          ```
          </details>
        - `[n14]` Warunek: JEŻELI (wartość pola Dostawca (DT.01.01.03) (Dostawca_x0020__x0028_DT_x002e_0) z bieżącego elementu) ORAZ (wartość pola Są inne usł. krytyczne Dostawcy? (DT.01.02.16) (S_x0105__x0020_inne_x0020_us_x01) z bieżącego elementu jest równe Tak)
          > **Wskazówka migracji**: Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: (wartość pola Dostawca (DT.01.01.03) (Dostawca_x0020__x0028_DT_x002e_0) z bieżącego elementu) ORAZ (wartość pola Są inne usł. krytyczne Dostawcy? (DT.01.02.16) (S_x0105__x0020_inne_x0020_us_x01) z bieżącego elementu jest równe Tak). (APEX: `Instrukcja IF ... THEN ... ELSIF w PL/SQL lub Exclusive Gateway w Flows for APEX.`)
          <details><summary>Szczegóły techniczne</summary>

          ```
          ConditionUse=Child
          ```
          </details>
            - `[n15]` zm_DT-01-02-01: Zapisz w zmiennej 'zm_DT-01-02-01' wartość: Tak.
              > **Wskazówka migracji**: Obliczenie/odczyt i zapis do zmiennej lokalnej 'zm_DT-01-02-01'. (APEX: `l_zm_DT_01_02_01 := Tak; lub flow_process.set_var(p_process_id, 'zm_DT-01-02-01', ...);`)
              <details><summary>Szczegóły techniczne</summary>

              ```
              ValueType = Text
              VariableName = 
              Value = Tak
              ```
              </details>
- `[n16]` Zapisz wpis w historii przepływu: „DT-01-01-34 Usługa DORA ICT: {WorkflowVariable:zm_DT-01-01-34}” (…)
  > **Wskazówka migracji**: Zapis audytowy do dziennika zdarzeń (Audit Log). (APEX: `APEX_DEBUG.INFO() lub INSERT INTO t_workflow_history(run_id, item_id, message, created_at);`)
  <details><summary>Szczegóły techniczne</summary>

  ```
  Message = DT-01-01-34 Usługa DORA ICT: {WorkflowVariable:zm_DT-01-01-34}
DT-01-01-38 Usługa DORA ICT Krytyczna: {WorkflowVariable:zm_DT-01-01-38}
DT-01-02-01: Ryzyko koncentracji: {WorkflowVariable:zm_DT-01-02-01}
  ```
  </details>
- `[n17]` Zaktualizuj element w bieżącym elemencie: ustaw pola Usługa ICT wg DORA? (DT.01.01.34) (Us_x0142_uga_x0020_kwalifikowana), Usługa krytyczna wg DORA? (DT.01.01.38) (Us_x0142_uga_x0020_krytyczna_x000), Ryzyko koncentracji? (DT.01.02.01) (Zwi_x0119_kszone_x0020_ryzyko_x0).
  > **Wskazówka migracji**: Aktualizacja danych elementu (Usługa ICT wg DORA? (DT.01.01.34) (Us_x0142_uga_x0020_kwalifikowana), Usługa krytyczna wg DORA? (DT.01.01.38) (Us_x0142_uga_x0020_krytyczna_x000), Ryzyko koncentracji? (DT.01.02.01) (Zwi_x0119_kszone_x0020_ryzyko_x0)). W systemie docelowym UPDATE lub REST PATCH/MERGE. (APEX: `UPDATE tabela SET ... WHERE id = :id; lub REST MERGE z nagłówkiem If-Match (weryfikacja ETag).`)
  <details><summary>Szczegóły techniczne</summary>

  ```
  ListId = {45763939-B649-439D-9A1B-39D6AB430FBF}
  ThisItem = True
  ```
  </details>

## Zmienne przepływu pracy

| Zmienna | Typ | Opis / Rola |
|---|---|---|
| `zm_DT-01-01-34` | Text | DT-01-01-34 Usługa ICT? |
| `zm_DT-01-01-38` | Text | zm_DT-01-01-38 |
| `zm_DT-01-02-01` | Text | zm_DT-01-02-01 |

## Pola odczytywane / zapisywane

| Pole | Odczyt | Zapis |
|---|---|---|
| Telefonia analogowa? (DT.01.01.31) (DT_x002e_01) | X |  |
| Usługa cykliczna? (DT.01.01.33) (DT_x002e_03) | X |  |
| Dostawca (DT.01.01.03) (Dostawca_x0020__x0028_DT_x002e_0) | X |  |
| Czy usługa związana z funkcją krytyczną (DT.01.01.35) (Funkcja_x0020_krytyczna) | X |  |
| Model kontraktowania (DT.01.01.10) (Model_x0020_kontraktowy_x0020__x) | X |  |
| Są inne usł. krytyczne Dostawcy? (DT.01.02.16) (S_x0105__x0020_inne_x0020_us_x01) | X |  |
| Typ usługi ICT (DT.01.01):Symbol usługi (Typ_x0020_us_x0142_ugi_x0020_ICT0) | X |  |
| Usługa krytyczna wg EBA? (DT.01.01.37) (Us_x0142_uga_x0020_krytyczna_x00) | X |  |
| Usługa krytyczna wg DORA? (DT.01.01.38) (Us_x0142_uga_x0020_krytyczna_x000) |  | X |
| Usługa ICT wg DORA? (DT.01.01.34) (Us_x0142_uga_x0020_kwalifikowana) |  | X |
| Ryzyko koncentracji? (DT.01.02.01) (Zwi_x0119_kszone_x0020_ryzyko_x0) |  | X |

### Słownik pól i identyfikatory techniczne

| Nazwa biznesowa | SharePoint InternalName | Typ | Odczyt | Zapis |
|---|---|---|---|---|
| Telefonia analogowa? (DT.01.01.31) | `DT_x002e_01` | Tekst/Ref | Tak | - |
| Usługa cykliczna? (DT.01.01.33) | `DT_x002e_03` | Tekst/Ref | Tak | - |
| Dostawca (DT.01.01.03) | `Dostawca_x0020__x0028_DT_x002e_0` | Tekst/Ref | Tak | - |
| Czy usługa związana z funkcją krytyczną (DT.01.01.35) | `Funkcja_x0020_krytyczna` | Tekst/Ref | Tak | - |
| Model kontraktowania (DT.01.01.10) | `Model_x0020_kontraktowy_x0020__x` | Tekst/Ref | Tak | - |
| Są inne usł. krytyczne Dostawcy? (DT.01.02.16) | `S_x0105__x0020_inne_x0020_us_x01` | Tekst/Ref | Tak | - |
| Typ usługi ICT (DT.01.01):Symbol usługi | `Typ_x0020_us_x0142_ugi_x0020_ICT0` | Tekst/Ref | Tak | - |
| Usługa krytyczna wg EBA? (DT.01.01.37) | `Us_x0142_uga_x0020_krytyczna_x00` | Tekst/Ref | Tak | - |
| Usługa krytyczna wg DORA? (DT.01.01.38) | `Us_x0142_uga_x0020_krytyczna_x000` | Tekst/Ref | - | Tak |
| Usługa ICT wg DORA? (DT.01.01.34) | `Us_x0142_uga_x0020_kwalifikowana` | Tekst/Ref | - | Tak |
| Ryzyko koncentracji? (DT.01.02.01) | `Zwi_x0119_kszone_x0020_ryzyko_x0` | Tekst/Ref | - | Tak |
