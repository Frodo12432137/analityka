# Zdjęcia potrzebne do walidacji Python ↔ GAMS

Nie pokazuj pełnych identyfikatorów PPE, nazw klientów, adresów ani innych
danych osobowych. Wystarczą nagłówki, liczby wierszy i 2–3 rekordy z zamazanym
środkiem identyfikatora. Nie uruchamiaj ponownie GAMS-a i nie otwieraj pliku
`Model_dobor_klientow_v8.lst` o rozmiarze około 3,9 GB.

## 1. Wejście Zamościa

Otwórz `Model_2025_20260318_Zamosc_w1_w4_parts.xlsx` i zrób:

1. jedno zdjęcie wszystkich zakładek;
2. `Oddzial`/`Oddział`: wiersze 1–4, kolumny A–F oraz ostatnią kolumnę z godziną;
3. `Klienci`: wiersze 1–5 kolumny A, z zamazanym środkiem PPE; pokaż też
   liczbę wszystkich wierszy;
4. `Klienci_part_1`: wiersze 1–4, kolumny A–F;
5. `Klienci_part_2`: ten sam zakres;
6. `Ograniczenia`: wiersze 1–6, kolumny A–F; PPE zamazane, wartości wag mogą
   pozostać widoczne.

Potrzebujemy potwierdzić dokładne nazwy nagłówków, zapis dat i godzin, format
PPE (tekst czy liczba), jednostkę bilansu oraz znak poboru/oddania. Nie są
potrzebne zdjęcia całych arkuszy.

## 2. Zapisany wynik GAMS dla Zamościa

Otwórz najnowszy `Wyniki_2025_20260318_Zamosc_...xlsx` i pokaż:

1. nazwy zakładek;
2. arkusz `Wyniki` w okolicy bloków zaczynających się w B3, G2, N2 i U2;
3. nagłówki i po 2–3 zanonimizowane rekordy każdego bloku;
4. liczbę wybranych klientów w `w1`, `w2`, `w3`, `w4`, jeśli jest widoczna.

## 3. Status czterech rozwiązań

W małym pliku tekstowym `Model_dobor_klientow_v8` (około 270 KB), nie w
gigantycznym `.lst`, wyszukaj kolejno:

- `S O L V E`;
- `MODEL STATUS`;
- `SOLVER STATUS`;
- `OBJECTIVE VALUE`;
- `MIP` albo nazwę solvera.

Zrób zdjęcie każdego z czterech podsumowań solve. Potrzebne są tylko status,
wartość celu, czas i ewentualna luka; żadnych rekordów PPE.

## 4. Kontrola kolejności grup

W GAMS Data Viewer otwórz `Dane_out\Klienci.gdx`, wybierz symbol
`s_map_kl_cz` i pokaż:

- informacje o symbolu i liczbę rekordów;
- pierwszych około 10 rekordów;
- ostatnich około 10 rekordów.

To jednorazowo potwierdzi, czy GAMS przypisał kolejność z `Klienci!A2:A...`
do grup `c1..c4` dokładnie tak samo jak Python. Identyfikatory można zamazać,
pozostawiając różne końcówki umożliwiające śledzenie kolejności.

## 5. Dopiero później

Po zgodności podstawowego wyboru sfotografujemy `Model_klienta_zastepczego_v32.gms`
oraz schemat kolumn lokalizacji. Ten etap odpowiada za zastępstwa i późniejsze
grupowanie do kontaktu; nie należy mieszać go z modelem v8.
