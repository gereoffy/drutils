# Támogatott formátumok és ellenőrzések

A `testfiles.py` fájlok épségét ellenőrzi: sérült-e a fájl, végig olvasható/dekódolható-e. Tipikus felhasználás:
lemezről vagy mentésből visszaállított fájlok átnézése. A cél a **tárolás közben keletkezett sérülések** (csonkolás,
kinullázott szektorok, bitflip, rossz helyről visszaállított adat) felderítése, nem a formátum teljes körű
szabványossági vizsgálata. Az író programok ismert furcsaságait (amitől a fájl nem sérült) figyelmeztetésként
kezeljük, nem hibaként.

Nincs külső függőség, minden tiszta Python (az OLE2-höz korábban kellő `olefile` helyett saját olvasó van).
Nagy adatmennyiséghez PyPy ajánlott (tipikusan 5–10× gyorsabb).

## Általános működés

- **Felismerés tartalom alapján** (magic bytes), nem a kiterjesztés alapján: `testfile()` → `detect_and_test()`.
- **Futtatás:** `pypy testfiles.py [-j N] fájl_vagy_könyvtár...`. A könyvtárakat rekurzívan bejárja.
  - `-j N`: N párhuzamos folyamattal vizsgál, szálak helyett folyamatokkal, mert a GIL miatt a szálak nem futnának
    ténylegesen párhuzamosan. Nagy fájlszámnál érdemes a magok számára állítani.
  - A kimenet párhuzamosan is pontosan ugyanaz, mint soros futásnál: fájlonként egyben, az eredeti sorrendben, a sorok
    nem keverednek. A mintákon (8607 fájl) 8 folyamattal 4,6× gyorsabb.
- **Eredmény** (`testfile()` visszatérési értéke: `(hibapont, típus)`):
  - `> 0` → **BAD** (sérült),
  - `0` → **OK**,
  - `< 0` → **DUNNO** (nem felismerhető, túl kicsi, vagy nem támogatott verzió).
- **Csupa nulla fájl** (bármilyen kiterjesztéssel) → BAD (`file contains only zero bytes`). Tipikusan lefoglalt, de
  soha ki nem írt terület visszaállítás után.
- **256 bájtnál kisebb fájl** → DUNNO (`small`), kivéve a GIF-et, a PNG-t és a WMF/EMF-et, amik lehetnek nagyon kicsik is
  (ikonok, 1 pixeles képek).
- **Kiterjesztés-figyelmeztetés** (nem változtat az eredményen): ha a kiterjesztés ismert, de a tartalom nem
  ismerhető fel (`WARNING! content not recognized as .jpg`), vagy más típusú (`WARNING! .wmf file, but content is jpg`).
  Kivételek: `.zip` néven bármilyen zip-alapú fájl, `.docx/.xlsx/.pptx` néven OLE (jelszóval védett Office fájl).
- **Kimenet:** alapból csak a hibaként számolt tételek (`ERROR! ...`) jelennek meg. Minden `test*` függvénynek van
  `debug=False` paramétere; önállóan futtatva (`pypy testjpeg.py fájl_vagy_könyvtár`) minden modul debug módban fut.
- **Kivételkezelés:** minden ellenőrző elkapja a saját kivételeit (hibapont: 100), egy sérült fájl nem állítja le a
  futást, és nem okozhat segfaultot (nincs natív kód, kivéve a zlib-et).
- **Metaadat-sorok (`XXX_INFO`)**, a visszaállított fájlok azonosításához (a fájlnév és a dátum elvész): a DWG, DXF,
  ZIP-alapú (CDR X4+ is), CDR, OLE, JPEG, TIFF, WebP, MP4/MOV/HEIC, AVI, WMV/WMA, MKV/WebM, MP3, WAV, SWF és SAV fájlokról minden fájlra kiír egy sort, a debug módtól függetlenül:

  `XXX_INFO;fájlnév;verzió;típus;létrehozás;utolsó mentés;dátum forrása;utoljára mentette;szerző;cím;program;[eszköz;]OK|BAD|DUNNO`

  (A DWG-nél kicsit eltér, lásd ott.) Az `eszköz` mező (fényképezőgép, telefon) csak a JPG/TIF/MP4/AVI sorokban van.
  A dátumok helyi időben, `YYYY-MM-DD HH:MM:SS` formában, az UTC-ben tárolt értékek átszámolva. Az üres mező azt
  jelenti, hogy a fájlban nincs (értelmes) adat. A mezőkből a `;` és a vezérlőkarakterek ki vannak szedve.
  CSV-be gyűjtés: `grep -a '^JPG_INFO;' kimenet.txt > jpg.csv`. A `-a` kell, mert a kimenet más soraiban lehet
  bináris szemét, és akkor a grep az egész bemenetet binárisnak veszi, és elnyeli a sorokat. A közös rész:
  `fileinfo.py`.
- **Fájldátum igazítása:** ha a `fileinfo.py` elején `fix_filedatetime = True`, a vizsgált fájl módosítási idejét
  (mtime, atime) a belőle kiolvasott utolsó mentés dátumára állítja, ha az nincs, a létrehozáséra (mint a `touch -d`).
  Visszaállított fájloknál hasznos, ahol a fájl dátuma a visszaállítás ideje lett. Alapból ki van kapcsolva. Minden
  `XXX_INFO`-t író formátumra működik, a sérült (BAD) fájlokra is, ha van bennük dátum.

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
| MP4, MOV, M4A, 3GP, HEIC, AVIF (ISOBMFF) | `testmp4.py` | box-szerkezet, mintatáblák, **minden minta helye**, H.264/H.265 NAL- és AV1 OBU-keretezés | – |
| AVI (RIFF, OpenDML) | `testavi.py` | chunk-szerkezet, **az index minden bejegyzése**, a videokockák eleje és nulla blokkjai | – |
| WebP | `testavi.py` | RIFF és chunk méretek, VP8X jelzők, VP8/VP8L fejléc, VP8L és alfa nulla blokkjai | – |
| WAV (RIFF, RF64) | `testavi.py` | chunk méretek, fmt összhang, **félbeszakadt felvétel**, ADPCM blokkfejlécek, MP3 keretlánc | – |
| CorelDRAW CDR (RIFF 3–X3, ZIP X4+) | `testavi.py`, `testzip.py` | chunk-szerkezet, **a tömörített rajzblokkok teljes zlib-kitömörítése**, indexelt chunkok | Adler-32 (cmpr), CRC32 (ZIP) |
| MP3 | `testmp3.py` | ID3v2 tagek, **a keretlánc hézagmentessége**, keretenkénti CRC, Xing/VBRI keretszám | CRC-16 (keret), LAME hangadat CRC-16 |
| SWF (FWS, CWS, ZWS) | `testswf.py` | méret, **teljes zlib/LZMA-kitömörítés**, tagek láncolata, beágyazott képek | Adler-32 (CWS) |
| WMV, WMA (ASF) | `testasf.py` | objektumok, **minden adatcsomag és payload hossza**, küldési idők, index | – |
| MKV, WebM (Matroska) | `testmkv.py` | EBML elemfa, blokkok és lacing, **H.264/HEVC NAL keretezés**, Cues/SeekHead index | CRC-32 elemek (ha vannak) |

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
- **512+ egymás utáni 0x00 bájt** a scan-adatban → hiba (kinullázott szektor). Kivétel a progresszív JPEG csak DC-s scanje: egyszínű
  területen ott minden blokk a csupa 0 bites „0 különbség” kódot kapja, így a nullasor érvényes.

**Egyéb:** a DC-értékekből ASCII-art előnézet rajzolható (`ASCII_ART` konstans a fájl elején: `None`,
`"truecolor"`, `"256"`, `"16x2"`, `"16"`), a DC-dekódolás szemrevételezéséhez.

**Nem észleli:** olyan bitflipet, ami érvényes Huffman-kódot eredményez és nem változtat a blokkszámon.

- **`JPG_INFO` sor:** verzió helyén a méret (`szélesség x magasság`). Az APP1 EXIF-ből: készítés
  (DateTimeOriginal, ha nincs: DateTimeDigitized), módosítás (DateTime), szerző (Artist / XPAuthor), cím (XPTitle /
  ImageDescription), program (Software), eszköz (Make + Model). Ha nincs EXIF dátum, az APP1 XMP-ből
  (`xmp:CreateDate`, `xmp:ModifyDate`, `xmp:CreatorTool`, `dc:creator`, `dc:title`). Az EXIF dátumoknak nincs
  időzónájuk, helyi időnek veszi őket. Csak a fő képre ír sort (a beágyazott és az extra képekre nem).

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
- **`TIF_INFO` sor:** verzió helyén a méret (`szélesség x magasság`). Készítés: EXIF DateTimeOriginal (Digitized),
  módosítás: DateTime (306), szerző: Artist, cím: XPTitle / ImageDescription, program: Software, eszköz: Make + Model.
  Ha nincs EXIF dátum, az XMP (700-as tag) `xmp:CreateDate` / `xmp:ModifyDate`. Forrás: `exif`, `xmp`, vagy vegyesen.

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

- A központi könyvtár beolvasása. Visszaállított fájloknál:
  - ha a zip vége (EOCD) után egy másik zip darabja van, saját zip-véggel (keveredés egy másik fájllal vagy korábbi
    mentéssel), az hiba; az ellenőrzés és a metaadatok az első teljes zip alapján,
  - ha a központi könyvtár nem a rögzített helyén van (hiányzik vagy ki van cserélve a fájl egy része), az hiba,
  - ha nincs zip-vég (csonka fájl), a helyi fejlécekből újraépíti a központi könyvtárat, így a megmaradt tagok CRC-je
    és a metaadatok ellenőrizhetők; a fájl ettől még BAD,
  - a zip vége utáni sima szemét csak debug figyelmeztetés.
- **Minden tag végigolvasása** (1 MB-os darabokban), **CRC32** tagonként.
- Office/ODF/epub/spv esetén **minden `.xml` és `.rels` tag jólformáltsága** (streamelő expat parser, nem épít fát).
  Az üres XML tagokat (pl. a LibreOffice `Configurations2/accelerator/current.xml`) kihagyja.
- Titkosított tag: kihagyva (debug módban jelezve). Nem támogatott tömörítés (pl. Deflate64): figyelmeztetés, nem hiba.
- **SPSS Viewer (.spv):** az `outputViewer*.xml` fájlok `<vtb:dataPath>` / `<vtb:path>` hivatkozásai létező
  tagokra mutassanak (hiányzó tag → hiba; ezt a CRC nem jelzi).
- **`ZIP_INFO` sor** (minden fájlról, debug módtól függetlenül), pl. `grep -a ^ZIP_INFO kimenet.txt > zip.csv` (a `-a` kell, mert a kimenet más soraiban lehet bináris szemét, és akkor a grep elnyeli a sorokat):

  `ZIP_INFO;fájlnév;zip verzió;típus;létrehozás;utolsó mentés;dátum forrása;utoljára mentette;szerző;cím;program;OK|BAD`

  - OOXML (docx/xlsx/pptx/vsdx): `docProps/core.xml` (created, modified, creator, lastModifiedBy, title) és `docProps/app.xml` (Application, AppVersion).
  - ODF: `meta.xml` (creation-date, dc:date, initial-creator, dc:creator, title, generator).
  - epub: a `container.xml` által mutatott `.opf` (dc:date, dcterms:modified, creator, title, generator). jar: `MANIFEST.MF` `Created-By`.
  - Ha nincs értelmes metaadat-dátum: a zip tagok dátuma (NTFS / Unix extra mező, különben DOS dátum), a legrégebbi
    a létrehozás, a legújabb az utolsó mentés. A dátum forrása: `meta`, `zip`, vagy vegyesen `zip/meta` (létrehozás/mentés).
    Az MS Office minden tagnak 1980-01-01 00:00-t ír, ezt (és a jövőbeli dátumokat) figyelmen kívül hagyja.
  - Minden dátum helyi időben (az OOXML UTC-ben tárol, átszámolva). Sérült metaadat-tagból annyit olvas ki, amennyit lehet.

## OLE2 / Compound File (`testole.py`, `parseole.py`)

**Felismerés:** `D0 CF 11 E0 A1 B1 1A E1`. Típus: doc, xls, ppt, db (Thumbs.db), egyéb OLE.

**Felépítés:**
- **`parseole.py`**: önálló OLE-olvasó az olefile helyett, csak a Python standard könyvtárára épül, más programokból
  (pl. vírusellenőrző) is használható. Benne van:
  - `OleFile` (szigorú és megengedő mód),
  - a konténer-ellenőrzések (`check_fat`, `check_propset`),
  - a metaadatok kiolvasása (`summary_properties`, `ole_info`),
  - a `Thumbs.db` katalógus beolvasása (`thumbs_catalog`).

  Parancssorból a streamek listáját és a metaadatokat írja ki: `pypy parseole.py fájl...`
- **`testole.py`**: a `parseole` köré épül. A fájl tartalmát ellenőrzi tovább (doc/xls/ppt szerkezet, beágyazott képek,
  bélyegképek), és kiírja az `OLE_INFO`/`THUMB_INFO` sorokat.

**Konténer (minden OLE fájlra, bármilyen programé):**
- Saját OLE-olvasó (MS-CFB), külső könyvtár nélkül. Az olefile megnyitáskori ellenőrzéseit követi:
  - **fejléc:** aláírás, CLSID, verzió, bájtsorrend, szektorméretek, fenntartott mezők, mini-cutoff,
  - **FAT és DIFAT:** a DIFAT hossza és lezárása, csonka FAT-szektor,
  - **könyvtár:** bejegyzés-típus, gyökér, névhossz, a piros-fekete fa minden mutatója a tartományon belül, minden
    bejegyzés legfeljebb egyszer szerepel, nincs névütközés, két stream nem kezdődik ugyanazon a szektoron,
  - **láncok:** a szektorindex a tartományon belül, csonka szektor, a lánc rövidebb a stream méreténél.

  Ugyanazok számítanak hibának, mint az olefile-ban (`DEFECT_INCORRECT` és felette). A régi programok ártalmatlan
  furcsaságai (pl. szemét a stream méret felső 32 bitjében) csak debug figyelmeztetések. A mintákon (2340 valódi,
  140 korábbi és 1200 új szintetikusan sérült fájl) fájlonként ugyanazt az eredményt adja, mint az olefile-os változat.
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

**Thumbs.db (a Windows XP/2003 Intéző bélyegkép-gyorsítótára, `Catalog` stream):** a visszaállító programok gyakran
`.doc` néven mentik, mert OLE fájl.
- A `Catalog` bejegyzései (hossz, sorszám, dátum, eredeti fájlnév) hiánytalanok és a streamen belül vannak.
- Minden bejegyzéshez van bélyegkép-stream (a neve a sorszám visszafelé, pl. 12 → `21`), a fejléc mérete stimmel, és a
  JPEG-et a `testjpeg` dekódolja. A régi (Windows 2000/ME) bélyegképek JPEG-jéből hiányoznak a Huffman-táblák, ezekhez
  a szabványos táblákat (ITU T.81, K.3–K.6) teszi elé.
- Hibás vagy hiányzó bélyegkép → hiba. A mintákon (187 fájl, 17249 bélyegkép) mind ép.
- **`THUMB_INFO` sor** bélyegképenként (a mappa egykori képeinek listája, akkor is, ha maguk a képek elvesztek):

  `THUMB_INFO;fájlnév;sorszám;az eredeti kép neve;dátum;OK|BAD|MISSING`

  A dátum a kép módosítási ideje a bélyegkép készítésekor (helyi idő). CSV: `grep -a '^THUMB_INFO;' kimenet.txt > thumbs.csv`.

**`OLE_INFO` sor** (minden fájlról, debug módtól függetlenül), pl. `grep -a ^OLE_INFO kimenet.txt > ole.csv`:

`OLE_INFO;fájlnév;formátum verzió;típus;létrehozás;utolsó mentés;dátum forrása;utoljára mentette;szerző;cím;program;OK|BAD`

- Formátum verzió: `Word6/95`, `Word97+`, `BIFF5`, `BIFF8`, `PPT97+`.
- Forrás: a `\x05SummaryInformation` property set (saját olvasó, sérült streamből is annyit, amennyit lehet;
  a szövegek a benne megadott kódlappal dekódolva). Ha nincs benne dátum (az Excel az utolsó mentést általában nem
  írja), a gyökér könyvtárbejegyzés létrehozási / módosítási ideje. A dátum forrása: `meta`, `ole`, vagy `meta/ole`.
- A dátumok helyi időben (a fájlban UTC FILETIME). A mintákon a doc-ok 90%-ánál az utolsó mentés
  órára egyezik a fájl mtime-jával.
- Ha a fájl a megnyitáskor hibás, a metaadatokat engedékeny módban olvassa újra, így sérült fájlból is kijön,
  amennyi kiolvasható.
- **Megengedő mód más programoknak** (pl. heurisztikus vírusellenőrzés): `parseole.OleFile(data, strict=False)`.
  - Csak akkor dob kivételt, ha a fájl nem OLE. Minden más hiba az `issues` listába kerül, és a sérült fájlból is
    kiolvassa, amit lehet (`listdir()`, `exists()`, `openstream()`).
  - Szándékosan rosszindulatú fájlok ellen is védett:
    - a szektorláncokban figyeli a ciklusokat,
    - egy lánc nem lehet hosszabb a FAT-nál,
    - a hibás vagy óriási FAT/DIFAT-méreteket a fájl méretére vágja,
    - értelmetlen szektorméretnél (pl. 1 bájt) a verzió szerinti szabványos méretet használja (512/4096, mini: 64),
      így egy fejlécbájt átírásával sem lehet elrejteni a tartalmat vagy lelassítani a vizsgálatot,
    - a könyvtárfát rekurzió nélkül járja be, így a mélyen egymásba ágyazott storage-ok sem okoznak `RecursionError`-t,
    - az összes kiolvasott adat mennyisége a fájlmérettel arányos, így az egymásra mutató streamekkel sem lehet
      memóriát vagy időt elfogyasztani.
  - A `testole` saját ellenőrzése a szigorú módot (`strict=True`, alapértelmezett) használja.

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
- **`SAV_INFO` sor:** verzió: `$FL2` / `$FL3`. A fejléc dátuma (`dd mmm yy hh:mm:ss`, helyi idő) a fájl írásának
  ideje, ez kerül a létrehozás és az utolsó mentés mezőbe is. Cím: a fájl címkéje (file label), program: a fejléc
  termékneve (pl. `IBM SPSS STATISTICS 64-bit MS Windows 21.0.0.0`, `Stata 16.1/-savespss-`).

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
- **`DXF_INFO` sor:** verzió: `$ACADVER` (és a kiadás, pl. `R2007`), létrehozás / utolsó mentés: `$TDCREATE` /
  `$TDUPDATE` (Julian dátum, helyi idő), utoljára mentette: `$LASTSAVEDBY`. Szerző és cím nincs a DXF-ben.

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
- **`DWG_INFO` sor** (minden fájlról, debug módtól függetlenül), a visszaállított fájlok azonosításához, pl.
  `grep -a ^DWG_INFO kimenet.txt > dwg.csv`:

  `DWG_INFO;fájlnév;verzió;kiadás;létrehozás;utolsó mentés;utoljára mentette;szerző;cím;OK|BAD|DUNNO`

  A dátumok forrása: R10–R12 a fejléc fix helye, R13–R2000 a fejlécváltozók bitfolyama, R2004+ az
  `AcDb:SummaryInfo` szakasz (ha hiányzik, R2004-ben és R2007-ben a fejlécváltozók; a mintákon, ahol mindkettő megvan,
  a kettő pontosan egyezik). A „utoljára mentette”, „szerző” és „cím” csak
  R2004+-ban van. Az üres mező azt jelenti, hogy a fájlban nincs érvényes érték (egyes nem AutoCAD programok
  nem töltik ki a dátumot; a létrehozás dátuma sablonból öröklött is lehet, pl. 1982/1992).
- R2007-ben a nem RS-kódolt kis szakaszok (előnézet, összefoglaló) tartalma nem ellenőrizhető.
- R2007: ha a fájl nagyobb a fejlécben megadott méretnél (visszaállításkor a klaszter végéig kiírt szemét), az csak
  figyelmeztetés; ha kisebb (csonka), hiba.

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
- **AV1 videó (`av01`):** minden minta OBU-kra bontása (fejléc: tiltott és fenntartott bit, érvényes típus; LEB128
  hossz, a hosszak pontosan kiadják a mintát; a sequence/frame header és a metadata OBU záró bitjei).
- **HEIC / HEIF / AVIF képek:** az `iloc` elemek adata a fájlon belül van, az elsődleges elem (`pitm`) létezik, és a
  HEVC/AVC képelemek (az iPhone-képek csempéi) NAL-, az AV1 képelemek (AVIF) OBU-ellenőrzésen mennek át.
- A hang (AAC stb.) és a többi kodek adatát nem vizsgálja (nincs benne ellenőrizhető keretezés).
- **`MP4_INFO` sor:** verzió: a márka (`ftyp`: `mp42`, `qt`, `heic`…), típus: `mp4` / `mov` / `heic`.
  - Videó: létrehozás: a felvétel ideje (Apple `com.apple.quicktime.creationdate`, időzónával), ha nincs, az `mvhd`
    létrehozási ideje (UTC, 1904 óta), végül a `©day`. Utolsó mentés: az `mvhd` módosítási ideje. (Az `mvhd` a vágó- vagy
    exportáló program mentési ideje is lehet, ezért a felvétel idejénél a `creationdate` az elsődleges.)
    Szerző, cím, program, eszköz: QuickTime `udta` (`©ART`, `©nam`, `©swr`, `©mak`, `©mod`), iTunes `ilst` (`©too`) és a
    QuickTime `keys` metaadatok. Forrás: `meta`, `mvhd`, vagy vegyesen.
  - HEIC/HEIF kép: az `Exif` elem (az `iloc` alapján), ugyanúgy, mint a JPEG-nél. Forrás: `exif`.

## AVI (`testavi.py`)

**Felismerés:** `RIFF` … `AVI `. A kodekeket nem dekódolja (lassú lenne, és a nagy fájloknál értelmetlen), a szerkezetet
és az indexet nézi. 1 GB AVI kb. 1 s.

- **RIFF-szerkezet:** a chunkok és listák egymásba ágyazása, mérete, a páros bájthatár; ami kilóg a szülőjéből vagy a
  fájlból → csonka. OpenDML (1 GB fölött): a további `RIFF AVIX` szegmensek is. A fájl vége utáni szemét (a klaszter
  végéig kiírt rész) csak figyelmeztetés.
- **Fejlécek:** `avih`, streamenként `strh`/`strf`.
- **`movi` lista:** minden chunk azonosítója érvényes (`##dc`, `##db`, `##wb`, `##pc`, `##tx`, `ix##`, `JUNK`), a
  streamszám létező streamre mutat.
- **Index:** az `idx1` és az OpenDML index (`indx` → `ix##`) **minden bejegyzése** egy ugyanolyan azonosítójú és méretű
  chunkra mutat (az `idx1` eltolását a `movi` listához vagy a fájl elejéhez viszonyítva is felismeri). Ez fogja meg a
  kiesett vagy elcsúszott részeket.
- **Videokockák, dekódolás nélkül:** a kocka eleje (MJPEG: `FFD8`, MPEG-4/H.264: `00 00 01`), és hogy nincs-e a kocka
  belsejében 64 bájtos nullasor (kódolt videoadatban ilyen nem lehet; a kocka végi nulla kitöltés megengedett). Ez a
  bájtkeresés gyors, és a képkockákba eső kinullázott szektorokat is megfogja. A hangadatban a nulla csend is lehet,
  azt nem nézi.
- Egyes Canon fényképezőgépek a hangcsomag után 2 bájttal felülírják a következő chunk azonosítóját (pl. `}}dc`): ha
  az index ugyanide ugyanilyen méretű, ugyanolyan végű chunkot mutat, csak figyelmeztetés.
- A mintákon (151 fájl, 1 GB): mind OK; szintetikus sérülésnél csonkolás 30/30, kinullázott 512 bájtos szektor 30/30,
  4 KB-os blokk 28/30 (a maradék hangadatra esett). A képkockák bitflipjei dekódolás nélkül nem derülnek ki.
- **`AVI_INFO` sor:** verzió helyén a videokodek (`MJPG`, `XVID`…).
  - Létrehozás: az `IDIT` chunk (Canon: `Wed Feb 02 15:05:50 2011`), a Fujifilm `strd` chunkjában lévő EXIF
    (DateTimeOriginal, utolsó mentés: DateTime), végül a `LIST INFO` `ICRD` mezője.
  - Program: `ISFT`, cím: `INAM`, szerző: `IART`.
  - Eszköz: a Fuji EXIF gyártó és típus, a HP `JUNK` chunkjában lévő típus, más kamerák `strd` chunkjában lévő
    gyártónév.

## WebP (`testavi.py`, a RIFF alapú AVI mellett)

**Felismerés:** `RIFF` … `WEBP`. Dekódolás nélkül.

- A RIFF és a chunkok mérete (a csonkolás mindig kiderül), a `VP8X` jelzőbitjei és a chunkok összhangja, a vászon és
  a kép mérete, animációnál minden `ANMF` keret a vásznon belül és benne képadat.
- `VP8` (veszteséges) képfejléc: kulcskocka, verzió, start kód, méret, az első partíció a chunkon belül. `VP8L`
  (veszteségmentes) fejléc, és nincs benne 64 bájtos nullasor; tömörített alfa (`ALPH`) ugyanígy, nyers alfa: pontosan
  szélesség × magasság bájt.
- A veszteséges VP8 adatban az egyszínű területeken hosszú nullasor is lehet (a mintákon 631 bájtos is), ezért ott a
  kinullázott szektor és a bitflip dekódolás nélkül nem derül ki (szintetikus teszt: csonkolás 30/30, kinullázott
  szektor 1/30).
- A mintákon (240 WebP) mind OK.
- **`WEBP_INFO` sor:** mint a `JPG_INFO`: méret, az `EXIF` chunk (készítés, módosítás, eszköz, program) és az `XMP`
  chunk adatai.

## WAV (`testavi.py`, RIFF WAVE és RF64)

**Felismerés:** `RIFF`/`RF64` … `WAVE` (a nagyon kicsi fájlokat is). Dekódolás nélkül; a `testfiles` a nagy
felvételeket memóriába képezve (`mmap`) olvassa. A big-endian `RIFX` WAV-ot nem ismeri (DUNNO).

- A RIFF és a chunkok mérete (csonkolás); RF64-nél (4 GB fölött) a `ds64` chunk 64 bites méretei. Ha a RIFF fejlécben
  a méret rossz (sok író elszámolja), de a fájlmérettel minden chunk stimmel, csak figyelmeztetés.
- A `fmt` adatai: csatornák, mintavétel, blokkméret; PCM/float/A-law/mu-law-nál a blokkméret és a bájtráta összhangja
  (figyelmeztetés), `WAVE_FORMAT_EXTENSIBLE` is.
- **Félbeszakadt felvétel:** a fejlécben 0 (vagy régi) a hangadat mérete, de utána még sok adat van (a diktafon vagy a
  felvevő program nem zárta le a fájlt) → hiba, a valódi méret kiírásával.
- IMA és MS ADPCM: minden blokk fejléce (lépésindex, prediktor); MP3-at tartalmazó WAV: a `testmp3` keretlánc-ellenőrzése.
- A PCM adatban a nulla a csend is lehet, ezért a kinullázott szektor és a bitflip ott nem derül ki.
- A mintákon (661 fájl, köztük a Python `wave` moduljának szándékosan hibás tesztfájljai): 655 OK, 3 BAD (a szándékosan
  csonkák), 3 DUNNO (big-endian). Szintetikus teszt: csonkolás és félbeszakadt felvétel 18/18.
- **`WAV_INFO` sor:** verzió helyén a formátum (pl. `PCM 24bit 48000Hz 2ch`). Létrehozás: a Broadcast WAV (`bext`)
  felvételi dátuma és ideje, ha nincs, a LIST INFO `ICRD`; program: `ISFT` (Sound Forge, GoldWave…), eszköz: a `bext`
  Originator mezője (pl. `Pro Tools`, `Zoom H4n`), előadó, cím: LIST INFO vagy ID3 chunk.

## CorelDRAW CDR (`testavi.py` és `testzip.py`)

**Felismerés:** a 3–X3 verziók (`RIFF` … `CDR3`…`CDRD`) RIFF fájlok, az X4-től ZIP (X6-tól `mimetype`
`application/x-vnd.corel.zcf.draw.document+zip`, előtte `content/riffData.cdr`). A ZIP-ben a rajz maga
(`content/root.dat` vagy `content/riffData.cdr`) megint RIFF, így ugyanaz az ellenőrző nézi.

- **RIFF:** a chunk-szerkezet (a közös RIFF-kóddal); a 8-as verziótól a rajz tömörített `LIST cmpr` blokkokban van:
  a négy méretmező, a két `CPng` + zlib folyam **teljes kitömörítése (Adler-32)**, és a kitömörített chunkok bejárása,
  ahol a méretmező index a blokk mérettáblájába (mint a libcdr-ben). A `stlt` (stílusok) lista a 9-es verziótól nem
  chunk-szerkezetű, ott csak a mérete számít.
- **ZIP:** a `testzip` minden ellenőrzése (tagonkénti CRC, XML), és a belső RIFF a fenti módon.
- A verzió a RIFF form betűjéből (`CDR9` = 9, `CDRB` = 11, `CDRG` = X6, `CDRP` = 2022; az `L` betű kimaradt), a ZIP-es
  CDR-ek XMP-jében lévő termékneve alapján ellenőrizve.
- A mintákon (318 fájl, CorelDRAW 5…2022): mind OK. Szintetikus sérülésnél: RIFF: csonkolás 15/15, kinullázott szektor
  13/15, bitflip 12/15; ZIP: mindhárom 15/15.
- **Metaadat:** a régi (RIFF) CDR-ben nincs dátum, a `CDR_INFO` sorban csak a verzió van. A ZIP-es CDR a `ZIP_INFO`
  sorba kerül (típus: `cdr`): az X6+ XMP-jéből létrehozás, utolsó mentés, szerző (`dc:creator`), utoljára mentette
  (`crl:LastAuthor`), program (`CorelDRAW 2022`); az X4–X5-ben dátum nincs, ott a zip-tagok dátuma.

## MP3 (`testmp3.py`)

**Felismerés:** `ID3` tag a fájl elején, vagy két egymást követő érvényes MPEG audio keret. Dekódolás nélkül, a mintákon
kb. 1 GB/s.

- **ID3v2 tag(ek)** a fájl elején (2.2, 2.3, 2.4; több egymás után is, egyes tagszerkesztők a régi elé írnak újat): a
  fejléc, a tag mérete a fájlon belül, a frame-ek a tagon belül (v2.4-ben a hibás, nem syncsafe méretet író programokat
  is kezeli), unsynchronisation. A beágyazott borítókép (APIC) a `testjpeg`/`testpng`-vel.
- **A fájl végi tagek** (ID3v1, Lyrics3v2, APE) leválasztása.
- **Keretlánc:** a fejlécből (verzió, layer, bitráta, mintavétel, padding) számolt hossz alapján a keretek hézag
  nélkül követik egymást. Szinkronvesztésnél újraszinkronizál, és jelzi a hézagot (helye, mérete, nulla-e). Csonka
  utolsó keret → hiba; a fájl vége utáni kevés (< 4 KB) szemét csak figyelmeztetés.
- **Keretenkénti CRC-16** (Layer III, ha a kódoló bekapcsolta; a régi fájloknál gyakori): a fejléc és az
  oldalinformáció. Ha minden keretben rossz, kódoló-hibának veszi (figyelmeztetés).
- **Xing/Info, VBRI fejléc:** a keretszám; ha kevesebb keret van → csonka.
- **LAME fejléc:** a teljes hangadat CRC-16-ja (a tag saját CRC-jével ellenőrizve, hogy tényleg LAME tag).
- Csak ID3 tagból álló fájl (a visszaállítás csak a tag elejét találta meg) → BAD, de a cím és az előadó kiíródik.
- A mintákon (522 fájl): 424 OK, 98 BAD (96 csak ID3 tag, 2 csonka). Szintetikus sérülésnél: csonkolás 100%, kinullázott
  szektor/blokk 95–100%, bitflip a CRC-s fájloknál 70%, CRC nélkül csak ha a keretfejlécbe esik.
- **`MP3_INFO` sor:** verzió: pl. `MPEG1 LIII`.
  - A felvétel éve nem a fájl dátuma, ezért nem a dátum mezőkbe kerül, hanem az utolsó (eszköz) mezőbe: `album (év)`.
  - Létrehozás / utolsó mentés: az ID3v2.4 kódolási (`TDEN`) és tagelési (`TDTG`) ideje, illetve a Windows Media
    Player által ismeretlen albumnál az album nevébe írt rippelési idő (`Ismeretlen album (2010.05.23. 15:50:07)`).
  - Előadó, cím: ID3v2, ha nincs, ID3v1 (egy kódoló kitöltetlen alapértelmezett tagjét – „The Title”, „The Author” –
    kihagyja). Program: `TSSE`/`TENC`, vagy a LAME verzió.

## SWF (`testswf.py`)

**Felismerés:** `FWS` (tömörítetlen), `CWS` (zlib), `ZWS` (LZMA), értelmes verzióval és fejléccel. A visszaállító
programok sok véletlen, `ZWS`-sel kezdődő adatot találnak (tömörített vagy titkosított fájlok darabjait): ezeket az
LZMA fejléc (paraméterbájt, szótárméret) alapján nem veszi SWF-nek, rájuk DUNNO jön.

- A fejlécben lévő (kitömörített) méret: tömörítetlennél a fájl mérete, `CWS`-nél **a teljes zlib-kitömörítés
  (Adler-32)**, `ZWS`-nél a teljes LZMA-kitömörítés.
- A tagek (`RECORDHEADER`) láncolata az End tagig. Az End tag után legfeljebb 512 bájt lehet: a kinullázott vagy
  hiányzó adat nulla bájtja maga is End tag, ezért ott a lánc „szabályosan” véget érne. A fejlécben lévő
  **képkockaszám = a ShowFrame tagek száma** (a csonkolást és a kiesett részt is megfogja).
- A beágyazott képek (DefineBitsJPEG2/3/4: JPEG, PNG, GIF) a `testjpeg`/`testpng`/`testgif`-fel, a zlib-es
  (DefineBitsLossless) képek kitömörítése. A videó- és hangadatot nem dekódolja.
- A mintákon (26 valódi SWF, Flash 6–11): 25 OK, 1 BAD (az 1,5 MB-os határtól a végéig kinullázva, 179 képkockából
  27 van meg). Az `ffmpeg`-gel készült és saját tömörítésű (CWS/ZWS) fájlokon: csonkolás, kinullázott szektor és
  bitflip a tömörített fájloknál mindig hiba, tömörítetlennél csak ha képbe vagy szerkezetbe esik.
- **`SWF_INFO` sor:** verzió: pl. `SWF 6 zlib`. Létrehozás / utolsó mentés és program, szerző, cím: a Metadata tag
  (XMP), illetve a Flex fordító ProductInfo tagjében lévő fordítási idő.

## WMV, WMA – ASF (`testasf.py`)

**Felismerés:** az ASF Header Object GUID-ja. Dekódolás nélkül; a `testfiles` a nagy fájlokat memóriába képezve
(`mmap`) olvassa. 1 GB kb. 1 s.

- **Objektumszerkezet:** a Header Object gyerekeinek mérete pontosan kitölti a headert, a File Properties szerinti
  fájlméret (kisebb fájl → csonka, nagyobb → figyelmeztetés), a Data Object mérete = 50 + csomagszám × csomagméret.
- **Minden adatcsomag:** error correction, length type és property flags, csomaghossz, padding, és **a payloadok
  hossza pontosan kitölti a csomagot** (több payload és tömörített payload is). A küldési idők nem ugorhatnak vissza
  (egy kinullázott csomagnál visszaugranak). A video payloadok belsejében nem lehet 64 bájtos nullasor (tömörített
  videoadatban ilyen nincs; a hangban a csend lehet nulla; a csomag végi kitöltés megengedett).
- **Index:** a Data utáni objektumok mérete, a Simple Index minden bejegyzése létező csomagra mutat.
- Szintetikus sérülésnél csonkolás és 4 KB-os blokk 24/24, kinullázott szektor 20/24 (a kimaradtak hangadatba
  estek), a bitflipek dekódolás nélkül nem derülnek ki.
- **`ASF_INFO` sor:** verzió helyén a streamek (`video+audio`, `audio`), típus `wmv`/`wma`.
  - Létrehozás: a File Properties dátuma (FILETIME, UTC; a mintákon pontosan egyezik a fájl dátumával), ha nincs,
    a `WM/EncodingTime`.
  - **Olympus diktafonok** (VN, WS, DS sorozat): az `OLYMPUS` leíróban lévő felvételi idő (kezdete → létrehozás,
    vége → utolsó mentés, a diktafon órája szerint), és a típus az utolsó (eszköz) mezőben, pl. `OLYMPUS VN541PC`.
  - Cím, szerző: Content Description, program: `WM/ToolName`, utolsó mező (ha nem diktafon): `WM/AlbumTitle (WM/Year)`.
- A mintákon (58 fájl: 4 WMV, 54 WMA, ebből 51 Olympus diktafonos): mind OK, dátum 57-nél.

## MKV, WebM – Matroska (`testmkv.py`)

**Felismerés:** EBML fejléc `matroska` / `webm` DocType-pal. Dekódolás nélkül; a `testfiles` a nagy fájlokat
memóriába képezve (`mmap`) olvassa.

- **EBML elemfa:** érvényes azonosítók és méretek, minden elem a szülőjén belül; ismeretlen méretű Segment és Cluster
  (élő felvétel) is. A Segment után maradt adat csak figyelmeztetés.
- **Blokkok** (SimpleBlock, Block): létező sáv, a lacing (Xiph, EBML, fix) méretei a blokkon belül.
- **Kodekek, dekódolás nélkül:** H.264/HEVC: a képkockák NAL keretezése és a tiltott `00 00 00/01/02` sorozatok (mint a
  `testmp4`-ben; ez fogja meg a képkockákba eső kinullázott szektorokat), AAC: nincs 64 bájtos nullasor (a mintákon
  9914 ép blokkban egyszer sem), AC3: a keretek szinkronszava (az AC3-ban a csend lehet nulla). A „header stripping”
  tömörítésnél (az `mkvmerge` levágja a keretek elejéről a mindig azonos bájtokat, pl. `0B 77`) a levágott bájtokat
  visszailleszti; más kódolásnál (zlib, titkosítás) a kodek-ellenőrzés kimarad.
- **Index:** a `Cues` minden bejegyzése egy Cluster elejére, illetve azon belül egy blokkra mutat; a `SeekHead` minden
  bejegyzése a megadott azonosítójú elemre.
- **CRC-32 elemek** (ha a fájlban vannak): a szülő elem többi adatának CRC-je.
- A mintákon (45 fájl, mkvmerge, H.264 + AAC/AC3): 44 OK, 1 BAD (egy nagyobb film levágott darabja, a blokkok közé
  más adat került). Szintetikus sérülésnél: csonkolás és 4 KB-os blokk 25/25, kinullázott szektor 23/25.
- **`MKV_INFO` sor:** verzió helyén a kodekek (`AVC+AAC+TEXT`), típus `mkv`/`webm`. Létrehozás: az `Info` `DateUTC`
  mezője (a muxolás ideje, UTC), cím: `Title`, program: `WritingApp`, előadó: a `Tags` ARTIST mezője.

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
- JPEG-tömörítésű TIFF, APNG.

Nem támogatott: BigTIFF, a DWG R10 előtti verziói, EMF+ (az EMF-be ágyazott GDI+ rekordok tartalma).
