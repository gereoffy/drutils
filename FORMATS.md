# Támogatott formátumok és ellenőrzések

A `testfiles.py` fájlok épségét ellenőrzi: sérült-e a fájl, végig olvasható/dekódolható-e. Tipikus felhasználás:
lemezről vagy mentésből visszaállított fájlok átnézése. A cél a **tárolás közben keletkezett sérülések** (csonkolás,
kinullázott szektorok, bitflip, rossz helyről visszaállított adat) felderítése, nem a formátum teljes körű
szabványossági vizsgálata. Az író programok ismert furcsaságait (amitől a fájl nem sérült) figyelmeztetésként
kezeljük, nem hibaként.

Külső függőség csak egy van, az is opcionális: az `olefile` (OLE2: doc/xls/ppt). Minden más tiszta Python.
Nagy adatmennyiséghez PyPy ajánlott (tipikusan 5–10× gyorsabb).

## Általános működés

- **Felismerés tartalom alapján** (magic bytes), nem a kiterjesztés alapján: `testfile()` → `detect_and_test()`.
- **Eredmény** (`testfile()` visszatérési értéke: `(hibapont, típus)`):
  - `> 0` → **BAD** (sérült),
  - `0` → **OK**,
  - `< 0` → **DUNNO** (nem felismerhető, túl kicsi, vagy nem támogatott verzió).
- **Csupa nulla fájl** (bármilyen kiterjesztéssel) → BAD (`file contains only zero bytes`). Tipikusan lefoglalt, de
  soha ki nem írt terület visszaállítás után.
- **256 bájtnál kisebb fájl** → DUNNO (`small`), kivéve a WMF/EMF-et, ami lehet nagyon kicsi is.
- **Kiterjesztés-figyelmeztetés** (nem változtat az eredményen): ha a kiterjesztés ismert, de a tartalom nem
  ismerhető fel (`WARNING! content not recognized as .jpg`), vagy más típusú (`WARNING! .wmf file, but content is jpg`).
  Kivételek: `.zip` néven bármilyen zip-alapú fájl, `.docx/.xlsx/.pptx` néven OLE (jelszóval védett Office fájl).
- **Kimenet:** alapból csak a hibaként számolt tételek (`ERROR! ...`) jelennek meg. Minden `test*` függvénynek van
  `debug=False` paramétere; önállóan futtatva (`pypy testjpeg.py fájl_vagy_könyvtár`) minden modul debug módban fut.
- **Kivételkezelés:** minden ellenőrző elkapja a saját kivételeit (hibapont: 100), egy sérült fájl nem állítja le a
  futást, és nem okozhat segfaultot (nincs natív kód, kivéve a zlib-et).

## Összefoglaló táblázat

| Formátum | Modul | Mit ellenőriz röviden | Integritás-ellenőrzés |
|---|---|---|---|
| JPEG | `testjpeg.py` | markerek, **teljes Huffman-dekódolás** minden scanre, MCU-szám | – (a Huffman-kód maga) |
| PNG, APNG | `testpng.py` | chunkok, **teljes zlib-kitömörítés**, pontos méret, filter byte-ok | CRC32 chunkonként, Adler-32 |
| GIF | `testgif.py` | blokkok, **minden frame LZW-dekódolása**, pixelszám | – |
| TIFF | `testtif.py` | IFD-lánc, strip/tile-ok, **kitömörítés** (LZW, Deflate, PackBits, JPEG) | Adler-32 (Deflate) |
| PSD, PSB | `testpsd.py` | szekciók, rétegek csatornái, RLE/ZIP sorok | Adler-32 (ZIP) |
| ZIP (docx, xlsx, pptx, odt, epub, spv, jar…) | `testzip.py` | minden tag végigolvasva, XML jólformáltság, SPV hivatkozások | CRC32 tagonként |
| OLE2 (doc, xls, ppt, egyéb) | `testole.py` | FAT-láncok, minden stream, formátumonkénti szerkezet, beágyazott képek | (a beágyazott képeké) |
| SPSS .sav, .zsav | `testsav.py` | szótár (dictionary), adatrész, esetszám | Adler-32 (ZSAV) |
| DXF (ASCII, bináris) | `testdxf.py` | csoportkódok, értéktípusok, szekciószerkezet, EOF | – |
| DWG (R10 – 2018) | `testdwg.py` | verziócsaládonként a formátum saját ellenőrzőösszegei | CRC16, CRC32, Adler-32, Reed–Solomon |
| WMF, EMF | `testwmf.py` | rekordok, paraméterek összhangja, EOF | placeable fejléc XOR-összeg |
| MP4, MOV, M4A, 3GP, HEIC, AVIF (ISOBMFF) | `testmp4.py` | box-szerkezet, mintatáblák, **minden minta helye**, H.264/H.265 NAL-keretezés | – |

---

## JPEG (`testjpeg.py`)

**Felismerés:** `FF D8 FF` + marker.

**Szerkezet:**
- Markerek végigjárása, szegmenshosszak (nem lóghatnak ki a fájlból), SOI/EOI/SOS/SOF darabszám
  (pontosan egy SOI, egy EOI, legalább egy SOS, pontosan egy SOF0/SOF1/SOF2).
- DQT: 8 és 16 bites kvantálási táblák. DHT: érvényes Huffman-tábla (kódtúlcsordulás, legfeljebb 256 kód).
- SOF: komponensek, mintavételezési tényezők (1–4). Képméret-heurisztika (pl. szélesség < 16, extrém oldalarány)
  → figyelmeztetés + 1 hibapont.
- MPF (APP2) blokk olvasása, little- és big-endian (iPhone) változat is.
- Az EOI utáni beágyazott második kép (pl. előnézet) rekurzívan ellenőrizve. A fájl végi nulla kitöltés megengedett.

**Tartalom – teljes entrópia-dekódolás (IDCT nélkül):**
- Minden scan Huffman-dekódolása: baseline, extended, progresszív DC (első és finomító) és progresszív AC (első
  és finomító). A progresszív AC-finomításhoz blokkonként nyilvántartja a nem-nulla koefficienseket.
- **Pontosan az elvárt számú MCU/blokk** dekódolódjon scanenként (a képméretből és a mintavételezésből számolva).
- Érvénytelen Huffman-kód, koefficiens-index túlcsordulás, idő előtti adatvég → hiba.
- Restart (RST) markerek sorrendje (D0…D7 ciklikusan), restart interval nélküli RST → hiba.
- **512+ egymás utáni 0x00 bájt** a scan-adatban → hiba (kinullázott szektor).

**Egyéb:** a DC-értékekből ASCII-art előnézet rajzolható (`ASCII_ART` konstans a fájl elején: `None`,
`"truecolor"`, `"256"`, `"16x2"`, `"16"`), a DC-dekódolás szemrevételezéséhez.

**Nem észleli:** olyan bitflipet, ami érvényes Huffman-kódot eredményez és nem változtat a blokkszámon.

## PNG, APNG (`testpng.py`)

**Felismerés:** `89 50 4E 47 0D 0A 1A 0A`.

- **Minden chunk CRC32-je.** Chunknév érvényessége, csonka chunk.
- Chunk-sorrend: IHDR az első (vagy Apple CgBI után), IDAT-ok egymás után, IEND a végén.
  Palettás képnél kötelező a PLTE (legfeljebb 256 szín).
- IHDR: bitmélység és színtípus érvényes kombinációja, tömörítés/szűrő/interlace mezők.
- **Teljes zlib-kitömörítés** (1 MB-os darabokban, alacsony memóriával), a stream végének és az **Adler-32**-nek
  az ellenőrzése.
- **Pontos kitömörített méret**, interlace-es (Adam7) képnél passonként számolva (a 8 bitnél kisebb mélység és a
  8 pixelnél keskenyebb kép is helyesen).
- **Minden scanline filter byte-ja** (0–4).
- Apple CgBI (iOS) PNG: nyers deflate zlib-fejléc nélkül.
- APNG: minden animációs frame (fcTL + fdAT) adatának kitömörítése és méretének ellenőrzése.
- IEND utáni adat → csak figyelmeztetés.

## GIF (`testgif.py`)

**Felismerés:** `GIF87a` / `GIF89a`.

- Logikai képernyő (méretkorlát: 8192 × 4096, felette hiba), globális és lokális paletták.
- Blokkok (kép, kiterjesztés, trailer), sub-block láncok (csonka lánc → hiba).
- **Minden frame LZW-dekódolása** (csak a pixelek száma, értékük nem kell): érvénytelen LZW-kód → hiba,
  **a pixelszám pontosan szélesség × magasság** legyen.
- LZW minimális kódméret 2–8.
- Legalább egy képkocka, és **kötelező a trailer (0x3B)**.
- Figyelmeztetés: hiányzó LZW end code (ha a pixelszám rendben van), a képernyőn kívül eső frame, adat a
  trailer után.

## TIFF (`testtif.py`)

**Felismerés:** `II*\0` / `MM\0*` (klasszikus TIFF, version 42). A BigTIFF (43) nem támogatott.

- IFD-lánc bejárása, **körkörös hivatkozás** felismerése, **minden IFD (oldal) külön ellenőrzése**.
- Tagok: ismeretlen típusú tag kihagyva (figyelmeztetés), fájlon kívülre mutató tag → hiba.
- Kép adatai: strip-ek vagy tile-ok (TileOffsets), planar=1 és planar=2, al-mintavételezett YCbCr.
  Minden strip/tile a fájlon belül legyen, nulla hosszú strip → hiba, hiányzó StripByteCounts becslése.
- **Kitömörítés / méret strip-enként:**
  - tömörítetlen: a strip hossza ≥ a várt méret,
  - **LZW** (TIFF 6 és régi LSB-first változat): érvénytelen kód, korai EOI, túl sok maradék adat → hiba.
    A rossz bitszélességgel írt EOI-t (ismert enkóder-hiba) a libtiff-hez hasonlóan elfogadja,
  - **Deflate / Adobe Deflate:** teljes kitömörítés, **Adler-32**,
  - **PackBits:** túlfutás, maradék adat,
  - **JPEG (compression=7):** strip-enként a `testjpeg` dekódolja, a JPEGTables tag tábláival kiegészítve.
- Egyéb tömörítésnél (pl. CCITT G3/G4) csak a strip-ek helye ellenőrzött.

## PSD, PSB (`testpsd.py`)

**Felismerés:** `8BPS`, version 1 (PSD) vagy 2 (PSB, Large Document Format).

- Fejléc: csatornaszám, méret, bitmélység (1/8/16/32), színmód.
- Color Mode Data, Image Resources blokkok (`8BIM`, `MeSa`, `PHUT`, `AgHg`, `DCSR` aláírások).
- **Layer és mask információ:** layer-rekordok, **minden réteg minden csatornájának adatmérete**, az RLE
  csatornák soronkénti ellenőrzése, ZIP csatornák kitömörítése (Adler-32). A maszk-csatornák (-2/-3)
  méretét nem számolja, csak a hosszakat. Global layer mask, additional layer information blokkok.
- **Merged (összesített) kép:** tömörítetlen, RLE (minden sor pontosan a várt hosszra bomoljon ki) vagy ZIP.
  1 bites (bitmap) mód is.
- A fájl pontosan a képadat végén érjen véget (csonka vagy extra adat → hiba).

## ZIP-alapú formátumok (`testzip.py`)

**Felismerés:** `PK\3\4`. Típus: Office Open XML (docx, xlsx, pptx, vsdx), OpenDocument (odt, ods, odp, odg),
epub (a `mimetype` tag alapján), SPSS Viewer (spv), jar, apk, egyéb zip.

- A központi könyvtár beolvasása.
- **Minden tag végigolvasása** (1 MB-os darabokban), **CRC32** tagonként.
- Office/ODF/epub/spv esetén **minden `.xml` és `.rels` tag jólformáltsága** (streamelő expat parser, nem épít fát).
  Az üres XML tagokat (pl. a LibreOffice `Configurations2/accelerator/current.xml`) kihagyja.
- Titkosított tag: kihagyva (debug módban jelezve). Nem támogatott tömörítés (pl. Deflate64): figyelmeztetés, nem hiba.
- **SPSS Viewer (.spv):** az `outputViewer*.xml` fájlok `<vtb:dataPath>` / `<vtb:path>` hivatkozásai létező
  tagokra mutassanak (hiányzó tag → hiba; ezt a CRC nem jelzi).

## OLE2 / Compound File (`testole.py`, kell hozzá az `olefile`)

**Felismerés:** `D0 CF 11 E0 A1 B1 1A E1`. Típus: doc, xls, ppt, db (Thumbs.db), egyéb OLE.

**Konténer (minden OLE fájlra, bármilyen programé):**
- Megnyitás az olefile-lal; csak a valódi hibák számítanak (`DEFECT_INCORRECT` és felette). A régi programok
  ártalmatlan furcsaságai (pl. szemét a stream méret felső 32 bitjében) csak debug figyelmeztetések.
- **Minden stream végigolvasása**, a beágyazott storage-okban lévőké is (FAT-lánc, csonka szektor).
- **FAT-konzisztencia:** minden lánc pontosan akkora, mint a stream mérete, ENDOFCHAIN-nel zárul, és **egy szektor
  sem tartozik két lánchoz** (könyvtár, MiniFAT, ministream, nagy és kis streamek).
- **Property set streamek** (`\x05SummaryInformation`, `\x05DocumentSummaryInformation`, beágyazottak is,
  MS-OLEPS): fejléc, halmazok és tulajdonságok helye/mérete, az értékek a halmazon belül. (A Mac-es Excel 1 bájttal
  elszámolt halmaz-eltolását tűri.)
- Hiba esetén (és debug módban) kiírja a **root CLSID-t** és a **létrehozó alkalmazást** (AppName), ez az
  ismeretlen formátumoknál segít.

**XLS (Excel 5/95 `Book` és 97+ `Workbook` stream):**
- A BIFF-rekordok hézag nélkül lefedik a streamet, BOF/EOF párok, minden BOUNDSHEET egy BOF rekordra mutat,
  az utolsó EOF után csak nulla kitöltés lehet. Titkosított munkafüzetnél is működik.

**DOC (Word):**
- Word 97+: FIB, a table stream (`0Table`/`1Table`) megléte, **mind a 90 FIB-hivatkozás a table streamen belül**,
  a CHPX/PAPX formázási lapok (FKP) szerkezete, a **piece table**, és minden szövegdarab a WordDocument streamen
  belül. Titkosított dokumentumnál csak a FIB.
- Word 6/95: fcMin/fcMac tartomány.

**PPT (PowerPoint):**
- A rekordok lefedik a `PowerPoint Document` streamet, Current User stream, a **UserEdit-lánc**, és a **persist
  directory** minden bejegyzése egy rekord elejére mutat. Titkosított prezentációnál csak a Current User.

**Beágyazott képek:** a doc `Data`, a ppt `Pictures` streamjéből és az xls MSODRAWINGGROUP rekordjaiból a JPEG és
PNG képeket (OfficeArt BLIP) kivágja, és a `testjpeg`-gel / `testpng`-vel ellenőrzi.

## SPSS .sav / .zsav (`testsav.py`)

**Felismerés:** `$FL2` (sav) / `$FL3` (zsav, zlib). Tiszta Python: a korábbi pyreadstat-os ellenőrzés sérült
fájloknál segfaultolt.

- Fejléc: bájtsorrend (little/big endian), tömörítés típusa.
- **Szótár (dictionary):** változórekordok (típus, címke, hiányzó értékek), a 8 bájtnál hosszabb szövegek
  folytatórekordjai, értékcímkék és a hozzájuk tartozó változóindexek, dokumentum- és kiterjesztés-rekordok,
  súlyváltozó, a fejléc esetmérete = a változórekordok száma (a ReadStat által írt 0-t tűri).
- **Adatrész:**
  - tömörítetlen: a méret pontosan esetszám × esetméret,
  - **bájtkódos tömörítés:** az adatfolyam végigjárása, egész számú eset, **esetszám = a fejlécben lévő**,
  - **ZSAV:** zheader/ztrailer, a blokktáblázat (eltolások, méretek), **minden zlib blokk kitömörítése**
    (Adler-32), a kitömörített adat bájtkódos ellenőrzése.

## DXF (`testdxf.py`)

**Felismerés:** tartalom alapján: szöveges `0` / `SECTION` kezdet (előtte lehet 999-es megjegyzés), vagy
`AutoCAD Binary DXF` fejléc.

- **Szöveges DXF:** nincs benne vezérlő/bináris bájt (TAB, CR, LF és a DOS-os `^Z` a végén megengedett),
  a csoportkód érvényes szám (0–1071, a definiált tartományokban), **az érték típusa megfelel a kódnak**
  (lebegőpontos, egész, hexadecimális handle). A tizedesvesszős számokat (magyar/német locale-lal futó
  exportálók) figyelmeztetéssel elfogadja.
- **Bináris DXF:** 1 bájtos (R12) és 2 bájtos (R13+) csoportkódok, típusos értékek, csonka érték / lezáratlan szöveg.
- **Szerkezet:** SECTION/ENDSEC, TABLE/ENDTAB, BLOCK/ENDBLK párok, POLYLINE és attribútumos INSERT után
  VERTEX/ATTRIB…SEQEND, van ENTITIES szekció, **`EOF` a végén** (hiányzik → csonka), EOF után nincs adat.

## DWG (`testdwg.py`)

**Felismerés:** `AC10xx`. Az objektumokat nem értelmezi, csak a fájlszerkezetet és a formátum saját
ellenőrzőösszegeit.

| Család | Verzió | Ellenőrzés |
|---|---|---|
| R10 | AC1006 | táblák és szakaszok helye, az entitások hosszmezői végigláncolhatók (ellenőrzőösszeg még nincs a formátumban) |
| R11/R12 | AC1009 | az előzők + sentinelek a táblák és szakaszok körül, **minden táblabejegyzés és entitás CRC16-ja** |
| R13–R2000 | AC1012, AC1014, AC1015 | fájlfejléc CRC16 + sentinel, header és classes szakasz CRC16 + sentinelek, az object map darabjainak CRC16-ja, **minden objektum CRC16-ja** |
| R2004+ | AC1018, AC1024, AC1027, AC1032 | titkosított fájlfejléc **CRC32**, oldaltérkép és szakasztérkép (kitömörítve, Adler-32), **minden adatoldal fejléc- és adat-ellenőrzőösszege** (Adler-32) |
| R2007 | AC1021 | **Reed–Solomon** kódolt fájlfejléc (RS(255,239)), oldaltérkép és szakasztérkép, az RS-kódolt adatoldalak paritása (RS(255,251)) |

- R10: az üres szakasz/tábla fájlon kívüli címe (adat nem veszett el) csak figyelmeztetés.
- Nem támogatott (régebbi) verzió (AC1001–AC1004, AC2.x…) → DUNNO.
- R2007-ben a nem RS-kódolt kis szakaszok (előnézet, összefoglaló) tartalma nem ellenőrizhető.

## WMF, EMF (`testwmf.py`)

**WMF felismerés:** placeable (`D7 CD C6 9A`) vagy sima METAHEADER (típus 1/2, 9 szavas fejléc, verzió 0x100/0x300).

- Placeable fejléc **XOR-ellenőrzőösszege**, METAHEADER mezők.
- Minden rekord: hossz (≥ 3 szó, nem lóg ki), **ismert típus** (MS-WMF), nem nagyobb a fejlécben megadott
  legnagyobb rekordméretnél.
- **Paraméterek összhangja:** fix méretű rekordok (az opcionális kitöltőszót tűri), sokszögek/vonalláncok
  pontszáma, POLYPOLYGON pontszámainak összege, szövegek hossza (TEXTOUT, EXTTEXTOUT), a beágyazott DIB
  bitképek fejléce és mérete.
- EOF rekord kötelező. Ha a fejléc méretmezője szerint még adatnak kellene jönnie (egy sérülés hamis EOF-ot
  hozott létre) → hiba. Az EOF utáni kitöltés vagy szemét csak figyelmeztetés.

**EMF felismerés:** `EMR_HEADER` rekord + ` EMF` aláírás a 40. bájtnál (`testemf()`).

- Fejléc: méret, lefoglalt mező, leírószöveg helye, fejlécben megadott fájlméret ≤ a valódi (nagyobb → csonka).
- Minden rekord: méret (≥ 8, 4-gyel osztható, nem lóg ki), típus (1–122), **rekordszám és teljes méret = a
  fejlécben lévő**, az utolsó rekord EOF.
- Paraméterek: sokszögek (16 és 32 bites), több sokszöges rekordok pontszámösszege, EXTTEXTOUTW szöveg és
  betűköz-tömb a rekordon belül, bitképes rekordok (BITBLT, STRETCHBLT, STRETCHDIBITS) bitképe a rekordon belül,
  megjegyzés-rekordok hossza.

## MP4, MOV, M4A, 3GP, HEIC, AVIF – ISO Base Media File Format (`testmp4.py`)

**Felismerés:** `ftyp` box a fájl elején (a márka szerint `heic` / `mov` / `mp4` típus), vagy régi QuickTime-nál
`moov` / `mdat` / `wide` / `free` kezdés, töredezett szakasznál `moof` / `styp`. A formátumban nincs CRC.

- **Box-szerkezet:** a legfelső szintű boxok hézag nélkül lefedik a fájlt, a konténer-boxok (`moov`, `trak`, `mdia`,
  `minf`, `stbl`, `meta`, `udta`, `moof`, `traf`…) gyerekei pontosan kitöltik a szülőt, érvényes box-típusok,
  64 bites méret, a fájl végéig tartó box. Egy box, ami túlnyúlik a fájlon → csonka. (A QuickTime `ilst` kulcsindexes
  gyerekeit és a `udta` végi nulla lezárót elfogadja; a fájl végi nulla kitöltés csak figyelmeztetés.)
- **Kötelező elemek:** `moov` → `mvhd`, minden `trak` → `tkhd`, `mdia` → `mdhd`, `hdlr`, `stbl` → `stsd`, `stts`,
  `stsc`, `stsz`/`stz2`, `stco`/`co64`.
- **Mintatáblák összhangja:** a mintaszám az `stts`-ben és az `stsz`-ben egyezik, az `stsc` hozzárendelés pontosan a
  mintaszámot adja ki. (QuickTime tömörítetlen PCM hangnál az `stts` eltérése csak figyelmeztetés, és a mintaméretet
  a hangleíró csatornaszámából/bitmélységéből számolja.)
- **Minden minta (videókocka, hangcsomag) helye:** a táblákból kiszámolt minden chunk a fájlon és egy `mdat` boxon
  belül van. Ez akkor is jelzi a csonkolást, ha a fejléc ép. (Külső adatra hivatkozó QuickTime trackeknél kihagyva.)
- **Töredezett MP4:** a `moof`/`traf`/`trun` által leírt mintaadat a fájlon belül van.
- **H.264 / H.265 videó (`avc1`/`avc3`/`hvc1`/`hev1`):** minden minta NAL-egységekre bontása (a hosszmezők pontosan
  kiadják a minta méretét), érvényes NAL-fejléc, és **a NAL-egységek belsejében nincs tiltott `00 00 00/01/02`
  bájtsorozat** (emulation prevention). Ez a kinullázott blokkokat a videóadat belsejében is megfogja. A NAL végi
  nulla kitöltést és egyes kódolók által a szelet végére fűzött „end of sequence” NAL-t elfogadja.
- **HEIC / HEIF / AVIF képek:** az `iloc` elemek adata a fájlon belül van, az elsődleges elem (`pitm`) létezik, és a
  HEVC/AVC képelemek (az iPhone-képek csempéi) ugyanúgy NAL-ellenőrzésen mennek át.
- A hang (AAC stb.) és a többi kodek adatát nem vizsgálja (nincs benne ellenőrizhető keretezés).

---

## Ismert korlátok

Ezeket formátumszintű ellenőrzéssel nem lehet kiszűrni:
- **Nyers, ellenőrzőösszeg nélküli adatba eső sérülés:** tömörítetlen pixelek (TIFF, PSD, BMP-szerű DIB), a
  tömörítetlen SAV adatrész, lebegőpontos koordináták (bináris DXF, WMF/EMF pontok), szöveg a doc-ban. Egy ilyen
  bitflip csak egy pixel/érték megváltozását okozza.
- **Metaadatba eső sérülés**, amit a formátum nem véd (pl. ICC-profil, XMP egy TIFF-ben).

Csak szintetikus (generált) mintán tesztelt, valódi fájlon még nem:
- ZSAV (`$FL3`) és big-endian SAV,
- bináris DXF (az ezdxf-fel generált mintákon tesztelve),
- JPEG-tömörítésű TIFF, APNG,
- AVIF (az ISOBMFF-ágon generált minta sem volt; a HEIC-ek valódi iPhone-fotók).

Nem támogatott: BigTIFF, a DWG R10 előtti verziói, EMF+ (az EMF-be ágyazott GDI+ rekordok tartalma).
