# lstree – fájlok mentése kimentett `$MFT` alapján (tömörített fájlokkal is)

Önálló mentőeszköz olyan NTFS kötethez, amely nem mountolható, de az `$MFT` fájl nagyobb
része kimenthető. A kimentett MFT-rekordokból felépíti a könyvtárfát, és a run-listák alapján
közvetlenül az eszközről másolja ki a fájlokat. Kezeli az NTFS-tömörítést (LZNT1), az
attribútumlistás (több MFT-rekordra szétszórt) fájlokat és a sérült run-listákat.

Az [lsindx.py + indxrename.py](LSINDX.md) párostól független: nem használja az INDX
blokkokat és az `INDEX.pck`-t.

| Fájl | Szerep |
|---|---|
| [lstree.py](lstree.py) | Egy kimentett `$MFT` fájlból fát épít és fájlokat másol le az eszközről, NTFS-tömörítés (LZNT1), attribútumlisták és sérült run-listák kezelésével. |
| [lznt1.py](lznt1.py) | LZNT1 (NTFS-tömörítés) kitömörítő modul; önállóan futtatva egy nyersen kimentett tömörített fájlt állít helyre. |

---

## lstree.py

Akkor hasznos, ha az `$MFT` fájl nagyobb része kimenthető (például egy korábbi mentésből vagy
az MFT run-listája alapján kimásolva), de maga a kötet nem mountolható.

### Beállítás és futtatás

- Bemenet: `MFT` nevű fájl az aktuális könyvtárban (a kimentett `$MFT` tartalma)
  ([lstree.py:304](lstree.py:304)).
- Forráseszköz: `/dev/sda` ([lstree.py:353](lstree.py:353)), `part_start = 0x100000`
  (1 MiB, a szokásos partícióigazítás) és `blksize = 4096` ([lstree.py:6-7](lstree.py:6)).
- Kimenet: a `MENTES/` könyvtár alá építi fel a fát ([lstree.py:463](lstree.py:463)).
  A `MENTES` mappát előre létre kell hozni.

```bash
mkdir MENTES
```

```bash
python3 lstree.py > lstree.log
```

> ⚠️ A `copyfile` alapértelmezésben **`write=False`**, és a `printree` így hívja
> ([lstree.py:455](lstree.py:455)), vagyis a szkript jelenleg csak *száraz futást* végez:
> létrehozza a könyvtárakat, beolvassa a fájlok adatait és a végén kiírja, hány MB lenne
> visszaállítható (`X of Y MBytes recovered`), de fájlokat nem ír. Tényleges mentéshez a
> hívásban `write=True` kell.

### Működés

**1. MFT beolvasása** ([lstree.py:304-330](lstree.py:304)) – 1024 bájtos rekordonként:
- Ha a rekord nem `FILE`-lal kezdődik, megpróbálja 512 bájttal eltolva (a kimentésben
  elcsúszott szektorok miatt). Ha az eltolt rekord után közvetlenül újabb `FILE` jön, a
  rekord csonka – ilyenkor a második felét nullákkal pótolja (kis fájloknál így is működik).
- Ellenőrzi, hogy a rekordban tárolt MFT-szám egyezik-e a pozícióval (`wrong ID`).

**2. Rekord feldolgozása** (`parse_MFT`, [lstree.py:170](lstree.py:170)):
- fixup-javítás (hiba esetén figyelmeztet, de folytatja);
- `$FILE_NAME` → név és szülő (hosszú név előnyben);
- `$ATTRIBUTE_LIST` (0x20) → ha a fájl `$DATA` attribútuma más MFT-rekordokban folytatódik,
  azok számát a `c` (children) listába gyűjti;
- nem rezidens `$DATA` / `$INDEX_ALLOCATION` → méret, tömörítési egység mérete (`cs`,
  jellemzően 64 KiB) és a dekódolt run-lista, bájtpozíció/hossz párokként.

**3. Fa felépítése** ([lstree.py:336-349](lstree.py:336)) – minden rekordot a szülője `c`
listájába tesz; amelyiknek a szülője nem ismert, gyökérként marad a `keys` listában.

**4. Bejárás és másolás** (`printree`, `copyfile`, [lstree.py:355-461](lstree.py:355)):
- könyvtárnál `mkdir`, majd rekurzió a gyerekekre;
- ha a fájlnak nincs saját run-listája, de vannak attribútumlistás gyerekrekordjai, azok
  run-listáit fűzi össze;
- a fájlt a `copyfile` másolja ki, a tömörítetteket is (lásd a következő részt).

### Tömörített fájlok helyreállítása (`copyfile`, [lstree.py:355](lstree.py:355))

Az NTFS a tömörített fájlt **tömörítési egységekre** osztja (jellemzően 16 klaszter =
64 KiB). Minden egységet külön tömörít. Ha a tömörítés nem hoz nyereséget, az egység
tömörítetlenül marad. Tömörített egységnél a run-listában egy rövidebb adatfutás, majd egy
sparse „kitöltő” futás áll, a kettő együtt adja ki az egységet.

Tömörített fájlnak az számít, amelynek `$DATA` attribútumán be van állítva a tömörítés
jelzője. Ekkor a `parse_MFT` beírja az egységméretet (`cs`, [lstree.py:291](lstree.py:291)).
A `copyfile` futásonként dönt ([lstree.py:369](lstree.py:369)):

- **legalább egy egységnyi adatfutás:** a teljes egységeket nyersen másolja (ezek
  tömörítetlenek);
- **egységnél rövidebb maradék:** tömörített egység – beolvassa, nullákkal kiegészíti az
  egység méretére, és az `lznt1.decomp2` kitömöríti ([lstree.py:391](lstree.py:391));
- **utána jövő sparse futás:** az egység kitöltése, ezt átugorja; ha egy egységnél
  hosszabb, a többletet nullás egységekként írja ki;
- **önálló sparse futás:** nullákat ír.

A végén a fájlt a pontos méretre vágja.

Korlátok:

- Csak a szabályos mintát ismeri: egy tömörített egység = **egy** adatfutás + **egy**
  sparse kitöltő futás. Ha egy tömörített egység a lemezen két darabban van:
  - Ha a második darab is adatfutás, `not sparse block after compressed` hibát ír
    ([lstree.py:382](lstree.py:382)), mégis kitöltésnek veszi. Így egy valódi adatfutás
    kimarad, és a fájl további része elcsúszik.
  - A `missing sparse block` ágban a kitömörítés a hiányzó darab nélkül fut.
- Hibás tömörített egységnél (`wrong decompressed blocksize`, [lstree.py:393](lstree.py:393))
  a nyers, tömörített bájtokat írja ki. A fájl mérete nem csúszik el, de az adott egység
  tartalma hibás lesz.

### Sérült run-listák javítása (`decode_run1`, [lstree.py:9](lstree.py:9))

A run-lista minden eleme egy fejléc-bájt (alsó 4 bit: hossz mező mérete, felső 4 bit:
eltolás mező mérete), majd a hossz és az előző futáshoz képesti klaszter-eltolás.
Tömörített fájlnál a minta szabályos: minden adatfutást egy sparse futás követ, amely a
tömörítési egység többszörösére egészíti ki. A dekóder ezt ellenőrzi (`pad mismatch`,
`pad zero`, `pad nonzero` hibák), és `tryfix=True` esetén megpróbálja kijavítani az elrontott
bájtokat:

- hiányzó kitöltő futás → `01 <pad>` beszúrása;
- sérült adatfutás-fejléc → `11 <hossz>` feltételezése, ahol a hosszt a következő futás
  mintájából találja ki;
- utolsó adatfutás → a hossz a fájl ismert méretéből hiányzó rész;
- eltérő kitöltés → `01 <pad>` + `21`/`11` fejléc kipróbálása.

Minden javítási kísérlet után a lista hátralévő részét újradekódolja, és csak akkor fogadja
el, ha az hibátlanul végigmegy. A `parse_MFT` ezt tömörített fájloknál használja
(tömörítési egység = `1 << compr` klaszter). Ha a javított lista nem dekódolható végig
pontosan a VCN-tartomány méretére (`RUNlist FIXED` helyett `RUNlist CantFIX`), akkor
visszaáll a tömörítés-ellenőrzés nélküli sima dekódolásra. Így egy tömörítési egységen belül
töredezett, de egyébként ép run-lista sem vész el. A `decode_runs` függvény egy korábbi,
szöveges logot feldolgozó változat maradványa, jelenleg nincs meghívva.

---

## lznt1.py

### Modulként

- `decompress(buf)` – szabványos LZNT1 kitömörítés, 4 KiB-os chunkokban.
- `decomp2(buf, compr)` – szigorúbb változat helyreállításhoz: csak az érvényes
  chunk-fejléceket (4 KiB chunkméret jelzés) fogadja el, az első érvénytelennél megáll, és
  `(kitömörített_adat, felhasznált_bemeneti_bájtok)` párt ad vissza. Kivétel esetén
  `(buf, -1)`. Ezt használja az `lstree.py` a tömörített egységekhez.

### Önállóan futtatva

Egy nyersen (klaszterenként, run-lista nélkül) kimentett tömörített fájlt állít helyre
([lznt1.py:93-129](lznt1.py:93)). A fájlneveket, a végső méretet és a tömörítési egységet a
kódban kell megadni (`docfix.doc.NT` → `docfix.doc`, `size`, `compr=65536`).

```bash
python3 lznt1.py
```

Egységenként eldönti, mi van az adott pozíción:
- **nullás kitöltés** → 4 KiB-ot továbblép;
- **tömörített egység** (sikeres kitömörítés pontosan 64 KiB-ra) → kiírja, és a
  felhasznált bájtokat 4 KiB-ra kerekítve lép tovább;
- egyébként **tömörítetlen egység** → 64 KiB-ot nyersen átmásol.

A végén a kimenetet a megadott méretre vágja.

---

## Hasznos háttéranyag

- NTFS adatszerkezetek: [libfsntfs dokumentáció](https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc)
- MFT fixup: <https://dtidatarecovery.com/ntfs-master-file-table-fixup/>
