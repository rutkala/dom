# Wnętrze — model dwuwarstwowy

Źródło: `Projekt wnętrza 20,10,2023.pdf`.

## Zakres projektu źródłowego

Projekt wnętrza zawiera wizualizacje i rysunki techniczne dla czterech głównych stref:

- kuchnia + jadalnia (pom. 11),
- salon (pom. 10),
- spiżarnia (pom. 14),
- wiatrołap / hol wejściowy (pom. 1).

Pozostałe pomieszczenia nie mają w tym PDF-ie kompletnego projektu meblowego, dlatego na tym etapie nie są dopowiadane.

## Dwie warstwy

### 1. Warstwa `wnetrze_bloki`

To geometryczne bryły robocze służące do sprawdzania:

- wymiarów,
- przejść i ergonomii,
- pozycji mebli,
- wysokości zabudów,
- relacji z oknami i drzwiami.

Bryły są celowo proste. Ich źródłem są rysunki techniczne z PDF, a tam gdzie rysunek nie zamyka wszystkich wymiarów — układ z rzutu ogólnego i wizualizacji.

### 2. Warstwa `wnetrze_elementy`

To docelowa warstwa wizualna. Zawiera:

- bardziej szczegółowe proxy mebli,
- materiały i kolory z projektu,
- elementy odpowiadające pozycjom z wykazu materiałów,
- nazwy wybranych produktów, gdy PDF wskazuje konkretny model.

Nie oznacza to kopiowania modeli producentów 1:1. Jeżeli nie ma dostarczonego pliku 3D produktu, model jest odtworzony jako własna bryła o zbliżonych proporcjach i opisany nazwą produktu.

## Główne dane z projektu

### Kuchnia

- zabudowa główna: 5,950 m,
- wyspa: 2,900 × 0,900 m,
- wysokość blatu: 0,900 m,
- strefa hokerów: 1,700 m,
- bok roboczy wyspy: 1,200 + 0,600 + 0,800 + 0,300 m,
- wysoka zabudowa: do 2,600 m,
- witryna / winiarka: 0,600 × 2,600 m,
- ściana tablicowa: 1,850 m,
- drzwi przesuwne drewniane do spiżarni.

### Salon / jadalnia

- ściana TV / kominek: 4,710 m szerokości,
- wysokość zabudowy ściany TV: 2,900 m,
- centralna strefa betonowa: 2,300 m,
- kominek: 1,830 m w świetle zabudowy,
- ściana z obrazem i lamelami: 4,100 m,
- część betonowa: 2,750 m,
- lamele: 1,350 m.

### Spiżarnia

- ciąg dolny: 3,000 m,
- głębokość dolnej zabudowy: 0,450–0,600 m,
- wysoka zabudowa narożna: 1,410 m,
- wysokość zabudowy: do 2,900 m,
- układ półek i szafek zgodnie z rysunkami s. 33–36.

### Wiatrołap

- szafa: 2,500 m szerokości, 2,900 m wysokości,
- lustro: 1,150 m szerokości,
- konsola: 0,800 × 0,200 m, wysokość 0,150 m,
- ściana wejściowa: 4,650 m,
- ściana lamelowa z ukrytymi drzwiami: 1,500 m,
- zabudowa obok lameli: 1,160 m.

## Materiały / wybrane elementy z PDF

Kuchnia i spiżarnia:
- płyta meblowa: dąb craft złoty,
- płyta meblowa: czarny mat,
- blat: dąb craft złoty,
- hokery: Hoker loft 60 KAM,
- zlewozmywak: Primagran Oslo 80 Pocket,
- płytki: Halcon Doge Torcello 60×120 oraz Ceramica Limone Marmo White 60×120,
- farba tablicowa: Jeger.

Salon / jadalnia / wiatrołap:
- narożnik: projekt wskazuje model Liquid, tkanina Soro 21,
- krzesła: Alaska beżowe / czarne nogi,
- stoliki kawowe: okrągłe 60/90 cm,
- fotel: projekt wskazuje Sensi, tkanina Soro 40,
- beton architektoniczny / efekt SAFARI,
- kominek: Dimplex Sierra 72",
- dywan: Hector 200×300 cm,
- zasłony: Eurofirany Madlen,
- oświetlenie i szynoprzewody zgodnie z wykazem materiałów.

## Zasada wdrożenia w HTML

Docelowo podgląd ma mieć dwa niezależne przełączniki:

- **Wnętrze — bloki**
- **Wnętrze — elementy**

oraz filtrowanie per strefa: kuchnia, salon, spiżarnia, wiatrołap.

Warstwa elementów może być włączona razem z blokami do porównania, ale domyślnie ma zastępować bryły blokowe w codziennej prezentacji.

## Status implementacji

Generator i podgląd HTML obsługują dwie niezależne warstwy wnętrza oraz filtry dla kuchni, salonu, spiżarni i wiatrołapu. Wygenerowane pliki modelu są odtwarzane automatycznie na branchu roboczym po zmianach źródłowych.
