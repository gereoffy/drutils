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
| [lsindx.py](lsindx.py) | A teljes image-et végigszkenneli `FILE` (MFT) és `INDX` rekordokért, felépíti a könyvtárfát és a fájllistát, visszamásolja az ép MFT-rekordú fájlokat, opcionálisan **kinullázza** azok klasztereit az image-ben. |
| [indxrename.py](indxrename.py) | A PhotoRec által név nélkül visszaállított fájlokat az `INDEX.pck` alapján (méret, kiterjesztés, Office-metaadatból kinyert dátum) párosítja az eredeti nevekkel, és a helyükre mozgatja őket. |

A tömörített fájlok és a kimentett `$MFT` alapú mentés egy külön eszköz feladata, lásd:
[LSTREE.md](LSTREE.md).

---


## Munkafolyamat (pendrive-mentés)

```
 pendrive ──dd/ddrescue──▶ raw3x.img (MÁSOLAT!)
                               │
                               ▼
                         lsindx.py
            ┌──────────────────┼──────────────────────────┐
            ▼                  ▼                          ▼
   könyvtárfa a cwd-ben   INDEX.pck               ép MFT-rekordú fájlok
   (üres mappák,          (méret → [név, idő,     visszamásolva a fába,
    dir__N ismeretlen      MFT#, szülő] +         majd (opcionálisan) a
    szülőkhöz)             szülő → útvonal)       klasztereik kinullázva
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
és a hamis párosítás. A nullázás alapból **ki van kapcsolva**, lásd a 7. lépést.

---

## lsindx.py

### Beállítás

A paraméterek a szkript elején, konstansként vannak ([lsindx.py:6-10](lsindx.py:6)):

| Változó | Alapérték | Jelentés |
|---|---|---|
| `BLKSIZE` | `4096` | Klaszterméret (és az `INDX` blokkméret) bájtban. |
| `MFTSIZE` | `1024` | MFT-rekord mérete. |
| `part_start` | `0` | A partíció kezdete az image-ben bájtban (lásd lent, hogyan derül ki). |
| `device` | `/home/mentes-pd16g/raw3x.img` | A feldolgozandó image. |

### Futtatás

```bash
mkdir mentes && cd mentes
```

```bash
pypy3 ../lsindx.py > lsindx.log
```

(A shebang `pypy3`-at vár a sebesség miatt; sima `python3`-mal is fut, csak lassabban.)

> ⚠️ Az eszközt/image-et **csak olvasásra** nyitja meg (`rb`, [lsindx.py:199](lsindx.py:199)).
> A nullázáshoz (7. lépés) `r+b` kellene, de azt csak az image **másolatán** szabad
> használni, soha nem az eredeti lemezen.
>
> ⚠️ A könyvtárfát és a fájlokat az **aktuális könyvtárba** hozza létre, ezért üres
> munkakönyvtárból indítsd.

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
- **`device` és `part_start`:** a legegyszerűbb a partíció eszközét megadni (pl.
  `/dev/sdX2`), ekkor `part_start = 0`. Ha a teljes lemezt adod meg, a `part_start` a
  partíció kezdete bájtban (`fdisk -l` vagy `lsblk` alapján). A „Partíció-eltolás
  meghatározása” rész (2. lépés) ezt ellenőrizni is segít.
- **Az állapot ellenőrzése előtte** (`smartctl -a /dev/sdX`): fizikailag hibás lemeznél
  minden teljes olvasás további kockázat. A szkript két teljes menetben olvassa végig az
  eszközt (MFT, majd INDX), és a PhotoRec ugyanezt egy harmadik alkalommal is megteszi.
- **Olvasási hiba:** egy olvashatatlan szektornál a `read` kivételt dob, és a szkript
  leáll. Az `INDEX.pck` csak a végén jön létre, így ilyenkor az addigi munka elvész.
- **Futásidő:** 4 TB-nál egy menet is sok óra, ezért érdemes `pypy3`-mal futtatni.
- **A kimenet** (az aktuális könyvtár, `INDEX.pck`, visszamásolt fájlok) és a PhotoRec
  kimenete is **másik lemezre** kerüljön.

### Működés lépésenként

**1. MFT-rekordok keresése** ([lsindx.py:201-208](lsindx.py:201)) – az image-et 1024 bájtos
lépésekben olvassa, és minden `FILE` szignatúrájú rekordot feldolgoz (`parse_MFT`):

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

**2. INDX blokkok keresése** ([lsindx.py:210-216](lsindx.py:210)) – 4096 bájtos lépésekben
keresi az `INDX` szignatúrát (`parseindx`):

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

**3. Könyvtárfa felépítése** ([lsindx.py:222-238](lsindx.py:222)) – `get_path` a szülő-láncot
a gyökérig (MFT#5, amelynek neve `.`) követi, és `os.makedirs`-szel létrehozza. Ha a lánc egy
ismeretlen könyvtárnál megszakad, annak helyén `dir__<MFT#>` nevű mappa jön létre.

**4. Fájllista** ([lsindx.py:240-243](lsindx.py:240)) – az 1024 bájtnál nagyobb fájlokat
méret szerint rendezve kiírja a logba:

```
<méret> <unix idő> <fájl MFT#>/<szülő MFT#> "<útvonal/név>"
```

**5. `INDEX.pck` mentése** ([lsindx.py:245-249](lsindx.py:245)) – előtte a kis fájlok
szülőkönyvtáraihoz is létrehozza az útvonalat, lásd lent.

**6. Visszamásolás** ([lsindx.py:251-262](lsindx.py:251)) – az `mftfiles` fájljait a
run-listájuk alapján kimásolja a helyükre, a méretre vágja, és beállítja a módosítási időt.
Log: `COPY <bájt> bytes to <útvonal>  (<n> runs)`.

**7. Nullázás** ([lsindx.py:264-273](lsindx.py:264)) – a visszamásolt fájlok klasztereit
nullákkal felülírja az image-ben (a sparse futásokat kihagyja). Log:
`DELETE <bájt> bytes of <útvonal>`.

Az írás maga (`f.write(bytes(BLKSIZE*rl))`) **ki van kommentezve**, így alapból csak a
`DELETE` sorok jelennek meg, az image nem változik. Kettős védelem van rajta: a sort vissza
kell állítani (`#### WARNING` megjegyzés alatt), **és** a megnyitást `r+b`-re kell átírni.
Csak az image másolatán szabad bekapcsolni.

### Az `INDEX.pck` formátuma

```python
filedata, dirmap = pickle.load(open("INDEX.pck", "rb"))
```

- `filedata`: `dict[int, list[tuple]]` – kulcs a fájlméret bájtban, érték az ilyen méretű
  ismert fájlok listája, elemenként `(méret, név, mtime_unix, fájl_MFT#, szülő_MFT#)`.
  Ugyanaz a fájl többször is szerepelhet (MFT-ből és INDX-ből is, illetve hosszú és DOS
  8.3 névvel is).
- `dirmap`: `dict[int, str]` – szülő MFT# → a létrehozott könyvtár relatív útvonala.
  A `filedata` összes fájljának szülőkönyvtára benne van (a könyvtárak létre is jönnek).
  Ha a szülő-lánc megszakad, az útvonal `dir__<MFT#>`-mal kezdődik.

Az `INDEX.pck`-t az [indxrename.py](#indxrenamepy) használja fel.

### Ismert korlátok (lsindx.py)

- Csak 1024 bájtos MFT-rekordot, 4096 bájtos klasztert és INDX blokkot kezel.
- Az INDX blokkokat 4096 bájtra igazítva keresi az image elejétől, tehát ha a partíció
  kezdete nem 4096 többszöröse, a blokkok nem találhatók meg – ilyenkor érdemes előbb a
  partíciót kivágni az image-ből.
- Az MFT-rekordoknál 2 szektoros fixup-ot feltételez.
- A tömörített, töredezett (attribútumlistás) és sparse fájlokat nem másolja vissza
  közvetlenül; ezeket a nyers szkennelésnek kell megtalálnia (vagy az
  [lstree.py](LSTREE.md)-nak, ha van használható `$MFT`). A sparse futásokat (0-s pozíció) a másolás nullákkal tölti ki, a
  nullázás pedig kihagyja őket.
- Az MFT fájl-referenciákból csak az alsó 32 bitet használja.

---

## indxrename.py

A PhotoRec név nélküli kimenetét (`recup_dir.N/f1234567.doc` és hasonló fájlok)
az `lsindx.py` által készített `INDEX.pck` alapján az eredeti nevükre nevezi át, és
az eredeti könyvtárukba mozgatja.

### Függőség

```bash
pip3 install olefile
```

### Futtatás

Az `lsindx.py` **kimeneti könyvtárában** kell futtatni: itt van az `INDEX.pck`, és a
`dirmap`-ben tárolt relatív útvonalak (a már létrehozott könyvtárfa) is innen érvényesek.
A párosítandó fájlokat parancssori argumentumként kapja:

```
indxrename.py [--all] fájl...
```

| Kapcsoló | Jelentés |
|---|---|
| *(nincs)* | **Szigorú mód:** csak akkor nevez át, ha a dátum egyezik, vagy egyetlen lehetséges név van. |
| `--all` | **Minden mód:** mindig a legjobb (legközelebbi dátumú) jelöltre nevez át. |

A kapcsolónak a fájlnevek előtt kell állnia. Kapcsoló vagy fájl nélkül, illetve ismeretlen
kapcsolóval a szkript kiírja a használatot, és kilép.

```bash
python3 ../indxrename.py /mentes/photorec/recup_dir.*/* > indxrename.log
```

Sok fájlnál a shell argumentumlista-korlátja miatt érdemesebb `find`-dal:

```bash
find /mentes/photorec -type f -exec python3 ../indxrename.py {} + >> indxrename.log
```

> ⚠️ A fájlokat `os.rename`-mel **mozgatja** (nem másolja), ezért a PhotoRec kimenetének és a
> célfának ugyanazon a fájlrendszeren kell lennie. A párosítatlan fájlok a helyükön maradnak,
> így a szkript többször is lefuttatható, és a végén a PhotoRec könyvtárában csak a
> fel nem ismert fájlok maradnak.

### Működés

**1. A fájl adatainak megállapítása** (`fileinfo`, [indxrename.py:71](indxrename.py:71)):

- **méret**: a fájl mérete;
- **kiterjesztés**: a PhotoRec által adott fájlnév kiterjesztése (a PhotoRec ezt a formátum
  felismeréséből adja), normalizálva (lásd a 2. lépést);
- **dátum**: alapból a fájl mtime-ja. A PhotoRec ezt a legtöbb formátumnál a tartalomból
  állítja be (képeknél az EXIF alapján). Az Office-fájloknál nem teszi meg, ezért
  ezeknél a szkript maga olvassa ki a dátumot a dokumentum metaadataiból:
  - **ZIP-alapú** (`PK\x03\x04`: docx, xlsx, pptx) → `docProps/core.xml`, az összes `20`-szal
    kezdődő dátummező (létrehozás, módosítás, nyomtatás…) közül a **legkésőbbi**
    (`docxdate`, [indxrename.py:15](indxrename.py:15));
  - **OLE2** (`D0 CF 11 E0`: doc, xls, ppt) → a SummaryInformation *utolsó mentés* ideje,
    ennek hiányában a *létrehozásé*; csak akkor használja, ha 1997 utáni
    (`oledate`, [indxrename.py:39](indxrename.py:39)).

**2. Jelöltek keresése** ([indxrename.py:102-130](indxrename.py:102)) – a `filedata[méret]`
listából, azaz csak a **bájtra pontosan azonos méretű** ismert fájlok közül. Kihagyja:

- a `~`-mal kezdődő neveket (Office ideiglenes fájlok, pl. `~$level.docx`);
- azokat, amelyeknek a célhelyén már létezik fájl. Ez lehet egy `lsindx.py` által
  visszamásolt fájl vagy egy korábbi párosítás eredménye, így egy név csak egyszer osztható ki;
- az eltérő kiterjesztésűeket. A kiterjesztéseket mindkét oldalon kisbetűsíti és
  normalizálja (`EXT_ALIAS`, [indxrename.py:64](indxrename.py:64)), mert a PhotoRec
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

**3. Átnevezés** ([indxrename.py:133](indxrename.py:133)) – a `--all` kapcsoló dönti el,
mennyire szigorú:

- **`--all`** (*minden* mód): a legjobb jelöltre mindig átnevez, dátumellenőrzés nélkül. Ez
  a több menetes használat utolsó, „maradék” menete (lásd lent).
- **kapcsoló nélkül** (*szigorú* mód, alapértelmezés): csak akkor nevez át, ha

  - a dátumeltérés legfeljebb 2 óra + 61 másodperc (az időzóna-eltérés miatt: a
    `core.xml` UTC-ben tárol, de a `Z` levágása után helyi időként értelmeződik), vagy
  - csak egyetlen lehetséges név van.

  Ha a feltétel nem teljesül, a fájlt a helyén hagyja, `SKIP` sort ír, és utána kiírja a
  lehetséges neveket (`NAMES: [...]`).

### Javasolt használat: több menetben, fontossági sorrendben

A szkriptet nem egyszerre érdemes az összes fájlra ráengedni, hanem sokszor egymás után.
Mindig a legfontosabb fájltípusokkal kell kezdeni, és úgy haladni a többi felé:

1. **Szigorú mód** (kapcsoló nélkül), a legértékesebb típusokkal kezdve: először a nagy méretű
   Office-fájlok, aztán a fotók (JPEG), és így tovább. Például:

   ```bash
   find /mentes/photorec -type f \( -name '*.docx' -o -name '*.xlsx' -o -name '*.doc' -o -name '*.xls' \) -size +1M -exec python3 ../indxrename.py {} + >> indxrename.log
   ```

   ```bash
   find /mentes/photorec -type f -name '*.jpg' -exec python3 ../indxrename.py {} + >> indxrename.log
   ```

2. **Minden mód (`--all`)** a legvégén, a maradékra: ami addig nem kapott nevet, az a
   legközelebbi dátumú szabad jelöltet kapja.

   ```bash
   find /mentes/photorec -type f -exec python3 ../indxrename.py --all {} + >> indxrename.log
   ```

Ez azért működik jól, mert egy név **csak egyszer osztható ki**: ha a célhelyen már van
fájl, azt a nevet a szkript kihagyja. A korábbi, szigorú menetekben biztosan párosított
fájlok így lefoglalják a nevüket, és a későbbi, lazább menetek már csak a megmaradt
jelöltek közül választhatnak. Ez a mohó párosítás hátrányát is nagyrészt kiküszöböli.

Fényképezőgépről lemásolt fotóknál az EXIF-dátum és a fájl dátuma általában azonos. Ezt
az időt az INDX is tárolja, a PhotoRec pedig az EXIF-ből állítja be, így a fotók szigorú
módban is jól párosíthatók.

### Kimenet

```
<dátum> <méret> <fájl> OK(<jelöltek>/<összes>) <kit.> <eltérés mp> <új útvonal>
<dátum> <méret> <fájl> SKIP(<jelöltek>/<összes>) <kit.> <eltérés mp> <legjobb jelölt>
NAMES: [<lehetséges útvonalak>]
<dátum> <méret> <fájl> BAD(<szabad nevek>/<összes>) [<filedata bejegyzések>]
<dátum> <méret> <fájl> UNKNOWN
```

- `OK(n/m)`: `m` darab ismert fájl ilyen méretű, ebből `n` különböző útvonal volt szabad és
  egyező kiterjesztésű. Az `1/1` biztos találat, a nagyobb `n` és a nagy eltérés
  bizonytalan.
- `SKIP(n/m)`: csak szigorú módban fordul elő. Van jelölt, de a dátum nem egyezik, és egynél
  több lehetséges név van, ezért a fájl a helyén marad. Egy későbbi `--all` menet még
  átnevezheti.
- Ha egy mérethez több bejegyzés tartozik, előtte tabulált sorokban kiírja az összes
  kiterjesztés-egyező jelöltet a dátumeltéréssel együtt, ami utólagos kézi ellenőrzéshez
  hasznos.
- `BAD`: van ilyen méretű ismert fájl, de egyik sem jöhet szóba (foglalt, ideiglenes vagy más
  kiterjesztésű).
- `UNKNOWN`: nincs ilyen méretű fájl az indexben.

### Tudnivalók, korlátok

- A párosítás egy menetben **mohó**: a fájlokat az argumentumok sorrendjében dolgozza fel,
  és az első fájl kapja meg a számára legjobb nevet, akkor is, ha egy később jövőhöz még
  jobban illett volna. Ezt a fenti, több menetes használat nagyrészt kiküszöböli.
- Méret szerinti párosítás csak ott működik, ahol a PhotoRec a formátumból a **pontos**
  fájlméretet tudja meghatározni (pl. OLE2, ZIP). Levágott vagy kitöltött fájloknál
  `UNKNOWN` lesz az eredmény.
- A szkript maga csak az Office-formátumokból nyeri ki a dátumot, minden másnál a PhotoRec
  által beállított fájlidőt használja. Ha a PhotoRec egy formátumnál nem tud dátumot
  kinyerni, ott a fájlidő a mentés időpontja, így a dátum nem segít a választásban.
- Az index ideje a `$FILE_NAME` attribútumból származik. Ezt a Windows jellemzően csak
  létrehozáskor, átnevezéskor és mozgatáskor frissíti, ezért eltérhet a valódi utolsó
  módosítástól. Emiatt kell tűrés a dátum-összevetésnél.
- Ha a jelölt szülőkönyvtára nincs a `dirmap`-ben (régebbi `lsindx.py`-val készült
  `INDEX.pck`), a fájl a `dir__<szülő MFT#>` könyvtárba kerül. A célkönyvtárat szükség
  esetén létrehozza. Sikertelen átnevezésnél (pl. másik fájlrendszer) `RENAME ERROR` sort ír,
  és folytatja a futást.
- Az átnevezett fájl a PhotoRec által beállított mtime-ot tartja meg, az eredeti időt nem
  állítja vissza.
- Sérült Office-fájlnál a dátum nem olvasható ki, ilyenkor a fájl mtime-ja számít.


---

## Hasznos háttéranyag

- NTFS adatszerkezetek: [libfsntfs dokumentáció](https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc)
- MFT fixup: <https://dtidatarecovery.com/ntfs-master-file-table-fixup/>
