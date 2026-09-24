# Dom — geometryczny model roboczy 3D

To model utworzony z wektorów i wymiarów dokumentacji PDF, a nie model uzyskany z wygenerowanego wcześniej obrazu. Obraz AI nie był źródłem geometrii.

## Od czego zacząć

**podglad_3d.html** — samodzielny podgląd 3D z obrotem, przesuwaniem i przybliżaniem. Cała geometria jest w środku pliku. Nie ma odwołań do zewnętrznych bibliotek, serwerów lub kont użytkownika. Otwórz zapisany plik w przeglądarce. Podgląd korzysta z WebGL 2, a gdy WebGL nie jest dostępny, automatycznie przechodzi na programowe rysowanie tych samych trójkątów 3D z buforem głębokości. Tryb programowy może działać wolniej. Interfejs pozwala przełączać wnętrze, bryłę z dachem i widok z góry, ukrywać grupy oraz sprawdzać nazwy i uwagi do klikniętych elementów. Podgląd NIE jest edytorem parametrycznym.

**dom_wnetrze.glb** — ściany, podłogi, otwory i schematyczna stolarka, bez stropu i dachu. Wersja startowa do projektowania wnętrza. Elementy są osobnymi nazwanymi obiektami.

**dom_bryla.glb** — ten sam model z uproszczonym stropodachem i attyką. Plik zawiera rzeczywistą siatkę 3D i materiały robocze.

**dom_model_CAD.step** — złożenie CAD: 188 zamkniętych brył BREP oraz 44 powierzchnie odniesienia. Elementy są nazwane i pogrupowane. To geometria CAD, lecz nie natywny parametryczny projekt BIM i nie historia operacji konkretnego programu. Powierzchnie podłóg i sufitów celowo nie mają grubości.

**dom_model.obj + dom_materialy.mtl** — dodatkowy format wymiany siatek. Zachowaj oba pliki w jednym folderze. Nazwy obiektów i grup pozwalają oddzielić dach od wnętrza.

## Skala i współrzędne

- STEP: milimetry, jednostka zapisana w pliku, oś Z w górę.
- GLB: metry, standardowa oś Y w górę. Transformacja względem danych źródłowych: (x, y, z) GLB = (X, Z, -Y) CAD / 1000. Nie jest to lustrzane odbicie.
- OBJ i scena_modelu.json: metry, oś Z w górę.
- X w prawo i Y w górę na rzucie PDF. Z = 0 odpowiada projektowemu ±0,00 posadzki. Nie przypisano osiom automatycznie kierunków geograficznych.

Odtworzony obrys wektorowy ma 28 297,4 × 11 920 mm, podczas gdy opis projektu podaje 28 300 × 11 920 mm. Nie rozciągnięto modelu, aby wymusić równą długość. Obrys elewacji ma około 271,28 m² i nie obejmuje pełnego bilansu zadaszeń; nie zastępuje podanej powierzchni zabudowy 277,25 m². Zaokrąglenie współrzędnych do 0,1 mm nie oznacza takiej dokładności budowlanej.

## Podstawa modelu

Plik: `Projekt budowlany PZT_PAB_2024.02.01.pdf`.

- Strona 26: obrysy ścian, słupa, 15 pomieszczeń i otworów. Zastosowano wcześniejszą ekstrakcję zapisaną w `dane_zrodlowe.json`.
- Strony 27–28: wysokość do sufitu 2600 mm, przestrzeń instalacyjna 300 mm, płyta stropowa 180 mm, izolacja zewnętrzna 260 mm.
- Strona 31: zewnętrzny i wewnętrzny obrys dachu odczytane bezpośrednio z wektorowych ścieżek 0 i 1. Współrzędne i przeliczenie skali są w `obrys_dachu_z_pdf.json`.
- Strona 21: parametry ogólne do kontroli, nie do dowolnego reskalowania rzutu.

Źródłowy PDF SHA-256: `7f08b08ce23005a5d67db2a47e35adfd253c533141631d65b40e2453ac46f373`.

Nie łączono geometrii z odrębnym projektem wnętrza ani z przykładami repozytorium archtool.

## Aktualizacja stolarki na podstawie pomiaru

Stolarka okienna zostala zaktualizowana na podstawie okna.pdf - oferty 2024/510 v. 8 po pomiarze z 2024-12-13. Szczegoly i mapowanie znajduja sie w OKNA_ZAMOWIONE.md.

Okno kuchenne ma wymiar 2565 x 1490 mm i lewa krawedz 700 mm od sciany od strony garazu. Salon: HST 6555 x 2630 mm. Sypialnia: HST 3070 x 2630 mm. Trzy okna pokojowe: 1770 x 1590 mm. Para lazienkowa: 865 x 2580 mm. Dwa okna garazowe: 1470 x 575 mm.

Oferta podaje gabaryty produktow, typy i parametry, ale nie wspolrzedne montazowe ani wysokosci parapetow.

## Drzwi wejściowe i brama po zamówieniu

Drzwi.pdf i brama.pdf są źródłem aktualnych danych dla dwóch elementów zewnętrznych. Szczegółowe zestawienie znajduje się w DRZWI_BRAMA_ZAMOWIONE.md, a dane maszynowe w stolarka_zewnetrzna.json.

- drzwi wejściowe GERDA ALTUS RC2: 1470 × 2100 mm, skrzydło 970 mm + doświetle 500 mm, RAL 7016;
- brama garażowa KRISHOME K2 R: 5000 × 2500 mm, antracyt gładki 204, panel Slick bez tłoczeń.

Podgląd HTML oraz pliki GLB/OBJ pokazują te wymiary i podstawowe podziały. Geometria profili i okuć pozostaje schematyczna.

## Elewacja, teren i otoczenie

Model zewnętrzny zawiera teraz strefy materiałowe elewacji z rysunków projektu, żelbetowy daszek nad wejściem z `daszek.jpg`, teren i utwardzenia z PZT oraz schody zewnętrzne przy tarasie. Szczegóły źródeł i jawne uproszczenia są opisane w `ELEWACJA_TEREN.md`.

Uwzględniono również ustalenie z budowy o różnicy jednej warstwy pustaka: garaż ma 12 warstw do attyki, a pozostała część domu 13. Roboczy offset poziomu garażu wynosi 238,462 mm (3100 / 13) i jest zapisany w `parametry_modelu.json`.

## Elewacja i zagospodarowanie terenu

Model zewnętrzny obejmuje teraz wykończenie elewacji z projektu, teren i utwardzenia z PZT, taras ze schodami, żelbetowy daszek nad wejściem z `daszek.jpg` oraz podniesiony poziom garażu wynikający z 12 warstw pustaka wobec 13 w części mieszkalnej. Szczegóły i zakres założeń opisano w `ELEWACJA_TEREN_PODWORKO.md`.

Dane pomocnicze są rozdzielone na `elewacje_materialy.json` i `pzt_zagospodarowanie.json`, dzięki czemu można później modyfikować wygląd elewacji i podwórka bez ponownego odczytywania PDF.

## Co zawiera model

27 profili z rzutu: 26 fragmentów ścian i 1 słup. Ściany zostały wyciągnięte do wyliczonego poziomu 2900 mm, a nie tylko do sufitu 2600 mm. Odtworzono mur pod znanymi parapetami i nad otworami. Otwory przechodzą również przez odtworzoną izolację zewnętrzną. Stolarka okienna odpowiada 10 zamówionym zestawom z okna.pdf; zestawy HST sa w modelu reprezentowane przez po dwa techniczne segmenty. Zachowano 13 symboli drzwi/bramy i nieoznaczone przejście PR01. Nie dodano ściany na funkcjonalnej granicy kuchni i salonu.

Podłogi są osobnymi powierzchniami dla 15 pomieszczeń; osobne powierzchnie uzupełniają przejścia. Sufity to dodatkowe płaszczyzny na +2,60 m, domyślnie wyłączone w podglądzie i pominięte w obu GLB, aby nie zasłaniały wnętrza. Są w STEP i danych sceny.

Materiały wnętrza pozostają robocze. Elewacja zewnętrzna korzysta natomiast z podziałów białych, szarych i drewnianych pokazanych na arkuszach elewacji projektu.

## Założenia i ograniczenia — przeczytaj przed użyciem wymiarów

1. **Wymiary stolarki a położenie montażowe.** Gabaryty okien pochodzą z okna.pdf (oferta po pomiarze). Dokument nie podaje wysokości parapetów ani współrzędnych montażowych. Model zachowuje dotychczasowe położenie otworów, a dla kuchni dodatkowo ustalenie 700 mm od ściany przy garażu. Nie należy utożsamiać gabarytu produktu z wymiarem otworu wykonawczego bez pomiaru montażowego.
2. **Nominał drzwi nie jest otworem w murze.** Szerokości otworów pochodzą z rzutu; skrzydła/brama mają osobne wymiary nominalne. Dla DR02–DR13 roboczo przyjęto 2050 mm wysokości otworu, przenosząc wartość wybranego otworu z A-A — nie ma potwierdzenia osobno dla każdego z nich. Dla bramy DR01 przyjęto jako wysokość otworu nominalne 2250 mm. Przejście PR01 ma roboczo 2600 mm, bez wymyślonego skrzydła drzwiowego.
3. **Stolarka jest symboliczna.** Rama 60 × 90 mm, szyba 10 mm, skrzydło 40 mm i ich osadzenie to ustawienia podglądu, nie przekroje podane w projekcie. Nie odwzorowano produktów, podziałów, okuć ani szczegółów HST.
4. **Dach jest uproszczony.** Dokładne obrysy XY pochodzą z wektorów strony 31, ale górną powierzchnię wypełnienia ustawiono roboczo płasko na +3,71 m. W źródle jest to rzędna lokalna, a NIE poziom całego dachu. Nie odtworzono spadków 5° i 0,5%, wpustów i pełnej zmienności warstw. Góra attyki +3,95 m przyjęta z projektu; nie rozstrzygnięto różnicy względem wymiaru 394 cm na B-B. Nie rozdzielono warstw attyki.
5. **Strop i słup.** 2900 mm to 2600 + 300, a 3080 mm to 2600 + 300 + 180. Zasięg poziomy płyty przyjęto po obrysie rdzenia. Wysokość wolnostojącego słupa roboczo przeniesiono do spodu stropu. Nie odtworzono jego zadaszenia.
6. **Wykończenia.** Nie pomniejszano pokoi o tynki i okładziny, których kompletnego układu nie określono. Podłogi i sufity są płaszczyznami, a nie dowolnie pogrubionymi warstwami. Przed doborem mebli na wymiar potrzebny jest pomiar po wykończeniu.
7. **Pominięte elementy.** Nadal brak fundamentów, instalacji, mebli i szczegółów konstrukcyjnych. Taras, schody, teren oraz daszek są już ujęte w modelu zewnętrznym, z uproszczeniami opisanymi w `ELEWACJA_TEREN.md`. Różnych poziomów posadowienia z projektu nie zastąpiono jedną zmyśloną wartością.
8. **Rozbieżności dokumentacji zachowano.** Dotyczy to między innymi łańcuchów wymiarowych, długości i wysokości budynku. Pełna lista jest w źródłowym JSON i `kontrola_modelu.json`.

## Edycja i powtarzalność

Najprostsze otwarcie w Blenderze: **File → Import → glTF 2.0 (.glb/.gltf)** i wybór `dom_wnetrze.glb`. Po imporcie można zapisać własny plik `.blend`. Materiały i geometria są robocze; to nie gotowy konfigurator mebli.

Dołączony **utworz_scene_Blender.py** może utworzyć natywny `.blend` z `scena_modelu.json`: kolekcje, osobny materiał dla każdej podłogi, współrzędne UV w metrach i opisy elementów. Skrypt wymaga Blendera. **Nie został tutaj uruchomiony; pakiet nie zawiera gotowego pliku .blend.** Sposób uruchomienia opisano na początku skryptu. Sam import GLB nie wymaga tego skryptu.

**generuj_model.py** odtwarza STEP, oba GLB, OBJ i pliki sceny z danych i parametrów. Wymaga Pythona z CadQuery, Shapely, Trimesh i NumPy. Zmiany założeń wysokościowych wprowadza się w `parametry_modelu.json`; źródłowa ekstrakcja pozostaje oddzielna. Nie traktuj jednak dowolnego przesuwania wierzchołków JSON jako gotowego edytora architektonicznego.

Po ponownym wygenerowaniu geometrii uruchom `python aktualizuj_podglad.py`, aby przebudować `podglad_3d.html`. Do tego czasu HTML zawiera poprzednią wersję sceny. Plik `podglad_szablon.html` jest szablonem technicznym, nie gotowym podglądem. Wcześniej utworzony plik .blend również nie aktualizuje się automatycznie.

## Kontrola plików

W trakcie generowania sprawdzono poprawność BREP każdego elementu, szczelność i orientację siatek wszystkich 188 brył oraz ponownie otwarto zapisane STEP i oba GLB. Powierzchnie odniesienia celowo nie są bryłami szczelnymi. Wyniki znajdują się w `kontrola_modelu.json`.

Ta kontrola sprawdza spójność plików 3D, **nie poprawność wykonawczą, nośność ani zgodność modelu ze stanem istniejącym**.

Podgląd przetestowano w Chromium w trybie programowym (WebGL niedostępny w środowisku testowym): widoki wnętrza, bryły i z góry, obrót, zoom, przełączanie elementów, wybór obiektu oraz pobranie osadzonego GLB. Pobrany GLB ma identyczny SHA-256 jak oryginał. Ścieżka renderowania WebGL i skrypt zapisu .blend nie były wykonane w tym środowisku.
