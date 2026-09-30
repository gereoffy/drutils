# lsindx + indxrename – könyvtárfa és fájlnevek visszaállítása INDX blokkokból

Két, együtt használandó Python szkript egy olyan NTFS kötet mentéséhez, amelynél az MFT
(Master File Table) nagy része elveszett vagy sérült. Eredetileg egy 16 GB-os NTFS pendrive
mentéséhez készült.

Az alapötlet: a könyvtárak `INDX` blokkjai (a `$INDEX_ALLOCATION` attribútum adatai) az MFT-n
**kívül**, a kötet adatterületén vannak, és minden bejegyzésük tartalmazza a benne lévő fájl
teljes `$FILE_NAME` rekordját: **név, szülőkönyvtár MFT-száma, módosítási idő, méret**.
Így akkor is visszaépíthető a könyvtárfa és a fájlnevek listája, ha maguk az MFT-rekordok
elvesztek. A név nélküli, nyers (carving) visszaállításból – TestDisk/PhotoRec – származó
fájlokat utána **méret** és a fájlformátumból kinyerhető **dátum** alapján lehet a
listában szereplő eredeti nevekhez és helyekhez rendelni.

| Fájl | Szerep |
|---|---|
| [lsindx.py](lsindx.py) | A teljes image-et végigszkenneli `FILE` (MFT) és `INDX` rekordokért, felépíti a könyvtárfát és a fájllistát, kérésre (`--restore`) visszamásolja az ép MFT-rekordú fájlokat, és külön kérésre (`--delete-from-device`) **kinullázza** azok klasztereit az eszközön. |
| [fixoverlay.py](fixoverlay.py) | A PhotoRec `report.xml` alapján megadja a visszaállított fájlok helyét a lemezen, kimenti a fájl utáni részt (`.overlay`), és a PhotoRec által levágott ismert utófarkot (Samsung SEF-blokk, `0xFF` kitöltés) visszaírja a fájlok végére. |
| [dupfill.py](dupfill.py) | Az `indxrename.py` után a több helyre felmásolt képek hiányzó példányait hard linkkel pótolja. |
| [indxrename.py](indxrename.py) | A PhotoRec által név nélkül visszaállított fájlokat az `INDEX.pck` alapján (méret, kiterjesztés, Office-metaadatból kinyert dátum) párosítja az eredeti nevekkel, és a helyükre mozgatja őket. |

A tömörített fájlok és a kimentett `$MFT` alapú mentés egy külön eszköz feladata, lásd:
[LSTREE.md](LSTREE.md).

---


## Munkafolyamat (pendrive-mentés)

```
 pendrive ──dd/ddrescue──▶ raw3x.img (MÁSOLAT!)
                               │
                               ▼
              lsindx.py --scandisk raw3x.img
          (egy menet, folytatható → SCAN.dat)
                               │
                               ▼
                   lsindx.py (a SCAN.dat-ból)
            ┌──────────────────┼──────────────────────────┐
            ▼                  ▼                          ▼
   könyvtár- és           INDEX.pck               ép MFT-rekordú fájlok
   fájllista (stdout,     (méret → [név, idő,     visszamásolva a fába
   „find .” szerűen,      MFT#, szülő] +         (--restore), majd külön futással
   dir__N ismeretlen      szülő → útvonal)       nullázva (--delete-from-device)
   szülőkhöz)
                               │                          │
                               │                          ▼
                               │              PhotoRec (TestDisk) raw scan
                               │              a nullázott image-en
                               │                          │
                               ▼                          ▼
           indxrename.py: méret + kiterjesztés + formátumból kinyert dátum
                               │
                               ▼
         név nélküli fájlok átnevezve/áthelyezve az eredeti név és könyvtár alá
```

A nullázás célja, hogy a nyers szkennelés már csak azokat a fájlokat találja meg,
amelyeket az MFT alapján nem sikerült névvel együtt visszaállítani – így kevesebb a duplikátum
és a hamis párosítás. A nullázás csak a `--delete-from-device` kapcsolóval történik meg,
lásd a 8. lépést.

---

## lsindx.py

### Beállítás

A paraméterek a szkript elején, konstansként vannak ([lsindx.py:11-27](lsindx.py:11)):

| Változó | Alapérték | Jelentés |
|---|---|---|
| `BLKSIZE` | `4096` | Klaszterméret (és az `INDX` blokkméret) bájtban. |
| `MFTSIZE` | `1024` | MFT-rekord mérete. |
| `SCANPROGRESS` / `SCANLINE` | 1 GiB / 64 | Ennyi bájtonként egy progress karakter, ennyi karakterenként új sor. |
| `SCANCHAIN` | 64 | Ennyi egymás utáni `FILE` rekordtól számít MFT-láncnak (`M`), kevesebbnél `m`. |
| `SCANCHUNK` | 1 MiB | Egyszerre ennyit olvas az eszközről. 512 többszöröse, és nagyobb, mint `SCANMAXREC`. |
| `SCANALIGN` | 512 | Ekkora igazítással keresi a rekordokat. |
| `SCANMAXREC` | 64 KiB | Legnagyobb elfogadott rekordméret. Ennyi átfedéssel olvas, hogy a blokkhatáron átlógó rekordok is meglegyenek. |
| `SCANCHECKPOINT` | 1 GiB | Ennyi olvasás után menti a folytatáshoz szükséges állapotot. |
| `SCANFILE` | `SCAN.dat` | A megtalált `FILE`/`INDX` rekordok nyers másolata. |
| `SCANPOS` | `SCAN.pos` | A szkennelés állapota (JSON): eszköz, meddig jutott, mekkora ekkor a `SCAN.dat`. |
| `SCANBAD` | `SCAN.bad` | Az olvashatatlan, nullával pótolt tartományok listája (`pozíció hossz` soronként). |
| `SCANERRBLK` | 4 KiB | Olvasási hibánál ekkora lépésekben olvassa a blokkot előre, majd visszafelé a hibáig. |
| `part_start` | `0` | A partíció kezdete az eszközön/image-ben bájtban (lásd lent, hogyan derül ki). |

Az eszközt vagy image-et nem a kódban kell megadni, hanem a `--scandisk` kapcsolóval.

### Futtatás

A szkript két lépésben dolgozik:

```
lsindx.py --scandisk <eszköz|image>   a lemez végigolvasása → SCAN.dat (folytatható)
lsindx.py [--restore] [--delete-from-device]
                                      a SCAN.dat feldolgozása → könyvtárfa, INDEX.pck
```

| Kapcsoló | Mit csinál | Eszköz megnyitása |
|---|---|---|
| *(nincs)* | Könyvtár- és fájllista az stdout-ra, `INDEX.pck`. Semmit nem hoz létre a lemezen. | nem nyitja meg |
| `--restore` | Ezen felül létrehozza a könyvtárfát, és visszamásolja az ép MFT-rekordú fájlokat (7. lépés). | csak olvasásra (`rb`) |
| `--delete-from-device` | Kinullázza az MFT alapján visszaállítható fájlok klasztereit (8. lépés), ellenőrzés nélkül. | **írásra** (`r+b`) |

A két kapcsoló együtt is megadható, de a javasolt menet az, hogy előbb csak `--restore`-ral
futtatod, **ellenőrzöd a mentést**, és csak utána, külön futással jön a
`--delete-from-device`. A törlés nem másol újra semmit, és a másolatokat sem ellenőrzi.

**1. Szkennelés** (`scan_device`, [lsindx.py:288](lsindx.py:288)) – a lemezt **egyetlen
menetben**, 1 MiB-os blokkokban olvassa végig. Minden blokkban megkeresi az 512 bájtra
igazított rekordokat:

- **`FILE`** (MFT-rekord): a méretét a headerből veszi (a 28-as offseten lévő „allocated size”);
- **`INDX`** (könyvtár-indexblokk): a méretet szintén a headerből veszi (az index node header
  „allocated size” mezője + 24 bájt fejléc);
- **NTFS boot szektor** (a 3. bájttól `NTFS    `): 512 bájt. Ez az első és a tartalék boot
  szektort is megtalálja, amelyek a partíció elején és utolsó szektorában vannak.

Ha a headerben lévő méret értelmetlen (nem 2 hatványa 512 és 64 KiB között), az alapértelmezett
méretet használja: 1024 bájtot a `FILE`, 4096 bájtot az `INDX` rekordhoz. A blokkokat
64 KiB átfedéssel olvassa, így a blokk végén kezdődő, átlógó rekordok is teljes egészükben
bekerülnek. A lemez legvégén csonkán maradt rekord kimarad.

Minden rekordot nyersen hozzáír a `SCAN.dat`-hoz, rekordonként így:
`pozíció (8 bájt) + méret (4 bájt) + adat`. A keresés így nem függ a klaszter- és
rekordmérettől, és a partíció kezdetétől sem. A lemezt ezért elég **egyszer** végigolvasni,
ezekkel az értékekkel utána a feldolgozásnál lehet kísérletezni.

```bash
mkdir mentes && cd mentes
```

```bash
sudo pypy3 ../lsindx.py --scandisk /dev/sdX
```

A haladást az stdout-ra írja, gigabájtonként egy karakterrel:

| Karakter | Jelentés az adott GB-ban |
|---|---|
| `M` | MFT-lánc: legalább `SCANCHAIN` (64) egymás utáni `FILE` rekord, egyesével növő MFT-sorszámmal |
| `m` | csak kósza (láncon kívüli) `FILE` rekord, pl. régi másolat a `$LogFile`-ban vagy a pagefile-ban |
| `I` | INDX-rekord, `FILE` rekord nélkül |
| `.` | van benne adat, de nem talált rekordot |
| `0` | csupa nulla |
| `X` | olvasási hiba volt benne (lásd `SCAN.bad`) |

64 karakterenként új sort kezd, amelynek elején a pozíció áll GB-ban. A sor végére a
haladást, a sebességet és az addig talált rekordok számát írja:

```
       0 GB MmmMmmmIImmmmMmmmmmmmmmMm.00000000000000000000000000000000000000  64/120 GB  383 MB/s  FILE=461913 INDX=50724 NTFS=9
      64 GB 0000000000000000000000000000000000000000000000000000000.  120/120 GB  395 MB/s  FILE=461913 INDX=50724 NTFS=10
```

A karakterenkénti méret és a sor hossza a `SCANPROGRESS` és a `SCANLINE` konstanssal
állítható. A hibakimenetre csak a folytatás és a befejezés üzenete kerül.

Gigabájtonként menti a `SCAN.pos`-t. Ha a futás megszakad (Ctrl+C, áramszünet, leválasztott
lemez), ugyanezzel a paranccsal onnan folytatja, ahol az utolsó mentés volt. Az utána írt,
esetleg félig kiírt rekordokat a `SCAN.dat` végéről eldobja. Ha a szkennelés már kész,
ezt kiírja, és nem olvas újra. Másik eszközzel nem folytat egy meglévő `SCAN.dat`-ot;
újrakezdéshez mindkét fájlt törölni kell.

**2. Feldolgozás** – a `SCAN.dat`-ból dolgozik, kapcsoló nélkül a lemezt meg sem nyitja.
Tetszőleges alkalommal megismételhető, például a kód vagy a
`part_start` módosítása után:

```bash
pypy3 ../lsindx.py > lista.txt 2> lsindx.log
```

Az stdout-ra a `find .` kimenetéhez hasonló, rendezett listát ír: minden könyvtárat és fájlt
egy sorban, a teljes útvonalával. A gyökér `.`, ismeretlen szülőnél az útvonal `dir__<MFT#>`-mal
kezdődik:

```
./Windows/System32/drivers/etc
./Windows/System32/drivers/etc/hosts
dir__110037/...
```

A DOS 8.3 álneveket (`PROGRA~1`) kihagyja, ha a fájlnak a hosszú neve is ismert. A
diagnosztikai kiírások (`MFT#...`, `CRC error`, `BOOT`, a könyvtárlista MFT-számokkal, a
mérettel és dátummal bővített fájllista, `COPY`, `DELETE`) a hibakimenetre kerülnek.

Ha nincs `SCAN.dat`, kiírja, hogyan kell létrehozni. Ha a szkennelés még nem fejeződött be,
kiírja a folytatás parancsát.

(A shebang `pypy3`-at vár a sebesség miatt; sima `python3`-mal is fut, csak lassabban.)

> ⚠️ Az eszközt/image-et a szkenneléskor és a `--restore`-nál **csak olvasásra** nyitja meg
> (`rb`), írásra (`r+b`) kizárólag a `--delete-from-device`. Ezt a kapcsolót csak az image
> **másolatán** szabad használni, soha nem az eredeti lemezen.
>

> ⚠️ A `--restore` a könyvtárfát és a fájlokat az **aktuális könyvtárba** hozza létre, ezért
> üres munkakönyvtárból indítsd.

### Használat közvetlenül az eredeti lemezen

Ha nincs lehetőség image-et készíteni, a szkript az eszközről is tud olvasni. A fájlokat
csak olvassa, de a lemezt így is óvni kell:

- **Legyen csak olvasható, és ne legyen felcsatolva.** Linuxon a kernel szintjén is
  írásvédetté tehető:

  ```bash
  sudo blockdev --setro /dev/sdX
  ```

  Windowsra ne csatlakoztasd, mert felajánlhatja a `chkdsk` javítást, és az felülírhatja
  a megmaradt metaadatokat.
- **Eszköz és `part_start`:** a legegyszerűbb a partíció eszközét megadni a
  `--scandisk`-nek (pl. `/dev/sdX2`), ekkor `part_start = 0`. Ha a teljes lemezt adod meg, a `part_start` a
  partíció kezdete bájtban (`fdisk -l` vagy `lsblk` alapján). A „Partíció-eltolás
  meghatározása” rész (2. lépés) ezt ellenőrizni is segít.
- **Az állapot ellenőrzése előtte** (`smartctl -a /dev/sdX`): fizikailag hibás lemeznél
  minden teljes olvasás további kockázat. A szkript egyetlen menetben olvassa végig az
  eszközt, a PhotoRec pedig egy második alkalommal.
- **Olvasási hiba (bad sector):** ha egy 1 MiB-os blokk olvasása I/O hibát ad, a szkennelés
  nem áll le. A ddrescue-hoz hasonlóan a blokkot előbb az elejétől előre, majd a végétől
  visszafelé olvassa 4 KiB-os lépésekben, mindkét irányban az első hibáig. Linuxon ezt
  `O_DIRECT`-tel, a page cache megkerülésével teszi. Az újabb kernelek a blokkeszközt akár
  2 MiB-os page cache lapokban (folio) olvassák, és egy rossz szektor miatt az egész lap
  olvashatatlan lenne. Ez egy valódi lemezen elő is fordult: egyetlen rossz szektor miatt
  egy pontosan 2 MiB-os, igazított tartomány esett ki. Ahol nincs `O_DIRECT`, például
  macOS-en, sima `pread`-del olvas. A kettő közötti részt nem próbálja olvasni, hanem nullával tölti ki. Egy
  hibás blokk így legfeljebb két sikertelen 4 KiB-os olvasásba kerül, akárhány rossz szektor
  van benne, a blokk két szélén lévő jó adat pedig megmarad. Egy magányos rossz szektor csak
  4 KiB-ot, vagyis pár MFT-rekordot vagy egy INDX blokkot visz el. A nullával pótolt
  tartományokat a `SCAN.bad`-be írja, a progressben `X` jelzi őket. A sor végi statisztikában
  `BAD=... KB` áll, a végén pedig a hibakimenetre kerül az összesítés. A sérült rekordok
  bekerülnek a `SCAN.dat`-ba, a feldolgozás a fixup-ellenőrzésnél kiszűri őket (`CRC error`).
  Rossz szektoros lemeznél minden olvasás további kockázat, és a hibás blokkok újraolvasása
  lassú lehet.
- **Megszakadás:** a futás a legutóbbi gigabájtos mentéstől folytatható. A `SCAN.bad`-hez
  ilyenkor hozzáír, így a mentés és a leállás közötti hibás tartományok kétszer is
  szerepelhetnek benne.
- **Futásidő:** 4 TB-nál a szkennelés sok óra. A feldolgozás már csak a `SCAN.dat`-ot
  olvassa, ezért gyors, és bármikor megismételhető.
- **A kimenet** (az aktuális könyvtár, `SCAN.dat`, `INDEX.pck`, visszamásolt fájlok) és a
  PhotoRec kimenete is **másik lemezre** kerüljön.

### Működés lépésenként

A szkennelés után a feldolgozás így halad:

**0. Boot szektorok** ([lsindx.py:401](lsindx.py:401)) – a `SCAN.dat`-ban talált összes NTFS
boot szektor adatait kiírja: szektorméret, klaszterméret, MFT- és INDX-rekordméret, kötetméret,
az MFT klaszterszáma, valamint a belőle adódó `part_start`. Ez utóbbi a boot szektor
pozíciója, ha az első boot szektorról van szó. Ha a tartalékról, akkor a pozíció mínusz a
kötet mérete.

```
BOOT at 0xC800200: sector=512 cluster=4096 MFTrec=1024 INDXrec=4096 volume=184 MB MFT@LCN 786432  =>  part_start=0xC800200 (ha elso)  / 0x1000000 (ha tartalek)
```

Ha a lemez eleje hiányzik, a tartalék boot szektorból derül ki a `BLKSIZE`, a `MFTSIZE` és a
`part_start`, amelyeket a szkript elején kell beállítani. Ezekhez a feldolgozás újrafuttatása
elég, a lemezt nem kell újra szkennelni.

A `part_start` előtt talált `FILE` és `INDX` rekordokat a feldolgozás figyelmen kívül hagyja.
Ezek egy korábbi partícióhoz tartoznak (pl. Recovery vagy EFI), vagy más szemétnek számítanak,
és a saját MFT-számaikkal összekevernék a könyvtárfát. Ha a teljes lemezről készült a
`SCAN.dat`, így egy korábbi partíció is feldolgozható, a `part_start` átállításával. A
partíció végével a szkript nem foglalkozik, a lemez végéig minden rekordot feldolgoz.

**1. MFT-rekordok feldolgozása** ([lsindx.py:412-414](lsindx.py:412)) – a `SCAN.dat` minden
`FILE` rekordját feldolgozza (`parse_MFT`):

- Ellenőrzi a méreteket, és elvégzi a *fixup* (update sequence) javítást: az NTFS minden
  szektor utolsó 2 bájtját egy ellenőrző értékre cseréli, az eredetit a rekord fejlécében
  tárolja. Hibás fixup esetén a rekordot eldobja.
- A `$FILE_NAME` (0x30) attribútumból kiveszi a szülőkönyvtár MFT-számát, a módosítási időt
  és a nevet. Ha több név van, a nem-DOS (hosszú) nevet részesíti előnyben.
- Nem rezidens attribútumoknál dekódolja a run-listát (klaszter-futásokat):
  - `$DATA` (0x80, név nélküli): ha a rekord használatban van, nem könyvtár, nem tömörített,
    a run-lista összege egyezik a foglalt mérettel és 1 GB alatti, akkor bekerül a
    **közvetlenül visszaállítható** fájlok közé (`mftfiles`).
  - `$INDEX_ALLOCATION` (0xA0): a könyvtár első `INDX` blokkjának helyét jegyzi fel
    (`mftpos`) – ez a partíció-eltolás meghatározásához kell (lásd 2. pont).
- A fájlok a `filedata[méret]` listába, a könyvtárak a `dirlist[MFT#] = (név, szülő)`
  szótárba kerülnek.

**2. INDX blokkok feldolgozása** ([lsindx.py:416-418](lsindx.py:416)) – a `SCAN.dat`
minden `INDX` rekordját feldolgozza (`parseindx`):

- Fixup-javítás mind a 8 szektorra; hiba esetén „CRC error!” és a blokk kimarad.
- A bejegyzéseket a blokk **teljes foglalt méretéig** olvassa, nem csak a használt rész
  végéig – így a slack területen maradt régi, törölt vagy átnevezett bejegyzések is
  előkerülnek.
- Minden bejegyzésből: fájl MFT-száma, szülő MFT-száma, módosítási idő, méret, attribútumok,
  név. Könyvtárak (`0x10000000` flag) → `dirlist`; fájlok → `filedata[méret]`.
- Ha egy könyvtár az MFT-ből és INDX-ből is ismert, de eltér a név/szülő, kiírja:
  `MFT!=INDX mismatch: ...`.
- **Partíció-eltolás meghatározása:** ha egy könyvtárnak az MFT-rekordja is megvan, kiírja
  az INDX blokk tényleges pozícióját az image-ben és az MFT szerinti (partíció-relatív)
  helyét, valamint a kettő különbségét:

  ```
  MFT#1234 = 0x1A2B3000  vs.  0x1A2AC000    offs=0x7000
  ```

  Ez az `offs` a `part_start` helyes értéke. Érdemes először egy próbafutással ezt
  kideríteni, beállítani, és csak utána futtatni élesben.

**3. Könyvtárfa felépítése** ([lsindx.py:424-443](lsindx.py:424)) – `get_path` a szülő-láncot
a gyökérig (MFT#5, amelynek neve `.`) követi. Ha a lánc egy ismeretlen könyvtárnál megszakad
vagy hurokba fut, annak helyén `dir__<MFT#>` áll. A könyvtárakat csak `--restore` esetén hozza
létre (`os.makedirs`).

Egy könyvtár nevét az MFT-rekordja és a szülő INDX blokkja is megadhatja, sokszor hosszú és
DOS 8.3 névvel is. Mindig a hosszú név nyer: az MFT-ből vagy az INDX-ből kapott DOS nevet
egy később talált hosszú név felülírja.

**4. Fájllista a naplóba** ([lsindx.py:445-448](lsindx.py:445)) – az 1024 bájtnál nagyobb
fájlokat méret szerint rendezve kiírja a hibakimenetre:

```
<méret> <unix idő> <fájl MFT#>/<szülő MFT#> "<útvonal/név>"
```

**5. `INDEX.pck` mentése** ([lsindx.py:450-454](lsindx.py:450)) – előtte a kis fájlok
szülőkönyvtáraihoz is kiszámolja az útvonalat, lásd lent.

**6. Könyvtár- és fájllista** ([lsindx.py:456-468](lsindx.py:456)) – a `find .`-szerű lista az
stdout-ra (lásd a Futtatásnál).

**7. Visszamásolás** – csak `--restore` esetén ([lsindx.py:473](lsindx.py:473)). A
`SCAN.pos`-ban tárolt eszközt nyitja meg, csak olvasásra. Az `mftfiles` fájljait a
run-listájuk alapján kimásolja a helyükre, a méretre vágja, és beállítja a módosítási időt.
Log: `COPY <bájt> bytes to <útvonal>  (<n> runs)`.

**8. Nullázás** – csak `--delete-from-device` esetén ([lsindx.py:487](lsindx.py:487)).
Az összes MFT alapján visszaállítható fájl klasztereit nullákkal felülírja az eszközön (a
sparse futásokat kihagyja). Log: `DELETE <bájt> bytes of <útvonal>`.

> ⚠️ A törlés nem olvassa újra sem a mentést, sem a lemezt, és a `--restore` másolatait sem
> ellenőrzi. Ezért előtte a mentést ellenőrizni kell. Ha egy fájl visszamásolása nem
> sikerült, a lemezen lévő adata a törléssel végleg elvész.

### Az `INDEX.pck` formátuma

```python
filedata, dirmap = pickle.load(open("INDEX.pck", "rb"))
```

- `filedata`: `dict[int, list[tuple]]` – kulcs a fájlméret bájtban, érték az ilyen méretű
  ismert fájlok listája, elemenként `(méret, név, mtime_unix, fájl_MFT#, szülő_MFT#)`.
  Ugyanaz a fájl többször is szerepelhet (MFT-ből és INDX-ből is, illetve hosszú és DOS
  8.3 névvel is).
- `dirmap`: `dict[int, str]` – szülő MFT# → a könyvtár relatív útvonala.
  A `filedata` összes fájljának szülőkönyvtára benne van.
  Ha a szülő-lánc megszakad, az útvonal `dir__<MFT#>`-mal kezdődik.

Az `INDEX.pck`-t az [indxrename.py](#indxrenamepy) használja fel.

### Ismert korlátok (lsindx.py)

- A szkennelés tetszőleges (512 és 64 KiB közötti) rekordméretet és 512 bájtra igazított
  partíciókezdetet kezel. A feldolgozás viszont a `MFTSIZE`-nál eltérő méretű MFT-rekordokat
  eldobja, és a fixup-javításnál 512 bájtos szektort feltételez. Az MFT-rekordoknál
  ráadásul pontosan 2 szektort. Más értékeknél ezeket a kódban kell átállítani.
- A tömörített, töredezett (attribútumlistás) és sparse fájlokat nem másolja vissza
  közvetlenül; ezeket a nyers szkennelésnek kell megtalálnia (vagy az
  [lstree.py](LSTREE.md)-nak, ha van használható `$MFT`). A sparse futásokat (0-s pozíció) a másolás nullákkal tölti ki, a
  nullázás pedig kihagyja őket.
- Az MFT fájl-referenciákból csak az alsó 32 bitet használja.

---

## indxrename.py

A PhotoRec név nélküli kimenetét (`recup_dir.N/f1234567.doc` és hasonló fájlok)
az `lsindx.py` által készített `INDEX.pck` alapján az eredeti nevükön, az eredeti
könyvtárukban teszi elérhetővé, **hard linkként**. A PhotoRec-féle fájl a helyén marad.

### Függőség

```bash
pip3 install olefile
```

### Futtatás

Az `lsindx.py` **kimeneti könyvtárában** kell futtatni: itt van az `INDEX.pck`, és a
`dirmap`-ben tárolt relatív útvonalak is innen érvényesek. A célkönyvtárat a link
létrehozása előtt maga hozza létre, előre létrehozott könyvtárfa nem kell.
A párosítandó fájlokat parancssori argumentumként kapja:

```
indxrename.py [--alldate] [--larger] [--neighbor] [--report report.xml] [--tz N] [--tol N] fájl...
```

| Kapcsoló | Jelentés |
|---|---|
| *(nincs)* | **Legszigorúbb mód:** csak akkor, ha a méret pontosan egyezik, **és** a dátum is egyezik: ±2 másodperc, vagy pontosan 1–2 óra időzóna-eltérés ±2 másodperccel. |
| `--alldate` | A dátumot nem vizsgálja, de a méretnek pontosan egyeznie kell. Több jelölt közül a legközelebbi dátumú nyer. |
| `--larger` | Az eredeti **nagyobb** is lehet a visszaállított fájlnál (levágott utófarok, lásd a 4. lépést). A dátumnak ekkor is egyeznie kell. |
| `--neighbor` | Azonos méret, de nem egyező dátum esetén a lemezszomszéd igazolja a párosítást (lásd a 3. lépést). `--report` kell hozzá. |
| `--report report.xml` | A PhotoRec `report.xml`-je: ebből tudja a `--neighbor` a lemezen elfoglalt sorrendet, a `--larger` pedig előnyben részesíti azokat a jelölteket, amelyek beférnek a következő visszaállított fájl kezdetéig (lásd a 4. lépést). |
| `--tz N` | Legfeljebb `N` óra időzóna-eltérést enged meg (alapból 2). |
| `--tol N` | A dátumegyezés tűrése `N` másodperc (alapból 2). Egyes fényképezőgépek a fájlt pár másodperccel a felvétel után írják ki, ilyenkor az INDX-idő rendszeresen 6–9 másodperccel későbbi az EXIF-nél. |

A kapcsolóknak a fájlnevek előtt kell állniuk. Kapcsoló vagy fájl nélkül, illetve ismeretlen
kapcsolóval a szkript kiírja a használatot, és kilép.

```bash
python3 ../indxrename.py /mentes/photorec/recup_dir.*/* > indxrename.log
```

Sok fájlnál a shell argumentumlista-korlátja miatt érdemesebb `find`-dal:

```bash
find /mentes/photorec -type f -exec python3 ../indxrename.py {} + >> indxrename.log
```

> ⚠️ A fájlokat nem mozgatja, hanem **hard linket** készít róluk az új helyre (`os.link`). Ezért a
> PhotoRec kimenetének és a célfának ugyanazon a fájlrendszeren kell lennie. Egy fájl csak
> egy nevet kap: a már linkelt forrásfájlokat (`st_nlink > 1`) kihagyja, a naplóban `LINKED`
> jelzi őket. Így a szkript többször is lefuttatható. Egy elrontott menet után elég a
> célfa alkönyvtárait törölni: a forrásfájlok linkszáma visszaáll 1-re, és újra
> párosíthatók. A PhotoRec-féle fájlok nem változnak, kivéve, ha a `fixoverlay.py` vagy a
> `fixoverlay.py --dump … --do` visszaírta a végükre a levágott utófarkot.

### Működés

**1. A fájl adatainak megállapítása** (`fileinfo`, [indxrename.py:73](indxrename.py:73)):

- **méret**: a fájl mérete;
- **kiterjesztés**: a PhotoRec által adott fájlnév kiterjesztése (a PhotoRec ezt a formátum
  felismeréséből adja), normalizálva (lásd a 2. lépést);
- **dátum**: alapból a fájl mtime-ja. A PhotoRec ezt a legtöbb formátumnál a tartalomból
  állítja be (képeknél az EXIF alapján). Az Office-fájloknál nem teszi meg, ezért
  ezeknél a szkript maga olvassa ki a dátumot a dokumentum metaadataiból:
  - **ZIP-alapú** (`PK\x03\x04`: docx, xlsx, pptx) → `docProps/core.xml`, az összes `20`-szal
    kezdődő dátummező (létrehozás, módosítás, nyomtatás…) közül a **legkésőbbi**
    (`docxdate`, [indxrename.py:17](indxrename.py:17));
  - **OLE2** (`D0 CF 11 E0`: doc, xls, ppt) → a SummaryInformation *utolsó mentés* ideje,
    ennek hiányában a *létrehozásé*; csak akkor használja, ha 1997 utáni
    (`oledate`, [indxrename.py:41](indxrename.py:41)).

**2. Jelöltek keresése** ([indxrename.py:199-212](indxrename.py:199)) – a `filedata[méret]`
listából, azaz csak a **bájtra pontosan azonos méretű** ismert fájlok közül. Kihagyja:

- a `~`-mal kezdődő neveket (Office ideiglenes fájlok, pl. `~$level.docx`);
- azokat, amelyeknek a célhelyén már létezik fájl. Ez lehet egy `lsindx.py` által
  visszamásolt fájl vagy egy korábbi párosítás eredménye, így egy név csak egyszer osztható ki;
- az eltérő kiterjesztésűeket. A kiterjesztéseket mindkét oldalon kisbetűsíti és
  normalizálja (`EXT_ALIAS`, [indxrename.py:66](indxrename.py:66)), mert a PhotoRec
  egy formátumot mindig ugyanúgy nevez el, az eredeti fájl viszont más írásmóddal is
  szerepelhetett:

  | Eredeti | Ezzel egyezik |
  |---|---|
  | `jpeg`, `jpe`, `jfif` | `jpg` |
  | `tiff` | `tif` |
  | `htm` | `html` |
  | `pps` | `ppt` |
  | `ppsx` | `pptx` |
  | `mpeg` | `mpg` |

  Új párt az `EXT_ALIAS` szótárba lehet felvenni.

A maradék jelöltek közül azt választja, amelynek az `INDEX.pck`-ban tárolt módosítási
ideje a legközelebb van a fájlból kinyert dátumhoz.

**Levágott utófarok:** ha a PhotoRec levágta a fájl végét (Samsung SEF-blokk, `0xFF` kitöltés),
a pontos méret szerinti párosítás csak akkor működik, ha előbb a [fixoverlay.py](#fixoverlaypy)
vagy a `fixoverlay.py --dump … --do` visszaírta. Egy valódi mentésben a Samsung-fotók 98%-ánál a javított
méret pontosan egyezett egy INDX-bejegyzéssel. A HP M540 képeknél is pontosan egyezett, de ott
a fényképezőgép rosszul beállított órája miatt a dátum nem stimmelt. Ezeket csak az `--alldate`
párosítja.

**3. Párosítás** ([indxrename.py:213](indxrename.py:213)) – alapból a **legszigorúbb** módon: a fájl
csak akkor kap nevet, ha a mérete pontosan egyezik, **és** a dátuma is egyezik a jelölt
INDX-ben tárolt idejével (`date_ok`). Egyezőnek számít a ±2 másodpercen belüli eltérés, vagy
a pontosan 1–2 órás eltérés ±2 másodperccel. Az utóbbit az időzóna és a nyári idő okozza,
Office-fájloknál pedig az, hogy a `core.xml` UTC-ben tárol, de a `Z` levágása után helyi
időként értelmeződik. Egy valódi mentésben az INDX-idők nagyobb része pontosan, a többi
egész órányi eltéréssel egyezett. A megengedett órák száma `--tz N`-nel növelhető. Az
egyetlen azonos méretű jelölt önmagában nem elég, mert egy levágott fájl mérete véletlenül
egy egészen más fájléval is egyezhet.

Ha van azonos méretű jelölt, de a dátuma nem egyezik, a fájl a helyén marad: `SKIP` sort ír,
és utána kiírja a lehetséges neveket (`NAMES: [...]`). `--alldate` esetén a dátumot nem nézi,
és a legközelebbi dátumú azonos méretű jelöltet választja. Erre a rosszul beállított órájú
fényképezőgépeknél van szükség.

**Lemezszomszéd (`--neighbor`)** (`by_neighbor`, [indxrename.py:152](indxrename.py:152)) – sok fájlnál az
INDX-ben nem a felvétel ideje van, hanem az, amikor a képeket később a gépre másolták. Így a
dátum órákkal, napokkal, akár évekkel is eltérhet. `--neighbor` esetén az azonos méretű, de nem
egyező dátumú jelöltet akkor is elfogadja, ha a fájl **lemezszomszédjának** is van azonos
méretű jelöltje **ugyanabban a könyvtárban**, más néven. Lemezszomszéd a `report.xml` szerint
közvetlenül előtte vagy utána kezdődő PhotoRec-fájl, az előnézeti képeket átugorva. A
szomszéd tényleges méretével számol, vagyis a `fixoverlay.py` utáni mérettel, és a PhotoRec
kimenetében, a `report.xml` könyvtára alatt keresi meg. Ez azért működik, mert egy könyvtár
tartalma egyben került fel a lemezre, így a fájlok egymás mellé kerültek. Egy véletlen
méretegyezésnél a szomszéd nem esne ugyanabba a könyvtárba. Egy valódi mentésben a nem
egyező dátumú, azonos méretű jelöltek 99%-ánál a lemezszomszéd ugyanabba a könyvtárba esett,
és egy 400 fájlos mintából 397 így párosult. A naplóban `NEIGH(n/m)` jelzi.

**4. Nagyobb eredeti (`--larger`)** – csak akkor, ha nincs azonos méretű, dátum szerint egyező
szabad jelölt (`by_larger`, [indxrename.py:107](indxrename.py:107)). Arra az esetre való, amikor a
visszaállított fájl kisebb az eredetinél, mert a PhotoRec levágta a végét, és a
`fixoverlay.py` nem ismerte fel, például egy mozgóképes fotó videóját. A jelölt:

- azonos (normalizált) kiterjesztésű;
- legalább akkora, mint a visszaállított fájl;
- a dátuma a fenti szigorú feltétel szerint egyezik. Képeknél ezt a PhotoRec az EXIF-ből
  állítja be. Ahol nincs tartalomból vett dátum, a fájlidő a mentés ideje, és ilyen pontosan
  semmivel sem egyezik, így ezek maguktól kimaradnak.

Több jelölt közül a legkisebb méretkülönbségű nyer. Egy fájlnak csak az egyik nevét veszi
figyelembe, lehetőleg a hosszút a DOS alias helyett. A PhotoRec által kimentett beágyazott
előnézeti képeket (`t<szám>.jpg`) kihagyja, mert azok a teljes fotó dátumát kapják, de nem
maguk a fotók. Egy valódi mentésben a javítatlan Samsung-fotók kb. 88%-a így is megtalálta a
párját, pontosan 98 bájt méretkülönbséggel. A `fixoverlay.py` után azonban a pontos méret
szerinti párosítás jobb, mert a fájl is teljes lesz.

`--report report.xml` esetén felső korlátot is figyelembe vesz. A PhotoRec `report.xml`-jéből
tudható, hol ér véget a visszaállított fájl a lemezen, és hol kezdődik a következő
visszaállított fájl. Egy nem töredezett eredeti fájl legfeljebb ekkora lehetett (a méret
plusz a kimaradt bájtok). A korláton belüli jelöltek elsőbbséget kapnak. Ha csak a korláton
kívüli jelölt van, azt is elfogadja az időegyezés alapján, de a naplóban `LARGERX` jelzi.
Ilyenkor az eredeti nagyobb volt, mint ami a következő fájlig elfér: jellemzően mozgóképes
fotó, amelynek a videóját a PhotoRec külön fájlként állította vissza, vagy egy olyan kép,
amelynek a PhotoRec csak az elejét találta meg. A `report.xml`-ben a fájlokat a PhotoRec által
adott névvel (`f<szektor>.jpg`) keresi, így akkor is működik, ha a fájlokat közben más
könyvtárba helyezted át.

A `--larger`-t a pontos méret szerinti menetek **után** érdemes futtatni. Ha a PhotoRec egy
képből egy teljes és egy csonka változatot is visszaállított, így a teljes változat kapja meg a
nevet a pontos mérete alapján.

### Javasolt használat: több menetben, fontossági sorrendben

A szkriptet nem egyszerre érdemes az összes fájlra ráengedni, hanem sokszor egymás után.
Mindig a legfontosabb fájltípusokkal kell kezdeni, és úgy haladni a többi felé:

0. **Előtte** a levágott utófarkok visszaírása (`fixoverlay.py --report … --dump … --do`, vagy a már
   kimentett `.overlay`-ekből a `fixoverlay.py --do`), hogy a pontos méret szerinti párosítás működjön.

1. **Alapmód** (kapcsoló nélkül), a legértékesebb típusokkal kezdve: először a nagy méretű
   Office-fájlok, aztán a fotók (JPEG), és így tovább. Például:

   ```bash
   find /mentes/photorec -type f \( -name '*.docx' -o -name '*.xlsx' -o -name '*.doc' -o -name '*.xls' \) -size +1M -exec python3 ../indxrename.py {} + >> indxrename.log
   ```

   ```bash
   find /mentes/photorec -type f -name '*.jpg' -exec python3 ../indxrename.py {} + >> indxrename.log
   ```

2. **Nagyobb eredeti (`--larger`)** a pontos méret szerinti menetek után:

   ```bash
   find /mentes/photorec -type f -name '*.jpg' -exec python3 ../indxrename.py --larger --report /mentes/photorec/report.xml {} + >> indxrename.log
   ```

3. **Lemezszomszéd (`--neighbor`)** a maradékra, azonos mérettel, de a dátum helyett a
   szomszéd könyvtára alapján:

   ```bash
   find /mentes/photorec -type f -name 'f*.jpg' -links 1 -exec python3 ../indxrename.py --neighbor --report /mentes/photorec/report.xml {} + >> indxrename.log
   ```

   A `-links 1` csak a még párosítatlan fájlokat adja át.

4. **Dátum nélkül (`--alldate`)** csak célzottan, ami a `--neighbor` után is megmaradt, például egy rosszul beállított órájú
   fényképezőgép képeire. A méretnek itt is pontosan egyeznie kell, de a véletlen
   méretegyezés esélye nagyobb.

   ```bash
   find /mentes/photorec/_JPG_HP -type f -exec python3 ../indxrename.py --alldate {} + >> indxrename.log
   ```

Ez azért működik jól, mert egy név **csak egyszer osztható ki**: ha a célhelyen már van
fájl, azt a nevet a szkript kihagyja. A korábbi, szigorúbb menetekben biztosan párosított
fájlok így lefoglalják a nevüket, és a későbbi, lazább menetek már csak a megmaradt
jelöltek közül választhatnak. Ez a mohó párosítás hátrányát is nagyrészt kiküszöböli.

Fényképezőgépről lemásolt fotóknál az EXIF-dátum és a fájl dátuma általában azonos. Ezt
az időt az INDX is tárolja, a PhotoRec pedig az EXIF-ből állítja be, így a fotók alapmódban is
jól párosíthatók.

### Kimenet

```
<dátum> <méret> <fájl> OK(<jelöltek>/<összes>) <kit.> <eltérés mp> <új útvonal>
<dátum> <méret> <fájl> NEIGH(<jelöltek>/<összes>) <kit.> <eltérés mp> <új útvonal>
<dátum> <méret> <fájl> SKIP(<jelöltek>/<összes>) <kit.> <eltérés mp> <legjobb jelölt>
NAMES: [<lehetséges útvonalak>]
<dátum> <méret> <fájl> LARGER(<jelöltek>) <kit.> <méretkülönbség bájt> <új útvonal>
<dátum> <méret> <fájl> LARGERX(<jelöltek>) <kit.> <méretkülönbség bájt> <új útvonal>
<fájl> LINKED
<dátum> <méret> <fájl> BAD(<szabad nevek>/<összes>) [<filedata bejegyzések>]
<dátum> <méret> <fájl> UNKNOWN
```

- `OK(n/m)`: `m` darab ismert fájl ilyen méretű, ebből `n` szabad, egyező kiterjesztésű és
  (`--alldate` nélkül) dátum szerint is egyező. Az `1/1` biztos találat.
- `SKIP(n/m)`: van `n` azonos méretű szabad jelölt, de a dátuma nem egyezik, ezért a fájl a
  helyén marad. Egy későbbi `--neighbor` vagy `--alldate` menet még párosíthatja.
- `NEIGH(n/m)`: azonos méret, a dátum nem egyezik, de a lemezszomszéd ugyanabban a
  könyvtárban van (`--neighbor`).
- Ha egy mérethez több bejegyzés tartozik, előtte tabulált sorokban kiírja az összes
  kiterjesztés-egyező jelöltet a dátumeltéréssel együtt, ami utólagos kézi ellenőrzéshez
  hasznos.
- `BAD`: van ilyen méretű ismert fájl, de egyik sem jöhet szóba (foglalt, ideiglenes vagy más
  kiterjesztésű).
- `LARGER(n)`: `--larger` esetén egy nagyobb, dátum szerint egyező eredetihez linkelve. `n` a
  szóba jöhető fájlok száma, a szám a méretkülönbség bájtban.
- `LARGERX(n)`: mint a `LARGER`, de `--report` szerint az eredeti nem fért volna el a következő
  visszaállított fájl kezdetéig. Érdemes utólag ellenőrizni.
- `LINKED`: a fájl már kapott nevet egy korábbi menetben, ezért kihagyja.
- `UNKNOWN`: nincs ilyen méretű fájl az indexben (és `--larger` esetén nagyobb sem).

### Tudnivalók, korlátok

- A párosítás egy menetben **mohó**: a fájlokat az argumentumok sorrendjében dolgozza fel,
  és az első fájl kapja meg a számára legjobb nevet, akkor is, ha egy később jövőhöz még
  jobban illett volna. Ezt a fenti, több menetes használat nagyrészt kiküszöböli.
- Méret szerinti párosítás csak ott működik, ahol a PhotoRec a formátumból a **pontos**
  fájlméretet tudja meghatározni (pl. OLE2, ZIP). Levágott fájloknál a `fixoverlay.py` vagy a `--larger` segíthet,
  ha a fájlnak van tartalomból vett dátuma. Kitöltött (nagyobb) fájloknál `UNKNOWN` lesz
  az eredmény.
- A `--larger`-rel párosított fájlból hiányzik a levágott utófarok, ha a `fixoverlay.py` nem
  ismerte fel, például a mozgóképes fotók videója. A kép maga ép.
- A szkript maga csak az Office-formátumokból nyeri ki a dátumot, minden másnál a PhotoRec
  által beállított fájlidőt használja. Ha a PhotoRec egy formátumnál nem tud dátumot
  kinyerni, ott a fájlidő a mentés időpontja, így a dátum nem segít a választásban.
- Az index ideje a `$FILE_NAME` attribútumból származik. Ezt a Windows jellemzően csak
  létrehozáskor, átnevezéskor és mozgatáskor frissíti, ezért eltérhet a valódi utolsó
  módosítástól. Emiatt kell tűrés a dátum-összevetésnél.
- Ha a jelölt szülőkönyvtára nincs a `dirmap`-ben (régebbi `lsindx.py`-val készült
  `INDEX.pck`), a fájl a `dir__<szülő MFT#>` könyvtárba kerül. A célkönyvtárat szükség
  esetén létrehozza. Sikertelen link-létrehozásnál (pl. másik fájlrendszer) `LINK ERROR` sort ír,
  és folytatja a futást.
- Az új nevű fájl (hard link) a PhotoRec által beállított mtime-ot tartja meg, az eredeti időt
  nem állítja vissza.
- Sérült Office-fájlnál a dátum nem olvasható ki, ilyenkor a fájl mtime-ja számít.


---

## fixoverlay.py

A PhotoRec a JPEG végét az `FF D9` markernél zárja le, így levágja a fájl után fűzött adatot.
A `fixoverlay.py` ezt kezeli. A PhotoRec `report.xml`-jéből megállapítja, hol vannak a
visszaállított fájlok a lemezen. Kimenti a fájlok utáni részt, és az ismert utófarkot
visszaírja a fájl végére. Utána a fájl bájtra azonos az eredetivel, és az `indxrename.py` a
pontos méret szerint párosíthatja.

```
fixoverlay.py [--do] fájl...                                     a már kimentett <fájl>.overlay-ből
fixoverlay.py --report report.xml fájl...                        a fájl helye és a kimaradt bájtok
fixoverlay.py --report report.xml --dump <eszköz> fájl...        a fájl utáni rész kimentése: <fájl>.overlay
fixoverlay.py --report report.xml --dump <eszköz> --do fájl...   ismert utófarok visszaírása, a többi .overlay-be
```

`--do` nélkül semmit nem módosít, csak kiírja, mit csinálna. A `--dump`-hoz, vagyis az eszköz
olvasásához, root kell.

**A `report.xml`** (`load_report`, [fixoverlay.py:31](fixoverlay.py:31)) a PhotoRec kimeneti könyvtárában jön
létre, és minden visszaállított fájlról tartalmazza a nevét (`f<szektor>.<kit.>`), a méretét és a
lemezen elfoglalt helyét (`byte_run`). `--report` esetén minden megadott fájlra, a neve alapján,
kiírja:

```
<fájl> start=<lemez eleje> end=<lemez vége> gap=<kimaradt bájtok> size=<méret> runs=<futások>
```

A `gap` a fájl vége és a következő visszaállított fájl kezdete közötti bájtok száma. A fájl
tartományán belül kezdődő fájlokat, például a beágyazott előnézeti képeket, a keresés kihagyja.
Nem töredezett fájlnál (`runs=1`) az eredeti fájl legfeljebb `size+gap` bájtos lehetett. Ha a
fájl nem szerepel a `report.xml`-ben, `NOT IN REPORT` sort ír. A `load_report` függvényt az
`indxrename.py --report` is használja, ezért a két szkriptnek ugyanabban a könyvtárban kell
lennie.

**`--dump <eszköz>`**: a fájl utáni részt a következő fájl kezdetéig, de legfeljebb 256 KB-ot
(`TAILMAX`) kimenti a fájl mellé `<fájl>.overlay` néven. A töredezett fájlokat kihagyja.
`--do`-val együtt az ismert utófarkot rögtön visszaírja a fájl végére. Ami nem ismert, de nem
csupa nulla, azt `.overlay`-be menti későbbi elemzéshez, a csupa nulla részt pedig nem menti.
A naplósor végén ilyenkor `tail=<állapot>` áll: `FIXED`, `ALREADY`, `OVERLAY` vagy `NOTAIL`.

```bash
sudo find /home3/arpi/mentes_1 -path '*_JPG*' -name 'f*.jpg' -exec python3 fixoverlay.py --report /home3/arpi/mentes_1/report.xml --dump /dev/nbd0 --do {} + > fixoverlay.log
```

**A már kimentett `.overlay`-ekből** (report nélkül, root nélkül) `--do`-val ugyanígy visszaírja
az ismert utófarkot:

```bash
find /home3/arpi/mentes_1 -path '*_JPG*' -name 'f*.jpg' -exec python3 fixoverlay.py --do {} + > fixoverlay.log
```

**Ismert utófarkok** (`overlay_len`, [fixoverlay.py:56](fixoverlay.py:56)):

- **Samsung:** a SEF-blokk (`Image_UTC_Data` – a felvétel ideje UTC-ben, ms-ban –, `MCC_Data`
  – a mobilhálózat országkódja –, … `SEFH` tartalomjegyzék … `SEFT`) a `SEFT` zárójelig tart.
  Csak akkor fogadja el, ha a `SEFT` előtti 4 bájtos hossz szerint visszafelé egy `SEFH` fejléc
  van.
- **HP, FinePix stb.:** a kép utáni `0xFF` kitöltő bájtok, legfeljebb 64. Ha utánuk `D9` jön,
  az is hozzátartozik, mert az a valódi `FF D9` lezárás.

Ha a fájl vége már egyezik az utófarokkal, nem írja hozzá újra, így többször is futtatható. A
fájlidő megmarad. Az `.overlay`-es mód állapotai: `FIX`/`FIXED`, `ALREADY`, `NOTAIL`,
`NOOVERLAY`, utána a hossz. Az `indxrename.py` előtt kell futtatni.

## dupfill.py

Előfordul, hogy ugyanaz a kép több könyvtárba is fel volt másolva: azonos névvel, mérettel és
dátummal. A PhotoRec minden, a lemezen még meglévő példányt külön visszaállít. Ha azonban
valamelyik példány elveszett, például a törölt részre esett, akkor az egyik könyvtárban
megvan a kép, a másikban nincs.

A `dupfill.py` az `indxrename.py` összes menete után, az `INDEX.pck` könyvtárából futtatva
ezeket pótolja. Ha az INDX szerint egy kép több helyen szerepelt, és az egyik helyen már
megvan, a többi helyre **hard linket** készít róla, így az nem foglal helyet. Egy hiányzó
példányt akkor pótol, ha:

- a név (kis- és nagybetűtől függetlenül) és a méret egyezik;
- a dátum egész órányi eltéréssel ±2 másodpercen belül egyezik;
- a kiterjesztés kép (`IMGEXT`: jpg, png, gif, tif, heic, nef, cr2 stb.). A `thumbs.db`
  és a hasonló fájlok kimaradnak, mert azoknál az azonos méret nem jelent azonos tartalmat.

```
dupfill.py        kiírja, mit csinálna (LINK <meglévő> -> <hiányzó>)
dupfill.py --do   létrehozza a hard linkeket
```

## Hasznos háttéranyag

- NTFS adatszerkezetek: [libfsntfs dokumentáció](https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc)
- MFT fixup: <https://dtidatarecovery.com/ntfs-master-file-table-fixup/>
