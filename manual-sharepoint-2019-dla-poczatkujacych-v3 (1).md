# Manual: jak „zdjąć” witrynę SharePoint 2019, żeby odtworzyć ją gdzie indziej

### Wersja 3 (2026‑09‑10) — uwzględnia odpowiedzi adminów i poprawkę na okienka logowania; dla osoby, która nie pracuje na co dzień w SharePoint, tylko przez przeglądarkę

---

## Część A — Najpierw zrozum, z czym masz do czynienia

### A1. Słowniczek (10 minut, warto)

| Termin                                    | Co to jest po ludzku                                                                                                                                                  | Odpowiednik w świecie baz danych / APEX                 |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| **Kolekcja witryn** (site collection)     | „Kontener” najwyższego poziomu, np. `http://sp/sites/dora`. Ma jednego głównego administratora.                                                                       | Schemat bazy                                            |
| **Witryna** (site / web)                  | Strona z listami, bibliotekami i podwitrynami. Kolekcja ma witrynę główną i może mieć podwitryny.                                                                     | Podschemat / moduł aplikacji                            |
| **Lista**                                 | Tabela z kolumnami i wierszami (tu: „elementami”). Serce SharePointa.                                                                                                 | Tabela                                                  |
| **Biblioteka dokumentów**                 | Lista, której wiersze to pliki (+ ich kolumny).                                                                                                                       | Tabela z BLOB‑ami                                       |
| **Element** (item)                        | Wiersz listy.                                                                                                                                                         | Rekord                                                  |
| **Kolumna** (column / field)              | Kolumna listy. Ma typ: tekst, liczba, data, wybór, **odnośnik (lookup)**, **osoba**, **obliczeniowa**.                                                                | Kolumna; lookup = klucz obcy; osoba = FK do użytkownika |
| **Nazwa wewnętrzna** (InternalName)       | Techniczna nazwa kolumny (np. `Data_x0020_wpisu`). Różna od wyświetlanej.                                                                                             | Nazwa fizyczna kolumny                                  |
| **GUID**                                  | Identyfikator typu `{3F2A…}`. Listy, kolumny, widoki mają GUID‑y; workflow odwołują się do nich zamiast do nazw.                                                      | ID/OID                                                  |
| **Widok** (view)                          | Zapisany sposób pokazania listy: które kolumny, filtr, sortowanie, grupowanie. Widoki często pełnią rolę „raportów”.                                                  | View / zapytanie                                        |
| **Typ zawartości** (content type)         | Szablon „rodzaju elementu” — zestaw kolumn + formularze. Lista może mieć kilka typów (np. „Incydent” i „Zmiana”).                                                     | Podtyp encji                                            |
| **Kolumna witryny** (site column)         | Kolumna zdefiniowana na poziomie witryny, wielokrotnie użyta w listach.                                                                                               | Domena / typ współdzielony                              |
| **Uprawnienia, grupy, poziomy uprawnień** | Kto co może. Grupy (np. „Członkowie”) mają poziom (np. „Współtworzenie”). Uprawnienia można nadpisać na liście, folderze i pojedynczym elemencie.                     | Role/grants, RLS                                        |
| **Workflow (Nintex)**                     | Zautomatyzowany proces: „gdy dodano element → wyślij mail → czekaj na akceptację → zaktualizuj pole”. Nintex to dodatek, który daje graficzny edytor takich procesów. | Procedury + kolejka zadań + maile                       |
| **Formularz**                             | Ekran dodawania/edycji elementu. Standardowy, albo zbudowany w **Nintex Forms** lub **InfoPath** (mogą zawierać reguły!).                                             | Strona formularza                                       |
| **Funkcja** (feature)                     | Włączany „pakiet” funkcjonalności na witrynie/kolekcji.                                                                                                               | Plugin                                                  |
| **Rozwiązanie** (solution, `.wsp`)        | Paczka kodu/konfiguracji wdrożona przez administratora.                                                                                                               | Deployment package                                      |
| **Metadane zarządzane / term store**      | Centralne słowniki (drzewo terminów) używane w kolumnach.                                                                                                             | Tabele słownikowe                                       |
| **REST API**                              | Adresy `…/_api/…`, które po wpisaniu w przeglądarkę zwracają dane w XML/JSON.                                                                                         | SELECT z bazy                                           |
| **Konsola DevTools**                      | Okno programisty w przeglądarce (F12 → zakładka Console). Można tam wkleić skrypt, który w Twojej sesji wykona setki zapytań i pobierze wyniki jako pliki.            | SQL\*Plus w przeglądarce                                |

### A2. Gdzie ukrywa się „funkcjonalność” w SharePoint

To najważniejszy akapit. Logika biznesowa w SharePoint **nie siedzi w jednym miejscu**. Jest rozsypana w siedmiu warstwach — każdą trzeba wyciągnąć osobno:

1. **Struktura list** — kolumny, typy, wymagalność, relacje (lookupy).
2. **Reguły w kolumnach** — formuły kolumn obliczeniowych, formuły walidacji, wartości domyślne.
3. **Widoki** — filtry/sortowania/grupowania = gotowe raporty.
4. **Workflow (Nintex)** — cały proces: kto zatwierdza, kiedy idą maile, co się aktualizuje.
5. **Formularze** — reguły widoczności pól, walidacje, wyliczenia (Nintex Forms / InfoPath / JS).
6. **Uprawnienia** — kto co widzi i może zrobić, także na poziomie pojedynczych wierszy.
7. **Strony i skrypty** — przyciski, JavaScript wstrzyknięty do stron, dostosowania wstążki.
8. **Integracje zewnętrzne** — listy zewnętrzne (BCS), wywołania usług i zapytania SQL z workflow, dane z Excela/wyszukiwania (u Ciebie potwierdzone — patrz Krok 11).

Do tego **dane**: elementy list, załączniki, dokumenty, historia wersji, historia wykonania procesów.

### A3. Zasady pracy

- Niczego nie zmieniaj w witrynie źródłowej. Wszystko, co niżej, jest odczytem (wyjątek: zapis szablonu witryny tworzy jeden plik w galerii — nieszkodliwe).
- Załóż folder np. `SP_export\<nazwa witryny>\` z podfolderami:
  `00_witryna`, `10_listy_definicje`, `20_dane`, `30_uprawnienia`, `40_workflow`, `50_formularze`, `60_strony_ui`, `90_notatki`.
  Wrzuć to do Git — masz wersjonowany artefakt audytowy.
- Każdy zapisany plik nazywaj z datą, np. `10_lista_Incydenty_2026-09-09.json`.
- Prowadź plik `90_notatki\GUID_slownik.csv`: `GUID; typ (lista/kolumna/widok/grupa); nazwa`. Będziesz go potrzebował przy czytaniu workflow.

---

## Część B — Przygotowanie warsztatu (raz)

### B1. Sprawdź, co masz

1. Wejdź na witrynę. Kliknij ikonę koła zębatego (prawy górny róg) → **Ustawienia witryny** (Site settings). Jeśli widzisz sekcje „Użytkownicy i uprawnienia”, „Galerie projektanta stron sieci Web”, „Administracja witryną”, „Nintex Workflow” — masz uprawnienia właściciela. Dobrze.
2. Zapisz sobie adres witryny, np. `http://sp.bank.local/sites/dora`. Dalej nazywam go **ADRES**.
3. Wpisz w przeglądarce: `ADRES/_api/web` → powinieneś zobaczyć XML z tytułem witryny. Jeśli tak, REST działa i większość manuala jest do wykonania.
4. Wpisz: `ADRES/_layouts/15/viewlsts.aspx` → to strona **Zawartość witryny**: lista wszystkich list, bibliotek i podwitryn. Zrób jej screenshot — to Twoja mapa.

### B2. Naucz się jednego chwytu: konsola przeglądarki

1. Będąc na dowolnej stronie witryny, wciśnij **F12** → zakładka **Console** (Konsola).
2. Wklej poniższy blok i wciśnij Enter. Nic się nie stanie — to tylko definicje pomocników. **Wklejaj go na początku każdej sesji** (po odświeżeniu strony znika).

```javascript
// --- POMOCNICY (v3) ---
const host = location.origin; // ten sam host, na którym jesteś zalogowany
const sameHost = (u) => u.replace(/^https?:\/\/[^/]+/, host); // przepisuje inny host na bieżący
const base = host + _spPageContextInfo.webServerRelativeUrl.replace(/\/$/, "");
const site = host + _spPageContextInfo.siteServerRelativeUrl.replace(/\/$/, "");
const opt = {
  credentials: "include",
  headers: { Accept: "application/json;odata=nometadata" },
};
const get = async (u) => {
  const r = await fetch(sameHost(u), opt);
  const j = await r.json();
  if (!r.ok || j["odata.error"])
    throw new Error(
      j["odata.error"]?.message?.value || "HTTP " + r.status + " " + u,
    );
  return j;
};
const getAll = async (u) => {
  let out = [];
  while (u) {
    const r = await get(u);
    out.push(...(r.value || []));
    u = r["odata.nextLink"];
  }
  return out;
};
const dl = (name, data) => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(
    new Blob([typeof data === "string" ? data : JSON.stringify(data, null, 1)]),
  );
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
};
const safe = (s) => (s || "").replace(/[^\w.-]+/g, "_") || "bez_nazwy";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
console.log("base =", base, "| site =", site);
```

3. Test: wklej `dl('test.json', await get(base + '/_api/web'))` → przeglądarka pobierze plik `test.json`. Przy pierwszym skrypcie pobierającym wiele plików przeglądarka zapyta „Ta witryna próbuje pobrać wiele plików” — kliknij **Zezwól** (Edge/Chrome: ikona w pasku adresu lub Ustawienia → Uprawnienia witryny → Automatyczne pobieranie).

### B2a. Okienka z loginem i hasłem przy każdym zapytaniu

Jeśli podczas skryptu wyskakuje okno logowania (nawet kilkanaście razy), przyczyna jest jedna z dwóch:

- **Zapytania idą pod inny host niż ten, na którym jesteś zalogowany.** SharePoint zna witrynę np. jako `http://sp.bank.local/…`, a Ty masz otwartą kartę `http://sp/…`. Dla przeglądarki to dwa różne serwery, więc nie dokłada poświadczeń. Pomocnicy v3 rozwiązują to na stałe: `base`, `site` i `sameHost()` zawsze używają hosta z paska adresu, a `credentials:'include'` każe dołączać poświadczenia.
- **Host nie jest w strefie „Lokalny intranet”**, więc Windows nie loguje automatycznie. Każde nowe połączenie HTTP dostaje osobne pytanie (uwierzytelnianie NTLM działa per połączenie — stąd wiele okienek). Rozwiązanie: Panel sterowania → **Opcje internetowe** → Zabezpieczenia → **Lokalny intranet** → Witryny → Zaawansowane → dodaj `http://sp` i `http://sp.bank.local` (Edge i Chrome czytają te ustawienia). Jeśli pole jest wyszarzone przez politykę banku — poproś IT o dopisanie hosta do polityki `AuthServerAllowlist` (Edge/Chrome).

Zasada praktyczna: **otwieraj witrynę pod tym adresem, pod którym samo wejście na stronę nie pyta o hasło**, i dopiero na tej karcie uruchamiaj konsolę. Jeśli mimo wszystko pojawi się jedno okienko — wpisz dane, zaznacz „Zapamiętaj”, i kolejne zapytania pójdą już bez pytania.

Adminowie potwierdzili, że konsola, REST i usługi `_vti_bin` są dostępne. Gdyby mimo to coś zablokowało pobieranie, wszystko da się zrobić ręcznie, wpisując adresy `_api` w pasek — tylko wolniej.

### B3. Jak czytać wynik z `_api` bez konsoli

Wpisanie adresu `_api/...` w pasek daje XML (w pasku adresu używaj tego samego hosta, co przy logowaniu — inaczej znów pojawi się okienko). Czytelniej jest w JSON — w Chrome/Edge zainstaluj rozszerzenie typu „JSON Viewer”, albo używaj konsoli. Wszystkie adresy z tego manuala można wpisać ręcznie, zastępując `${base}` przez ADRES i `guid'…'` przez GUID listy.

Jak znaleźć GUID listy ręcznie: wejdź na listę → koło zębate → **Ustawienia listy**; w adresie strony jest `List=%7B3F2A…%7D` — `%7B` i `%7D` to `{` i `}`; środek to GUID.

---

## Część C — Krok po kroku: struktura i logika

### Krok 1. Zrzut witryny i podwitryn (folder `00_witryna`)

W konsoli (po wklejeniu pomocników z B2):

```javascript
async function walk(url, acc = []) {
  acc.push(
    await get(
      url +
        "/_api/web?$select=Title,Url,ServerRelativeUrl,WebTemplate,Created,LastItemModifiedDate,HasUniqueRoleAssignments",
    ),
  );
  const subs = await get(url + "/_api/web/webs?$select=Url");
  for (const w of subs.value) await walk(sameHost(w.Url), acc);
  return acc;
}
dl("00_witryny.json", await walk(site));
dl("00_wlasciwosci.json", await get(base + "/_api/web?$select=*"));
dl("00_propertybag.json", await get(base + "/_api/web/allproperties"));
dl("00_regionalne.json", await get(base + "/_api/web/regionalsettings"));
dl(
  "00_funkcje_witryny.json",
  await getAll(base + "/_api/web/features?$select=DisplayName,DefinitionId"),
);
dl(
  "00_funkcje_kolekcji.json",
  await getAll(base + "/_api/site/features?$select=DisplayName,DefinitionId"),
);
dl(
  "00_nawigacja_lewa.json",
  await getAll(base + "/_api/web/navigation/quicklaunch"),
);
dl(
  "00_nawigacja_gorna.json",
  await getAll(base + "/_api/web/navigation/topnavigationbar"),
);
dl(
  "00_kolumny_witryny.json",
  await getAll(base + "/_api/web/fields?$select=*&$filter=Hidden eq false"),
);
dl(
  "00_typy_zawartosci_witryny.json",
  await getAll(
    base +
      "/_api/web/contenttypes?$expand=Fields&$select=Name,Id,Group,Description,Fields/InternalName,Fields/Title,Fields/TypeAsString,Fields/Required",
  ),
);
```

Co z tego wynika: lista podwitryn (każdą trzeba przejść osobno — **powtórz Kroki 1–7 na każdej podwitrynie**, wchodząc na nią i wklejając pomocniki od nowa), strefa czasowa i format dat (ważne przy przenoszeniu dat), włączone funkcje (podpowiadają, czy jest Publishing, Nintex, metadane zarządzane).

Dodatkowo ręcznie: Ustawienia witryny → zrób screenshoty stron **Funkcje witryny**, **Funkcje kolekcji witryn**, **Typy zawartości witryny**, **Kolumny witryny**.

### Krok 2. Definicje wszystkich list (folder `10_listy_definicje`)

To najważniejszy krok — daje model danych i połowę logiki.

```javascript
const lists = await getAll(`${base}/_api/web/lists?$select=*`);
dl("10_00_wszystkie_listy.json", lists);
const wszystkieDefinicje = [];
for (const l of lists) {
  const g = `${base}/_api/web/lists(guid'${l.Id}')`;
  try {
    const def = {
      lista: l,
      schemaXml: (await get(`${g}?$select=SchemaXml`)).SchemaXml,
      kolumny: await getAll(`${g}/fields?$select=*`),
      typyZawartosci: await getAll(`${g}/contenttypes?$expand=Fields`),
      widoki: await getAll(`${g}/views?$select=*`),
      formularze: await getAll(`${g}/forms`),
      eventReceivers: await getAll(`${g}/eventreceivers`),
      workflowy: await getAll(`${g}/workflowassociations`),
    };
    for (const v of def.widoki) {
      try {
        v.KolumnyWidoku = (
          await get(`${g}/views(guid'${v.Id}')/viewfields`)
        ).Items;
      } catch (e) {
        v.KolumnyWidoku = "błąd: " + e.message;
      }
    }
    wszystkieDefinicje.push(def);
    dl(`10_lista_${safe(l.Title)}.json`, def);
    await sleep(300); // odstęp, żeby przeglądarka nadążyła z zapisem
  } catch (e) {
    console.warn("Pominięto listę", l.Title, e.message);
  }
}
dl("10_01_wszystkie_definicje.json", wszystkieDefinicje); // kopia zbiorcza w jednym pliku
```

Skrypt jest odporny na błędy: lista, której nie da się odczytać, trafia do konsoli jako ostrzeżenie, a reszta idzie dalej. Na końcu masz też jeden zbiorczy plik — gdyby przeglądarka zablokowała część pojedynczych pobrań.

Pobierze się jeden plik JSON na listę (także listy ukryte — nie kasuj ich, tam są historie workflow). W każdym pliku szukaj:

| Sekcja           | Pole                                                       | Co oznacza dla odtworzenia                                                                                                                                                           |
| ---------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `lista`          | `BaseTemplate`                                             | 100 = zwykła lista, 101 = biblioteka dokumentów, 107 = zadania, 106 = kalendarz, 600 = lista zewnętrzna (dane z innego systemu!)                                                     |
|                  | `ItemCount`                                                | ile wierszy                                                                                                                                                                          |
|                  | `EnableVersioning`, `MajorVersionLimit`                    | czy trzymana jest historia zmian                                                                                                                                                     |
|                  | `EnableModeration`                                         | włączone **zatwierdzanie zawartości** (element ma status oczekujący/zatwierdzony)                                                                                                    |
|                  | `ReadSecurity`/`WriteSecurity` = 2                         | użytkownik widzi/edytuje **tylko własne** elementy — reguła bezpieczeństwa wierszowego                                                                                               |
|                  | `ValidationFormula`                                        | reguła walidacji całego wiersza                                                                                                                                                      |
|                  | `HasUniqueRoleAssignments` = true                          | lista ma własne uprawnienia (patrz Krok 6)                                                                                                                                           |
| `kolumny`        | `Title` / `InternalName`                                   | nazwa wyświetlana / techniczna                                                                                                                                                       |
|                  | `TypeAsString`                                             | typ: `Text`, `Note`, `Number`, `DateTime`, `Choice`, `MultiChoice`, `Lookup`, `LookupMulti`, `User`, `UserMulti`, `Calculated`, `Boolean`, `TaxonomyFieldType` (metadane zarządzane) |
|                  | `Required`, `EnforceUniqueValues`, `Indexed`               | NOT NULL, UNIQUE, indeks                                                                                                                                                             |
|                  | `Choices`                                                  | lista wartości do wyboru                                                                                                                                                             |
|                  | `LookupList` + `LookupField`                               | GUID listy, na którą wskazuje odnośnik = **klucz obcy**                                                                                                                              |
|                  | `RelationshipDeleteBehavior`                               | Cascade/Restrict przy usunięciu rodzica                                                                                                                                              |
|                  | `Formula`                                                  | **formuła kolumny obliczeniowej** — logika!                                                                                                                                          |
|                  | `ValidationFormula` + `ValidationMessage`                  | walidacja pola — logika!                                                                                                                                                             |
|                  | `DefaultValue` / `DefaultFormula`                          | wartość domyślna — logika!                                                                                                                                                           |
|                  | `Hidden`, `ShowInNewForm`, `ShowInEditForm`                | czy pole jest widoczne / edytowalne w formularzu                                                                                                                                     |
|                  | `JSLink`                                                   | dołączony skrypt JS — dostosowanie (patrz Krok 7)                                                                                                                                    |
| `widoki`         | `Title`, `ViewQuery`, `KolumnyWidoku`, `DefaultView`       | `ViewQuery` to filtr/sortowanie/grupowanie w XML (CAML). Każdy widok = raport do odtworzenia                                                                                         |
| `formularze`     | `ServerRelativeUrl`                                        | jeśli adres jest inny niż standardowe `NewForm.aspx`/`EditForm.aspx`/`DispForm.aspx` w folderze listy — formularz jest niestandardowy (Krok 5)                                       |
| `eventReceivers` | `ReceiverAssembly`, `ReceiverClass`, `EventType`           | kod .NET przy dodaniu/zmianie elementu. Adminowie potwierdzili brak kodu niestandardowego — spodziewaj się pustej listy; jeśli coś tu jest, zapytaj ponownie                         |
| `workflowy`      | `Name`, `Enabled`, `AutoStartCreate/Change`, `AllowManual` | jakie procesy są przypięte do listy i kiedy startują                                                                                                                                 |

Na koniec zaktualizuj `GUID_slownik.csv`: dla każdej listy jej `Id` i `Title`; dla każdej kolumny lookup — `LookupList` i nazwa listy docelowej.

Uzupełnienie ręczne (screenshoty): dla każdej listy → **Ustawienia listy** (cała strona), a na niej linki: _Ustawienia wersji_, _Ustawienia zaawansowane_, _Ustawienia sprawdzania poprawności_, _Kolumny indeksowane_, _Ustawienia formularza_, _Ustawienia przepływu pracy_.

### Krok 3. Zapis witryny jako szablonu — POMIŃ

W Twoich witrynach jest aktywna funkcja Publishing, która blokuje „Zapisz witrynę jako szablon”. Nie tracisz nic istotnego: pełne definicje list masz w plikach z Kroku 2 (`schemaXml`), a strony i skrypty zbierzesz w Kroku 7. Numeracja kroków zostaje, żeby lista kontrolna się zgadzała.

### Krok 4. Workflow Nintex (folder `40_workflow`)

**4a. Inwentaryzacja.** Ustawienia witryny → sekcja **Nintex Workflow** → **Workflow inventory** (Spis przepływów pracy). Zobaczysz tabelę: nazwa workflow, lista, typ, wersja, autor. Kliknij eksport do CSV. Zrób to także z poziomu kolekcji (jeśli jest przełącznik zakresu).

**4b. Eksport definicji każdego workflow do pliku `.nwf`** (to plik XML z całą logiką — nie musisz klikać w akcje).

Masz dwie równoległe drogi — wybierz jedną lub obie (dobrze mieć kopię z dwóch źródeł):

_Droga A — przez adminów (najszybsza)._ Poproś o pliki wymienione w Części F pkt 7: wynik `FindWorkflows`, eksport `.nwf` każdego workflow skryptem serwerowym i eksport stałych. Dostaniesz komplet w jednym dniu.

_Droga B — samodzielnie z konsoli (usługi Nintex są u Ciebie dostępne):_

```javascript
async function exportNwf(nazwaWorkflow, nazwaListy, typ = "list") {
  const soap = `<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ExportWorkflow xmlns="http://nintex.com">
  <workflowName>${nazwaWorkflow}</workflowName>
  <listName>${nazwaListy}</listName>
  <workflowType>${typ}</workflowType>
</ExportWorkflow></soap:Body></soap:Envelope>`;
  const r = await fetch(`${base}/_vti_bin/NintexWorkflow/Workflow.asmx`, {
    method: "POST",
    body: soap,
    credentials: "include",
    headers: {
      "Content-Type": "text/xml; charset=utf-8",
      SOAPAction: "http://nintex.com/ExportWorkflow",
    },
  });
  const txt = await r.text();
  if (!r.ok) {
    console.warn("Błąd", r.status, nazwaWorkflow, txt.slice(0, 300));
    return;
  }
  const node = new DOMParser()
    .parseFromString(txt, "text/xml")
    .getElementsByTagName("ExportWorkflowResult")[0];
  if (!node || !node.textContent) {
    console.warn("Pusta odpowiedź dla", nazwaWorkflow, txt.slice(0, 300));
    return;
  }
  dl(`40_${safe(nazwaListy)}__${safe(nazwaWorkflow)}.nwf`, node.textContent);
}
// masowo, z listy nazw (nazwy z CSV z 4a):
// for (const [wf, lista] of [['Akceptacja incydentu','Incydenty'], ['Przegląd roczny','Rejestr']]) { await exportNwf(wf, lista); await sleep(500); }
// przykład: await exportNwf('Akceptacja incydentu', 'Incydenty');
// workflow witryny (bez listy): await exportNwf('Nazwa', '', 'site');
// wielokrotnego użytku: typ 'reusable' lub 'globallyreusable'
```

Nazwy workflow i list bierzesz z CSV z 4a (nazwa listy = tytuł wyświetlany). Jeśli w treści błędu jest mowa o nieznanym typie, spróbuj `'List'`/`'Site'` z wielkiej litery — zależy od wersji Nintex. Jeśli dostajesz błąd 401/403/404 — usługa jest wyłączona; wtedy sposób ręczny: wejdź na listę → wstążka **Lista** → **Nintex Workflow** → **Manage workflows** → otwórz workflow → na wstążce projektanta przycisk **Export** → zapisuje `.nwf`. Przy okazji kliknij **Print** → zapisz jako PDF (rozwinięty diagram z wszystkimi akcjami).

**4c. Ustawienia procesu, których nie ma w `.nwf`** (screenshoty/kopie):

- na liście: wstążka Lista → **Ustawienia przepływu pracy** — które workflow startują automatycznie przy dodaniu/edycji, warunki startu;
- Ustawienia witryny → Nintex Workflow → **Manage workflow constants** (stałe: adresy e‑mail, konta techniczne, adresy usług) — skopiuj tabelę; hasła nie są widoczne. Pełny eksport (także stałych z poziomu farmy) dostaniesz od adminów: `NWAdmin.exe -o ExportWorkflowConstants -siteUrl ADRES -outputFile stale.xml`;
- Ustawienia witryny → Nintex Workflow → **Scheduled workflows** (procesy uruchamiane harmonogramem);
- Ustawienia witryny → Nintex Workflow → **LazyApproval settings** (odpowiadanie na zadania mailem).

**4d. Dane wykonań** (kto, kiedy, jaki wynik): są w ukrytych listach `NintexWorkflowHistory`, `Workflow History`, `Workflow Tasks` — pobierz je w Kroku 8 jak każdą inną listę (już są w plikach z Kroku 2).

**4e. Workflow inne niż Nintex.** Jeśli w `workflowy` w Kroku 2 są procesy, których nie ma w spisie Nintex, to workflow SharePoint Designer. Ich definicje leżą w ukrytej bibliotece `Workflows`: `ADRES/Workflows/<nazwa>/<nazwa>.xoml` i `.xoml.rules` — pobierz przez `ADRES/_api/web/getfilebyserverrelativeurl('/sites/xxx/Workflows/<nazwa>/<nazwa>.xoml')/$value`.

### Krok 5. Formularze (folder `50_formularze`)

Jak rozpoznać rodzaj: wejdź na listę → kliknij **Nowy element**.

| Wygląd                                                                  | Rodzaj           | Co zrobić                                                                                                                                                                                                                 |
| ----------------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prosty formularz „pole pod polem”, w adresie `NewForm.aspx`             | standardowy      | nic więcej; układ wynika z Kroku 2 (`ShowInNewForm`, kolejność pól w typie zawartości)                                                                                                                                    |
| Ładny formularz z logo Nintex / w adresie `NintexForms`                 | **Nintex Forms** | wstążka Lista → **Nintex Forms** → w projektancie **Export** → plik `.xml`. Zawiera układ, kontrolki i **reguły** (ukrywanie pól, walidacje, wyliczenia). Zrób też screenshoty formularza w trybie edycji                 |
| Formularz „InfoPath”, adres zawiera `FormServer.aspx` lub `XsnLocation` | **InfoPath**     | pobierz szablon: dla listy `ADRES/Lists/<lista>/Item/template.xsn`, dla biblioteki formularzy `ADRES/<biblioteka>/Forms/template.xsn`. Zmień `.xsn` → `.cab`, rozpakuj: `manifest.xsf` zawiera reguły i połączenia danych |
| Standardowy, ale z dodatkowym zachowaniem (pola pojawiają się/znikają)  | JS/JSLink        | patrz Krok 7                                                                                                                                                                                                              |

### Krok 6. Uprawnienia (folder `30_uprawnienia`)

```javascript
dl(
  "30_poziomy_uprawnien.json",
  await getAll(base + "/_api/web/roledefinitions?$select=*"),
);
dl(
  "30_grupy_i_czlonkowie.json",
  await getAll(
    base +
      "/_api/web/sitegroups?$expand=Users&$select=Id,Title,Description,OwnerTitle,Users/LoginName,Users/Title,Users/Email",
  ),
);
dl(
  "30_uzytkownicy.json",
  await getAll(
    base + "/_api/web/siteusers?$select=Id,Title,LoginName,Email,IsSiteAdmin",
  ),
);
dl(
  "30_uprawnienia_witryny.json",
  await getAll(
    base + "/_api/web/roleassignments?$expand=Member,RoleDefinitionBindings",
  ),
);
const lists2 = await getAll(
  `${base}/_api/web/lists?$select=Id,Title,HasUniqueRoleAssignments,BaseTemplate,ItemCount`,
);
for (const l of lists2.filter(
  (x) => x.HasUniqueRoleAssignments && x.BaseTemplate !== 600,
)) {
  const g = `${base}/_api/web/lists(guid'${l.Id}')`;
  const out = {
    lista: l.Title,
    uprawnieniaListy: await getAll(
      `${g}/roleassignments?$expand=Member,RoleDefinitionBindings`,
    ),
    elementyZWlasnymiUprawnieniami: [],
  };
  try {
    const items = await getAll(
      `${g}/items?$select=Id,Title,HasUniqueRoleAssignments&$top=5000`,
    );
    for (const it of items.filter((i) => i.HasUniqueRoleAssignments))
      out.elementyZWlasnymiUprawnieniami.push({
        id: it.Id,
        tytul: it.Title,
        uprawnienia: await getAll(
          `${g}/items(${it.Id})/roleassignments?$expand=Member,RoleDefinitionBindings`,
        ),
      });
  } catch (e) {
    out.blad = e.message;
  }
  dl(`30_uprawnienia_lista_${safe(l.Title)}.json`, out);
  await sleep(300);
}
```

Jak to czytać: `Member.Title` = grupa lub osoba; `RoleDefinitionBindings[].Name` = poziom (np. „Pełna kontrola”, „Współtworzenie”, „Odczyt”). `LoginName` zaczynający się od `c:0+.w|` lub zawierający `\` to **grupa z Active Directory** — zapisz, bo to będą role w nowym systemie.

Ręcznie: Ustawienia witryny → **Uprawnienia witryny** (screenshot), **Administratorzy kolekcji witryn**, **Alerty użytkowników** (`_layouts/15/sitesubs.aspx` — kto dostaje powiadomienia o zmianach w listach; nie ma tego w API).

### Krok 7. Strony, skrypty, dostosowania (folder `60_strony_ui`)

```javascript
dl(
  "60_custom_actions_witryna.json",
  await getAll(base + "/_api/web/usercustomactions?$select=*"),
);
dl(
  "60_custom_actions_kolekcja.json",
  await getAll(base + "/_api/site/usercustomactions?$select=*"),
);
dl(
  "60_event_receivers_witryna.json",
  await getAll(base + "/_api/web/eventreceivers"),
);
```

- **Custom actions** = dodatkowe przyciski na wstążce/menu i skrypty wstrzykiwane do każdej strony (`ScriptSrc`, `ScriptBlock`). Jeśli lista jest pusta — dobrze.
- Strony: biblioteki **Strony witryny** (`SitePages`) i ewentualnie **Strony** (`Pages`). Otwórz stronę główną → koło zębate → **Edytuj stronę** → zobacz, jakie „składniki Web Part” są na stronie (zwłaszcza _Edytor skryptów_ / _Edytor zawartości_ — zawierają JS/HTML). Zrób screenshoty. Zawartość web partów: `ADRES/_api/web/getfilebyserverrelativeurl('/sites/xxx/SitePages/Home.aspx')/getlimitedwebpartmanager(scope=1)/webparts?$expand=WebPart,WebPart/Properties`.
- Pliki JS/CSS: biblioteki **Zasoby witryny** (`SiteAssets`) i **Biblioteka stylów** (`Style Library`) — pobierz je jak dokumenty (Krok 9).
- Kolumny z `JSLink` (Krok 2) → pobierz wskazany plik `.js`.

### Krok 8. Metadane zarządzane — POMIŃ

Adminowie potwierdzili, że term store nie jest używany. Jeśli mimo to w Kroku 2 trafisz na kolumnę `TypeAsString = TaxonomyFieldType`, wróć do adminów z jej nazwą.

---

## Część D — Dane

### Krok 9. Elementy list (folder `20_dane`)

```javascript
async function dumpItems(l) {
  const g = `${base}/_api/web/lists(guid'${l.Id}')`;
  const fields = (
    await getAll(`${g}/fields?$select=InternalName,TypeAsString,Hidden`)
  ).filter((f) => !f.Hidden);
  const lk = fields.filter((f) =>
    ["Lookup", "LookupMulti"].includes(f.TypeAsString),
  );
  const us = fields.filter((f) =>
    ["User", "UserMulti"].includes(f.TypeAsString),
  );
  const sel = [
    "*",
    "FileRef",
    "FileDirRef",
    ...lk.map((f) => `${f.InternalName}/Id,${f.InternalName}/Title`),
    ...us.map(
      (f) =>
        `${f.InternalName}/Id,${f.InternalName}/Title,${f.InternalName}/EMail,${f.InternalName}/Name`,
    ),
  ].join(",");
  const exp = [...lk, ...us].map((f) => f.InternalName).join(",");
  try {
    return await getAll(
      `${g}/items?$top=5000&$select=${sel}` + (exp ? `&$expand=${exp}` : ""),
    );
  } catch (e) {
    // za dużo kolumn lookup (limit 12) lub inny błąd → wersja bez rozwijania: lookupy jako XxxId
    console.warn(
      "Lista",
      l.Title,
      "— pobieram bez rozwijania lookupów:",
      e.message,
    );
    return await getAll(`${g}/items?$top=5000&$select=*,FileRef,FileDirRef`);
  }
}
const pomin = [
  "NintexWorkflowHistory",
  "Workflow History",
  "Historia przepływu pracy",
]; // ogromne listy techniczne — pobierz osobno, jeśli potrzebne
const lists3 = await getAll(
  `${base}/_api/web/lists?$select=Id,Title,ItemCount,BaseTemplate`,
);
for (const l of lists3.filter(
  (x) => x.BaseTemplate !== 600 && !pomin.includes(x.Title),
)) {
  try {
    dl(`20_dane_${safe(l.Title)}.json`, await dumpItems(l));
    await sleep(300);
  } catch (e) {
    console.warn("Pominięto", l.Title, e.message);
  }
}
```

Uwagi:

- Listy zewnętrzne (`BaseTemplate` 600) są pomijane celowo — nie mają danych w SharePoint (patrz Krok 11). Listy historii Nintex też, bo potrafią mieć setki tysięcy wierszy; jeśli chcesz je mieć, wywołaj `dumpItems` ręcznie dla tej jednej listy.
- Jeśli lista ma więcej niż 12 kolumn typu odnośnik/osoba, SharePoint odmawia rozwijania — skrypt sam przełącza się na wersję, w której lookupy przychodzą jako `XxxId` (numer). Nazwy dopasujesz po ID do danych listy docelowej.
- Lookupy i osoby dostaniesz jako `{Id, Title}` (osoby także e‑mail i login) — dokładnie to, czego potrzebujesz do kluczy obcych.
- Kolumny obliczeniowe zwracają wyliczoną wartość; formuła jest w Kroku 2.
- Jeśli chcesz szybko jedną listę bez konsoli: wstążka **Lista** → **Eksportuj do programu Excel** (lookupy jako tekst, bez ID).
- Historia wersji **nie jest wymagana** (potwierdzone) — pobierasz tylko stan bieżący.
- Załączniki: `…/items(ID)/attachmentfiles` → każdy plik przez `…/attachmentfiles('nazwa.pdf')/$value`; leżą też fizycznie w `ADRES/Lists/<lista>/Attachments/<ID>/`.

### Krok 10. Dokumenty z bibliotek

- Metadane plików już masz w Kroku 9 (`FileRef` = ścieżka).
- Same pliki, masowo z zachowaniem folderów: w bibliotece wstążka **Biblioteka** → **Otwórz w Eksploratorze** (Internet Explorer/Edge w trybie IE) albo w Windows „Mapuj dysk sieciowy” na adres biblioteki (`\\sp.bank.local\DavWWWRoot\sites\dora\Dokumenty`). To zwykłe kopiowanie plików — adminowie potwierdzili, że WebDAV działa.
- Pojedynczy plik: `ADRES/_api/web/getfilebyserverrelativeurl('/sites/dora/Dokumenty/plik.docx')/$value`.
- Wersje plików nie są wymagane — kopiujesz tylko bieżące.

---

## Część D2 — Integracje zewnętrzne (Krok 11) — NAJWAŻNIEJSZY OTWARTY TEMAT

Adminowie potwierdzili, że witryny korzystają z danych spoza SharePoint. To oznacza, że część funkcjonalności zależy od innego systemu (bazy SQL, usługi, pliku Excel), który na nowej platformie też musi mieć źródło. Trzeba ustalić **co, skąd, w którą stronę i z jakim uwierzytelnieniem**. Wszystko poniżej to szukanie śladów przez web; resztę dopytasz adminów.

### 11a. Listy zewnętrzne (BCS)

W plikach `10_lista_*.json` z Kroku 2 znajdź listy z `lista.BaseTemplate = 600`. Szybciej — w konsoli:

```javascript
const ext = (
  await getAll(`${base}/_api/web/lists?$select=Id,Title,BaseTemplate`)
).filter((l) => l.BaseTemplate === 600);
for (const l of ext) {
  dl(
    `11_bcs_${safe(l.Title)}.xml`,
    (await get(`${base}/_api/web/lists(guid'${l.Id}')?$select=SchemaXml`))
      .SchemaXml,
  );
  await sleep(300);
}
console.log(ext.map((l) => l.Title));
```

W zapisanym XML szukaj atrybutów: `EntityNamespace`, `EntityName` (nazwa encji), `LobSystemInstance` (nazwa źródła — np. instancja SQL lub usługa), `SpecificFinder` (metoda odczytu). Zapisz je w `90_notatki\integracje.md`. Sama lista zewnętrzna nie ma danych w SharePoint — pokazuje na żywo dane z tamtego systemu; **nie eksportuj jej jak zwykłej listy** (Krok 9 zwróci błędy lub puste dane — to normalne).

Kolumny typu **„Dane zewnętrzne”** w zwykłych listach: w Kroku 2 `TypeAsString = BusinessData` — to lookup do encji BCS; zanotuj `RelatedField`/`SystemInstance` ze `schemaXml`.

### 11b. Integracje w workflow Nintex

Otwórz każdy plik `.nwf` w edytorze tekstu (VS Code, Notepad++) i wyszukaj (Ctrl+F) słowa:

| Szukaj                         | Akcja Nintex                   | Co zanotować                                                    |
| ------------------------------ | ------------------------------ | --------------------------------------------------------------- |
| `CallWebService`, `WebRequest` | Call web service / Web request | adres URL usługi, metoda, konto (zwykle stała lub Secure Store) |
| `ExecuteSql`                   | Execute SQL                    | connection string (bez hasła), treść zapytania                  |
| `QueryLDAP`                    | Query LDAP                     | co pobiera z AD (np. przełożonego)                              |
| `QueryExcel`                   | Query Excel Services           | plik `.xlsx` i zakres                                           |
| `QueryUserProfile`             | Query user profile             | pola profilu (np. Manager, Department)                          |
| `Credential` / `Constant`      | użycie stałej                  | nazwa stałej → dopasuj do eksportu z 4c                         |

Każde trafienie to jeden wiersz w `integracje.md`: workflow → akcja → system docelowy → odczyt/zapis → uwierzytelnienie.

### 11c. Strony i formularze

- W Kroku 7 (strony w trybie edycji) zanotuj web party: **Excel Web Access** (który plik), **Wyszukiwanie zawartości / Wyniki wyszukiwania** (jakie źródło wyników), **Wyświetlanie danych / Filtr** połączone z listami zewnętrznymi.
- W eksportach **Nintex Forms** (Krok 5) szukaj `ExternalData`, `Lookup` do listy z 11a, `WebService`.
- W InfoPath `manifest.xsf` szukaj `<xsf:dataConnections>` — każde połączenie to integracja.

### 11d. Pytania do adminów (druga runda — konkretne)

1. Proszę o eksport **modeli BDC** z Central Admin → Zarządzanie aplikacjami → Usługa łączności danych biznesowych → Eksport (pliki `.bdcm`) dla źródeł używanych w naszych witrynach.
2. Dla każdej integracji: **nazwa systemu/bazy, właściciel biznesowy i techniczny, sposób uwierzytelnienia** (Secure Store — jaka aplikacja docelowa; konto techniczne; passthrough).
3. Czy integracja jest **tylko odczytem**, czy SharePoint również **zapisuje** do tamtego systemu (to zmienia projekt migracji).
4. Czy usługi wywoływane z workflow (URL z 11b) są dostępne z sieci, w której stanie nowa platforma.
5. Czy poza naszymi witrynami coś **odczytuje dane z tych witryn** (inne systemy, raporty Power BI, skrypty) — po migracji straciłyby źródło.

---

## Część E — Co zrobić z tym, co zebrałeś (folder `90_notatki`)

Dla każdej witryny spisz w jednym dokumencie:

1. **Model danych** — tabela: lista → kolumny (typ, wymagane, unikalne) → relacje (lookup → lista docelowa, zachowanie przy usuwaniu) → wersjonowanie/zatwierdzanie/„tylko własne”.
2. **Reguły** — wszystkie `Formula`, `ValidationFormula`, `DefaultValue`, reguły z formularzy Nintex/InfoPath, warunki startu workflow, `ViewQuery` widoków (opisz słowami, co filtruje).
3. **Procesy** — na każdy `.nwf`: wyzwalacz → kroki → decyzje → zadania (kto, termin, eskalacja) → maile (do kogo, treść) → aktualizacje pól → integracje (`Call web service`, `Execute SQL`, `Query LDAP`).
4. **Role** — grupa → poziom → gdzie (witryna/lista/element) → grupa AD.
5. **Ekrany** — widoki (kolumny, filtry), formularze (układ, pola warunkowe), nawigacja, strona główna.
6. **Sprawy w toku** — ile workflow jest w stanie „Running” (Workflow inventory / lista `Workflow Tasks` z niezakończonymi zadaniami). Decyzja: dokończyć na SharePoint przed przełączeniem, czy przenieść stan.

---

## Część F — Odpowiedzi adminów (stan na 2026‑09‑09) i co z nich wynika

| #   | Pytanie                                  | Odpowiedź | Skutek                                                                                                                                                     |
| --- | ---------------------------------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Konsola F12, REST, `_vti_bin` (Nintex)   | Tak       | wszystkie skrypty z manuala działają                                                                                                                       |
| 2   | Rozwiązania farmowe / kod niestandardowy | Nie       | Krok 7 tylko kontrolnie                                                                                                                                    |
| 3   | Event receivery                          | Brak      | ignoruj sekcję `eventReceivers`                                                                                                                            |
| 4   | Publishing aktywny                       | Tak       | **Krok 3 pominięty**                                                                                                                                       |
| 5   | Term store                               | Nie       | **Krok 8 pominięty**                                                                                                                                       |
| 6   | WebDAV / Otwórz w Eksploratorze          | Tak       | Krok 10 przez kopiowanie plików                                                                                                                            |
| 7   | Eksporty z NWAdmin                       | Tak       | poproś o: `FindWorkflows`, masowy eksport `.nwf`, `ExportWorkflowConstants` per witryna i farma, globalne ustawienia Nintex (szablony maili, LazyApproval) |
| 8   | SharePoint Designer                      | Nie       | bez wpływu                                                                                                                                                 |
| 9   | Dane spoza SharePoint                    | **Tak**   | **Krok 11 + druga runda pytań (11d)**                                                                                                                      |
| 10  | Historia wersji / wykonań workflow       | Nie       | tylko stan bieżący; listy historii Nintex pobierz mimo to (tanie, przydają się do testów)                                                                  |

---

## Część G0 — Co zostało zweryfikowane w wersji 3

- Wszystkie skrypty używają hosta z paska adresu (`location.origin`) i `credentials:'include'` — usuwa okienka logowania wynikające z różnicy hostów.
- `get()` wykrywa błędy SharePoint (`odata.error`) i zgłasza je czytelnie zamiast zapisywać pliki z komunikatem błędu.
- Pętle mają `try/catch` — pojedyncza problematyczna lista nie przerywa całego zrzutu; pomijane listy widać w konsoli (`console.warn`).
- Pomijane są listy zewnętrzne (BCS) i ogromne listy historii Nintex; Krok 9 ma automatyczny fallback przy limicie 12 kolumn lookup.
- Krok 2 dodatkowo tworzy jeden zbiorczy plik, na wypadek blokady wielokrotnych pobrań.
- Odstępy `sleep(300)` między pobraniami zapobiegają gubieniu plików przez przeglądarkę.
- Nazwy plików: puste tytuły list dostają `bez_nazwy` zamiast błędu.
- Czego nie da się sprawdzić bez Twojego środowiska: dokładna wartość `workflowType` w usłudze Nintex (`list` vs `List`) i to, czy na Twoich stronach jest `_spPageContextInfo` (jest na każdej klasycznej stronie SharePoint 2019; gdyby nie było, otwórz `ADRES/_layouts/15/viewlsts.aspx` i uruchom konsolę tam).

## Część G — Lista kontrolna (odhacz per witryna i podwitryna)

- [ ] Krok 1 — pliki `00_*` + screenshoty ustawień witryny
- [ ] Krok 2 — plik JSON na każdą listę + screenshoty ustawień list + uzupełniony słownik GUID
- [x] Krok 3 — pominięty (Publishing)
- [ ] Krok 4 — spis workflow CSV, wszystkie `.nwf` (od adminów i/lub z konsoli), PDF‑y z Print, stałe, harmonogramy, ustawienia startu
- [ ] Krok 5 — formularze rozpoznane; eksporty Nintex Forms / InfoPath / screenshoty
- [ ] Krok 6 — uprawnienia witryny, list, elementów; grupy; grupy AD; alerty
- [ ] Krok 7 — custom actions, strony, web party, JS/CSS
- [x] Krok 8 — pominięty (brak term store)
- [ ] Krok 9 — dane wszystkich list + załączniki (bez wersji)
- [ ] Krok 10 — dokumenty z bibliotek
- [ ] Część E — notatki mapujące + lista spraw w toku
- [ ] Krok 11 — listy BCS, integracje z `.nwf`, web party; `integracje.md`
- [ ] Część F — pliki od adminów (pkt 7) i odpowiedzi drugiej rundy (11d) wpięte do `90_notatki`
