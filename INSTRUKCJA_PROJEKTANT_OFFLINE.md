# Instrukcja obsługi: Projektant (prototyp offline)

**Projektant (prototyp offline)** to wizualny edytor grafów automatyzacji dla list SharePoint w aplikacji webowej DORA. Pozwala zbudować algorytm krok po kroku, przetestować go na lokalnym eksporcie danych (**Symulacja offline**) oraz zweryfikować na żywych danych z SharePoint w trybie tylko do odczytu (**Podgląd online (tylko GET)**).

> [!IMPORTANT]
> Projektant jest prototypem bez funkcji zapisu do SharePoint (`write_available=False`). Zarówno symulacja offline, jak i podgląd online oraz lokalne zatwierdzenie w dzienniku **nie modyfikują** żadnych elementów na witrynie SharePoint.

---

## 1. Uruchomienie i przygotowanie danych

1. Uruchom aplikację webową skryptem `run_web_gui.bat` (lub poleceniem `uv run python main_web.py --show`).
2. *(Zalecane przed projektowaniem)* Przejdź do zakładki **3. Automatyzacje** → **Relacje offline**, wskaż folder z eksportem (np. `DaneZeSkryptu_nnn`) i kliknij **Wczytaj**.
   - Wczytanie eksportu zasila listy rozwijane w Projektancie (listy, widoki, pola Lookup) oraz jest **wymagane** do uruchomienia **Symulacji offline**.
3. Przełącz się na podzakładkę **Projektant (prototyp offline)**.

---

## 2. Górny pasek narzędzi i pliki JSON

| Element | Działanie |
|---|---|
| **Nowy graf** | Tworzy pusty graf z węzłem `start`. |
| **Anuluj zmiany** | Przywraca ostatnio wczytaną lub zapisaną definicję (aktywne, gdy widoczny jest status *Niezapisane zmiany*). |
| **Typ węzła** + **Dodaj węzeł** | Dodaje na płótno nowy węzeł wybranego typu. |
| **Symulacja offline** | Uruchamia testowy przebieg grafu na danych z eksportu wczytanego w zakładce *Relacje offline*. |
| **Podgląd online (tylko GET)** | Pobiera świeże dane z SharePoint przez Windows SSO (tylko GET) i wylicza proponowane zmiany. |
| **Ścieżka pliku JSON grafu** | Ścieżka robocza pliku (domyślnie `out_automation/workflow_draft.json`). |
| **Wczytaj JSON** / **Zapisz JSON** | Odczytuje lub zapisuje definicję grafu na dysk. Zapis automatycznie aplikuje niezastosowane zmiany z Inspektora węzła. |

> [!TIP]
> Na dole widoku znajduje się rozwijana sekcja **Podgląd i edycja surowego JSON grafu**, która pozwala podejrzeć lub bezpośrednio zmodyfikować strukturę JSON.

---

## 3. Parametry ogólne algorytmu (nagłówek)

Nad płótnem znajdują się ustawienia całego przepływu:

- **Nazwa algorytmu** — opisowa nazwa reguły.
- **Witryna SharePoint** — adres URL witryny docelowej (wymagany przy podglądzie online).
- **Lista źródłowa** — główna lista, dla której uruchamiany jest algorytm (wybór po nazwie z katalogu automatycznie zapisuje wewnętrzny identyfikator GUID w JSON i zawęża listy rozwijane pól w Inspektorze dla aliasu `source` oraz widoków tej listy; dla aliasów z węzłów `lookup` podpowiedzi pól zawężają się do odpowiedniej listy docelowej). Techniczne pola GUID/`field_id` są ukryte w warstwie wizualnej i zarządzane wyłącznie w definicji JSON.
- **Zakres (scope)**:
  - `Cała lista (all)` — przetwarza wszystkie elementy listy źródłowej.
  - `Wybrane ID (ids)` — przetwarza tylko wskazane ID elementów (wpisz liczby całkowite > 0 oddzielone przecinkiem, spacją lub średnikiem, np. `1, 2, 5`).
  - `Widok listy (view)` — ogranicza elementy do wybranego **Widoku listy** (obsługiwane w podglądzie online dla zweryfikowanego podzbioru filtrów CAML; symulacja offline odrzuca zakres widoku).
- **Limit aktualizacji (max_updates)** — maksymalna liczba proponowanych zmian (`0 = bez limitu`).

---

## 4. Praca na płótnie grafu

Płótno po lewej stronie prezentuje węzły i połączenia między nimi:

- **Przesuwanie węzła**: chwyć węzeł lewym przyciskiem myszy i przeciągnij w nowe miejsce (pozycje zapisują się w sekcji `layout` pliku JSON).
- **Wybór węzła**: kliknij węzeł, aby otworzyć jego parametry w panelu **Inspektor węzła** po prawej stronie.
- **Tworzenie połączenia**:
  1. Kliknij port wyjściowy (**●** po prawej stronie węzła źródłowego). Węzeł `Warunek` posiada dwa porty wyjściowe: **true** oraz **false**; węzły `Pomiń` i `Koniec` nie mają portów wyjściowych.
  2. Kliknij węzeł docelowy (lub jego port wejściowy **●** po lewej stronie). Węzeł `Start` nie ma portu wejściowego.
- **Usuwanie połączenia**: kliknij bezpośrednio na linię (krawędź) łączącą dwa węzły.

---

## 5. Typy węzłów i Inspektor węzła

Po kliknięciu węzła edytuj jego właściwości po prawej stronie i zatwierdź przyciskiem **Zastosuj** (przycisk **Usuń węzeł** usuwa zaznaczony węzeł poza węzłem `start`).

### Dostępne typy węzłów

1. **Start (`start`)** — punkt wejścia przepływu; udostępnia bieżący element listy źródłowej pod domyślnym aliasem `source`.
2. **Odczyt relacji (`lookup`)** — pobiera powiązany element (lub kolekcję) z innej listy:
   - **Z aliasu (from)** — alias źródłowy (np. `source`).
   - **Pole Lookup z katalogu** — pole relacji łączące listy (techniczny identyfikator `field_id` jest ukryty w UI i zapisywany w JSON).
   - **Jako alias (as)** — nazwa aliasu, pod którym wynik będzie dostępny w kolejnych krokach.
   - **Kierunek relacji**: `W przód (forward)` lub `Odwrotny (reverse)`.
   - **Kolekcja (many)** — zaznacz, gdy relacja może zwrócić wiele elementów.
   - **Lista docelowa (odwrotne)** — wymagane przy relacjach odwrotnych (wybór po nazwie listy z katalogu).
3. **Warunek (`condition`)** — rozgałęzia przepływ na ścieżki **true** i **false**:
   - **Wspólne scalenie (merge)** — opcjonalny węzeł scalenia powiązany z warunkiem.
   - **Operator** / **Alias** oraz czytelny podgląd warunku (surowy JSON warunku znajduje się w zwiniętej sekcji technicznej).
   - **Konstruktor warunku (drzewo)...** — otwiera wizualny edytor drzewa warunków:
     - Po lewej stronie wyświetla strukturę warunku, po prawej jego operator (`and`, `or`, `not`, `any`, `all`, `exists`, `empty`, `not_empty`, `eq`, `ne`, `lt`, `le`, `gt`, `ge`) oraz wyrażenia lewej i prawej strony.
     - Przyciski **Zastąp zaznaczony warunek**, **Dodaj warunek do AND / OR** oraz **Usuń wybrany warunek** pozwalają budować złożone reguły bez ręcznego pisania JSON.
     - Dla `any`/`all` element kolekcji jest wiązany pod aliasem `item`.
4. **Ustaw pole (`assign`)** — rejestruje proponowaną zmianę wartości pola:
   - **Alias docelowy** — alias rekordu do zmiany (zazwyczaj `source`).
   - **Pole docelowe z katalogu** — wybór pola po nazwie z listy (filtrowanej wg aliasu docelowego; techniczne `field_id` pozostaje ukryte).
   - **Konstruktor wartości**:
     - `Stała (literal)` — wpisz wartość w formacie JSON (np. `"Gotowe"`, `123`, `true`, `null`).
     - `Wartość pola (field)` — odczytuje wartość wskazanego pola z podanego aliasu.
     - `Liczba elementów (count)` — zlicza elementy w kolekcji pod wskazanym aliasem.
5. **Scalenie (`merge`)** — łączy ponownie rozgałęzione ścieżki przepływu.
6. **Pomiń (`skip`)** — kończy ścieżkę bez proponowania zmian.
7. **Koniec (`end`)** — jawnie kończy ścieżkę przepływu.

### Jak interpretować opisy pól w listach rozwijanych

Pola na listach rozwijanych są wyświetlane w formacie:

`Nazwa wyświetlana [NazwaWewnętrzna] (Typ)`

Na przykładzie `Symbol kategorii [LinkTitleNoMenu] (Computed)`:

1. **`Symbol kategorii`** — nazwa wyświetlana kolumny w SharePoint (`Title` kolumny, widoczna dla użytkowników w widokach i formularzach).
2. **`[LinkTitleNoMenu]`** — techniczna nazwa wewnętrzna kolumny w SharePoint (`InternalName`), niezmienna mimo zmiany nazwy wyświetlanej. Pozwala odróżnić różne kolumny SharePoint, które mają identyczną nazwę wyświetlaną.
3. **`(Computed)`** — typ kolumny w SharePoint (`TypeAsString`).

> [!TIP]
> **Filtrowanie kontekstowe list pól**:
> Projektant automatycznie ukrywa pola, których nie da się użyć w danej operacji:
> - **Ustaw pole (`assign`) → Pole docelowe**: pokazuje wyłącznie pola zapisywalne (bez `Computed`, `Calculated`, `Counter`, `User`, `LookupMulti`, pól systemowych i pól tylko do odczytu).
> - **Ustaw pole → Konstruktor wartości (`Wartość pola`)**: po wyborze pola docelowego zawęża listę do pól o zgodnym typie (np. `Text` do `Text`, `Number`/`Currency`, lub `Lookup` wskazujący na tę samą listę docelową).
> - **Odczyt relacji (`lookup`)**: pokazuje wyłącznie realne pola relacji `Lookup`/`LookupMulti` (bez pól zależnych i kolumn użytkowników). W trybie odwrotnym (`reverse`) lista docelowa zawęża się do list posiadających relację powrotną do listy źródłowej.
> - **Warunek (`condition`)**: pokazuje wyłącznie obsługiwane pola do odczytu (bez `Computed`, `Calculated`, `Counter`, `User`, pól ukrytych i zależnych).

> [!TIP]
> **Uwaga na duplikaty z dopiskiem `(Computed)` (np. `[LinkTitle]`, `[LinkTitleNoMenu]`)**:
> SharePoint automatycznie tworzy dla kolumny tytułowej (`[Title]`) dodatkowe pola pomocnicze do renderowania linków w widokach list (`LinkTitle`, `LinkTitleNoMenu` typu `Computed`), które dziedziczą jej nazwę wyświetlaną (np. *Symbol kategorii*). Nie są to jednak prawdziwe pola danych do odczytu/zapisu w logice przepływu.
> W warunkach oraz w węźle **Ustaw pole (`assign`)** wybieraj właściwą kolumnę danych, np. `Symbol kategorii [Title] (Text)`, a nie `Symbol kategorii [LinkTitleNoMenu] (Computed)`.

#### Najczęstsze typy pól `(Typ)`

| Typ w nawiasie | Znaczenie | Użycie w Projektancie |
|---|---|---|
| `Text`, `Note`, `Choice`, `Number`, `Currency`, `Boolean`, `DateTime` | Standardowe kolumny danych | Obsługiwane do odczytu i zapisu (o ile pole nie jest systemowe lub tylko do odczytu). |
| `Lookup`, `LookupMulti` | Pole relacji do innej listy (pojedyncze / wielokrotne) | Obsługiwane w węzłach `Odczyt relacji (lookup)`, warunkach i `Ustaw pole`. |
| `Computed` | Kolumna pomocnicza widoku SharePoint (np. `LinkTitle`, `LinkTitleNoMenu`, `Edit`) | Nie używaj jako kolumny danych — nie nadaje się do zapisu ani porównań wartości. |
| `Calculated` | Kolumna wyliczana ze wzoru SharePoint | Tylko podgląd/informacja; nieobsługiwana do zapisu w `Ustaw pole`. |
| `Counter` | Systemowy identyfikator rekordu (`ID`) | Pole systemowe tylko do odczytu (używane do identyfikacji elementów i relacji). |
| `User`, `UserMulti`, `Attachments` | Użytkownicy / załączniki SharePoint | Nieobsługiwane jako docelowe pola zapisu w obecnym prototypie. |

---

## 6. Testowanie i podgląd wyników

### Symulacja offline
- Wymaga wcześniejszego wczytania eksportu w **Relacje offline**.
- Po kliknięciu **Symulacja offline** otwiera się okno z dwiema zakładkami:
  - **Proponowane zmiany** — tabela wynikowa (*Lista*, *Element*, *Pole*, *Wartość przed*, *Proponowana wartość*, *Elementy źródłowe*, *Kroki*).
  - **Przebieg krok po kroku** — szczegółowy ślad wykonania grafu dla każdego elementu (*Element*, *Krok*, *Węzeł*, *Użyte zmienne i wartości*, *Wynik kroku*, *Wyjście*) z polem filtrowania, pozwalający prześledzić dokładne wartości pól/zmiennych i decyzje na rozgałęzieniach.
- Wynik ma charakter orientacyjny — bazuje na historycznym eksporcie i nie stosuje filtrów widoków.

### Podgląd online (tylko GET) i dziennik zatwierdzeń
1. Kliknij **Podgląd online (tylko GET)** — aplikacja wykona świeży odczyt wymaganych list i pól z SharePoint (przez Windows SSO, z kontrolą stronicowania i ETag).
2. W oknie wyników możesz kliknąć **Zapisz w dzienniku**, aby utrwalić podgląd w lokalnej bazie SQLite (`out_automation/journal.sqlite`).
3. Jeśli podgląd wykazał zmiany (`> 0`) i został zapisany w dzienniku, aktywuje się przycisk **Zatwierdź (ponowny odczyt GET)...**:
   - Wymaga przepisania dokładnej frazy potwierdzenia (`ZATWIERDZAM <run_id>`).
   - Ponownie odczytuje dane z SharePoint (GET), weryfikuje brak rozbieżności (graf, dane, zakres, ETag) i zapisuje zgodę **wyłącznie w lokalnym dzienniku SQLite**.
