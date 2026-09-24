# Elewacja, teren, daszek i podwórko

## Źródła

- `DWK_2021-001-PZT_PAB.pdf`, s. 15: projekt zagospodarowania terenu (PZT), skala 1:500.
- `DWK_2021-001-PZT_PAB.pdf`, s. 26–27: elewacje zachodnia/wschodnia oraz południowa/północna, skala 1:50.
- `daszek.jpg`: zdjęcie istniejącego żelbetowego daszku nad wejściem głównym.
- Ustalenie inwestora: garaż ma 12 warstw pustaka do attyki, pozostała część domu 13; garaż jest o jedną warstwę wyżej.

## Elewacja

Kolorowe strefy elewacji są odtworzone z wektorowych wypełnień rysunków projektowych, a nie dobierane „na oko”. Model rozróżnia biały tynk, szary tynk oraz drewniane strefy poziome. Dla drewna dodano schematyczne poziome podziały. Dane źródłowe są w `elewacje_materialy.json` wraz z numerami stron i indeksami wektorów PDF.

Projekt opisuje elewację jako białą i szarą, pokrytą tynkiem silikonowym, z elementami drewnianymi w układzie poziomym. Aktualna zamówiona stolarka z wcześniejszych etapów pozostaje nadrzędna wobec wymiarów stolarki z rysunków elewacji.

## Garaż — różnica poziomów

Do modelu przyjęto roboczo **238,462 mm** jako wysokość jednej warstwy, wyliczoną z modelowej wysokości muru 3100 mm / 13 warstw. Posadzka garażu, brama i dwa okna garażowe zostały podniesione o 238,462 mm względem poziomu 0 pozostałej części domu. Górny poziom stropu/attyki pozostaje wspólny, więc wysokość wnętrza garażu jest odpowiednio mniejsza. Wartość 238,462 mm jest wyliczeniem geometrycznym z 3100 mm / 13 warstw, a nie niezależnym pomiarem wysokości pustaka. Jeśli pomiar na budowie wykaże inną różnicę poziomów, parametr `garage_floor_offset_mm` w `parametry_modelu.json` należy skorygować.

## Daszek wejściowy

`daszek.jpg` pokazuje płaski żelbetowy daszek oparty z jednej strony o bryłę domu, a z drugiej o słup. W rzucie projektu istniejący słup `P01` ma położenie odpowiadające zdjęciu. Daszek został wprowadzony jako płyta 180 mm nad wnęką wejściową, z obrysem opartym o geometrię wnęki i słupa. To odtworzenie geometrii widocznej na zdjęciu, a nie projekt konstrukcyjny zbrojenia.

## PZT, podwórko i taras

Obrysy terenu biologicznie czynnego, tarasu i utwardzeń odczytano bezpośrednio z wektorów PZT. Dopasowanie współrzędnych PZT do modelu wykonano po obrysie budynku; maksymalny błąd dopasowania punktów kontrolnych wynosi ok. 0,18 mm w układzie modelu.

Z wektorów PZT otrzymano orientacyjnie:
- teren biologicznie czynny: **1588,19 m²**,
- taras: **88,14 m²**,
- geometria wszystkich odczytanych utwardzeń: **494,85 m²**.

Opisowy bilans projektu podaje utwardzenie 487,84 m². Model zachowuje obrys wektorowy z mapy zamiast korygować go do liczby z bilansu; rozbieżność jest jawna i nie została „wyrównana”.

## Ukształtowanie terenu i schody

Projekt podaje rzędne terenu w zakresie **254,6–250,3 m n.p.m.**, spadek terenu w kierunku północnym oraz rzędną wejścia **253,5 m n.p.m.**. Ponieważ PZT nie stanowi kompletnej siatki NMT, powierzchnia terenu w modelu jest świadomie uproszczona do płaszczyzny o spadku ok. 3,3% w osi działki. To interpretacja wizualna oparta na podanych rzędnych, nie model geodezyjny.

Przy tarasie od strony północnej elewacja pokazuje schody. W modelu użyto 4 stopni po 150 mm wysokości i 300 mm głębokości, żeby połączyć poziom tarasu z uproszczoną powierzchnią terenu. Dokładne wysokości stopni należy ostatecznie ustalić z niwelacji terenu wykonanej na budowie.

## Pliki modelu

Aktualizacja obejmuje `index.html`, `podglad_3d.html`, `scena_modelu.json`, oba GLB oraz OBJ/MTL. `dom_model_CAD.step` nie jest w tym etapie rozszerzony o otoczenie i wykończenie elewacji.
