#! /usr/bin/python3

# OLE2 (Compound File) alapu fileok: doc, xls, ppt, Thumbs.db, msg, ...
# kulso konyvtar nelkul (korabban olefile kellett hozza)

import datetime
import io
import re
from struct import unpack, unpack_from


def P23Decode(value):
    try:
        return value.decode('utf-8',errors="ignore")
    except UnicodeDecodeError as u:
        return value.decode('windows-1252')

def ShortXLUnicodeString(data, isBIFF8):
    cch = data[0]
    if isBIFF8:
        highbyte = data[1]
        if highbyte == 0:
            return P23Decode(data[2:2 + cch])
        else:
            return data[2:2 + cch * 2].decode('utf-16le', errors='ignore')
    else:
        return P23Decode(data[1:1 + cch])


###############################################################################################################################
# OLE2 (Compound File Binary, MS-CFB) olvaso, kulso konyvtar nelkul. Az olefile ellenorzeseit koveti: a hibak kivetelt
# dobnak (strict), az iroi furcsasagok (pl. szemet a stream meret felso 32 bitjeben) csak az issues listaba kerulnek.
# strict=False: megengedo parser (pl. virusellenorzeshez): semmi nem dob kivetelt (csak a nem OLE file), minden hiba az
# issues listaba kerul, es amit lehet, kiolvas a serult fileokbol is. A hibas meretek / ciklikus lancok ellen vedett
# (a beolvasott adat merete a file meretevel aranyos).
###############################################################################################################################

OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
ENDOFCHAIN, FREESECT, FATSECT, DIFSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFC, 0xFFFFFFFF
UNSURE, POTENTIAL, INCORRECT, FATAL = 10, 20, 30, 40      # hiba szintek (mint az olefile-ban)


class OleFileError(IOError):
    pass

class NotOleFileError(OleFileError):
    pass


class OleEntry:
    """ konyvtar bejegyzes """
    __slots__ = ('sid', 'name', 'type', 'left', 'right', 'child', 'clsid', 'createTime', 'modifyTime', 'isectStart',
                 'size', 'is_minifat', 'kids', 'kids_dict', 'used')


class OleFile:
    """
    ole = OleFile(data): fejlec, FAT (DIFAT-tal), konyvtar fa. Felulet: listdir(), exists(path), openstream(path).read(),
    entry(path), root, fat, minifat, issues. A path '/'-rel elvalasztott szoveg vagy lista, kis/nagybetu fuggetlen.
    """

    def __init__(self, d, strict=True):
        self.d = d
        self.strict = strict
        self.read_budget = 8 * len(d) + (16 << 20)   # megengedo modban osszesen ennyi byte olvashato a lancokbol (DoS vedelem)
        self.raise_level = INCORRECT if strict else FATAL + 1
        self.issues = []            # a nem hibanak szamito furcsasagok
        self.minifat = None
        self.ministream = None
        self.used_fat, self.used_minifat = set(), set()
        if len(d) < 512 or d[:8] != OLE_MAGIC:
            raise NotOleFileError("not an OLE2 structured storage file")
        (clsid, minor, self.dll_version, byte_order, sector_shift, mini_shift, res1, res2, ndir, self.num_fat_sectors,
         self.first_dir_sector, trans, cutoff, self.first_mini_fat_sector, self.num_mini_fat_sectors,
         self.first_difat_sector, self.num_difat_sectors) = unpack_from('<16sHHHHHHLLLLLLLLLL', d, 8)
        if clsid != bytes(16): self.defect(INCORRECT, "incorrect CLSID in OLE header")
        if self.dll_version not in (3, 4): self.defect(INCORRECT, "incorrect DllVersion in OLE header")
        if byte_order != 0xFFFE: self.defect(INCORRECT, "incorrect ByteOrder in OLE header")
        ss = self.sectorsize = 1 << min(sector_shift, 16)
        if ss not in (512, 4096): self.defect(INCORRECT, "incorrect sector_size in OLE header")
        if (self.dll_version == 3 and ss != 512) or (self.dll_version == 4 and ss != 4096):
            self.defect(INCORRECT, "sector_size does not match DllVersion in OLE header")
        self.minisectorsize = 1 << min(mini_shift, 16)
        if self.minisectorsize != 64: self.defect(INCORRECT, "incorrect mini_sector_size in OLE header")
        if res1 or res2: self.defect(INCORRECT, "incorrect OLE header (non-null reserved bytes)")
        if ss == 512 and ndir: self.defect(INCORRECT, "incorrect number of directory sectors in OLE header")
        if trans: self.defect(POTENTIAL, "incorrect OLE header (transaction_signature_number>0)")
        if cutoff != 0x1000: self.defect(INCORRECT, "incorrect mini_stream_cutoff_size in OLE header")
        self.minisectorcutoff = 0x1000
        self.nb_sect = (len(d) + ss - 1) // ss - 1       # a fileban levo szektorok szama (a fejlec nelkul)
        self.check_duplicate(self.first_dir_sector)
        if self.num_mini_fat_sectors: self.check_duplicate(self.first_mini_fat_sector)
        if self.num_difat_sectors: self.check_duplicate(self.first_difat_sector)
        self.load_fat()
        self.load_directory()

    def defect(self, level, msg):
        if level >= self.raise_level: raise OleFileError(msg)
        self.issues.append(msg)

    def check_duplicate(self, first, mini=False):
        """ ket stream nem kezdodhet ugyanazon a szektoron """
        if not mini and first in (DIFSECT, FATSECT, ENDOFCHAIN, FREESECT): return
        used = self.used_minifat if mini else self.used_fat
        if first in used: self.defect(INCORRECT, "Stream referenced twice")
        used.add(first)

    def getsect(self, s):
        """ egy teljes szektor (FAT/DIFAT olvasashoz), csonka szektor: FATAL """
        o = (s + 1) * self.sectorsize
        b = self.d[o:o + self.sectorsize]
        if len(b) != self.sectorsize:
            self.defect(FATAL, "incomplete OLE sector")
            return None
        return b

    def sect2list(self, b):
        return list(unpack_from('<%dL' % (len(b) // 4), b))

    def load_fat_sect(self, idx):
        for s in idx:
            if s in (ENDOFCHAIN, FREESECT): break
            if not self.strict and len(self.fat) >= self.nb_sect: break   # a tobbi ugyis levagodik (DoS vedelem)
            b = self.getsect(s)
            if b is None: break
            self.fat += self.sect2list(b)

    def load_fat(self):
        self.fat = []
        self.load_fat_sect(self.sect2list(self.d[76:512]))
        if self.num_difat_sectors:
            if self.num_fat_sectors <= 109: self.defect(INCORRECT, "incorrect DIFAT, not enough sectors")
            if self.first_difat_sector >= self.nb_sect: self.defect(FATAL, "incorrect DIFAT, first index out of range")
            per = self.sectorsize // 4 - 1
            nb = (self.num_fat_sectors - 109 + per - 1) // per
            if self.num_difat_sectors != nb: self.defect(INCORRECT, "incorrect DIFAT")
            s = self.first_difat_sector
            if not self.strict: nb = min(nb, self.num_difat_sectors, self.nb_sect)   # hibas/oriasi szamok (DoS vedelem)
            for i in range(nb):
                b = self.getsect(s)
                if b is None: break
                v = self.sect2list(b)
                self.load_fat_sect(v[:per])
                s = v[per]
            if s not in (ENDOFCHAIN, FREESECT): self.defect(INCORRECT, "incorrect end of DIFAT")
        del self.fat[self.nb_sect:]

    def read_chain(self, data, offset, ss, fat, sect, size=None):
        """
        egy stream beolvasasa a lancbol (az olefile OleStream ellenorzeseivel). size=None: ismeretlen meret (konyvtar),
        ENDOFCHAIN-ig. data: a file (offset=szektor meret) vagy a ministream (offset=0)
        """
        unknown = size is None
        if unknown: size = len(fat) * ss
        nb = (size + ss - 1) // ss
        if nb > len(fat): self.defect(INCORRECT, "malformed OLE document, stream too large")
        if size == 0 and sect != ENDOFCHAIN: self.defect(INCORRECT, "incorrect OLE sector index for empty stream")
        seen = None
        if not self.strict:
            nb = min(nb, len(fat))   # ciklus nelkul a lanc nem lehet hosszabb a FAT-nal
            seen = set()
        out = []
        for i in range(nb):
            if sect == ENDOFCHAIN:
                if unknown: break
                self.defect(INCORRECT, "incomplete OLE stream")
                break
            if sect >= len(fat):
                self.defect(INCORRECT, "incorrect OLE FAT, sector index out of range")
                break
            if seen is not None:
                if sect in seen:
                    self.defect(INCORRECT, "loop in OLE sector chain")
                    break
                seen.add(sect)
                self.read_budget -= ss
                if self.read_budget < 0:
                    self.defect(INCORRECT, "OLE read limit exceeded (overlapping streams?)")
                    break
            o = offset + ss * sect
            b = data[o:o + ss]
            if len(b) != ss and sect != len(fat) - 1: self.defect(INCORRECT, "incomplete OLE sector")
            out.append(b)
            sect = fat[sect]
        b = b''.join(out)
        if len(b) >= size: return b[:size]
        if not unknown: self.defect(INCORRECT, "OLE stream size is less than declared")
        return b

    def load_directory(self):
        dd = self.read_chain(self.d, self.sectorsize, self.sectorsize, self.fat, self.first_dir_sector)
        self.dirdata = dd
        self.direntries = [None] * (len(dd) // 128)
        if not self.direntries:
            self.defect(FATAL, "OLE directory index out of range")
            self.root = None
            return
        self.root = self.load_entry(0)
        self.build_tree(self.root)

    def load_entry(self, sid):
        if sid >= len(self.direntries):
            self.defect(FATAL, "OLE directory index out of range")
            return None
        if self.direntries[sid] is not None:
            self.defect(INCORRECT, "double reference for OLE stream/storage")
            return self.direntries[sid]
        e = self.dirdata[sid * 128:(sid + 1) * 128]
        en = OleEntry()
        en.sid = sid
        nl, en.type, color, en.left, en.right, en.child = unpack_from('<HBBLLL', e, 64)
        clsid = e[80:96]
        en.createTime, en.modifyTime, en.isectStart, low, high = unpack_from('<QQLLL', e, 100)
        if en.type not in (0, 1, 2, 5): self.defect(INCORRECT, "unhandled OLE storage type")
        if en.type == 5 and sid != 0: self.defect(INCORRECT, "duplicate OLE root entry")
        if sid == 0 and en.type != 5: self.defect(INCORRECT, "incorrect OLE root entry")
        if nl > 64:
            self.defect(INCORRECT, "incorrect DirEntry name length >64 bytes")
            nl = 64
        en.name = e[:max(nl - 2, 0)].decode('utf-16le', 'replace')
        if self.sectorsize == 512:
            # a regi irok a felso 32 bitbe szemetet (0xFFFFFFFF, 1...) irhatnak
            if high not in (0, 0xFFFFFFFF): self.defect(UNSURE, "incorrect OLE stream size")
            en.size = low
        else:
            en.size = low + (high << 32)
        en.clsid = "" if clsid == bytes(16) else "%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X" % unpack_from('<LHH8B', clsid)
        if en.type == 1 and en.size: self.defect(POTENTIAL, "OLE storage with size>0")
        en.is_minifat = en.type == 2 and 0 < en.size < self.minisectorcutoff
        if en.type in (2, 5) and en.size: self.check_duplicate(en.isectStart, en.is_minifat)
        en.kids, en.kids_dict, en.used = [], {}, False
        self.direntries[sid] = en
        return en

    def build_tree(self, node):
        """ a piros-fekete fa bejarasa (bal, sajat, jobb, gyerekek), a gyerekek nev szerint rendezve """
        if node is None or node.child == NOSTREAM: return
        todo = [(node, node.child)]
        while todo:
            parent, sid = todo.pop()
            if sid == NOSTREAM: continue
            if sid >= len(self.direntries):
                self.defect(INCORRECT, "OLE DirEntry index out of range")
                continue
            child = self.load_entry(sid)
            if child is None: continue
            if child.used:
                self.defect(INCORRECT, "OLE Entry referenced more than once")
                continue
            child.used = True
            low = child.name.lower()
            if low in parent.kids_dict: self.defect(INCORRECT, "Duplicate filename in OLE storage")
            if child.type not in (1, 2): self.defect(INCORRECT, "The directory tree contains an entry which is not a stream nor a storage.")
            parent.kids.append(child)
            parent.kids_dict[low] = child
            todo += [(parent, child.left), (parent, child.right)]
            # a stream gyerek mutatoja is NOSTREAM kell legyen: ha nem, azt is bejarjuk (mint az olefile), igy a serules kiderul
            if child.child != NOSTREAM: todo.append((child, child.child))
        for e in self.direntries:
            if e is not None: e.kids.sort(key=lambda k: k.name)

    def listdir(self, streams=True, storages=False):
        out = []
        def walk(node, prefix):
            for k in node.kids:
                if k.type == 1:
                    if storages: out.append(prefix + [k.name])
                    walk(k, prefix + [k.name])
                elif k.type == 2 and streams:
                    out.append(prefix + [k.name])
        if self.root is not None: walk(self.root, [])
        return out

    def entry(self, path):
        node = self.root
        for n in (path.split('/') if isinstance(path, str) else path):
            node = node.kids_dict.get(n.lower()) if node is not None else None
        return node

    def exists(self, path):
        return self.entry(path) is not None

    def load_minifat(self):
        stream_size = self.num_mini_fat_sectors * self.sectorsize
        nb = (self.root.size + self.minisectorsize - 1) // self.minisectorsize
        if nb * 4 > stream_size: self.defect(INCORRECT, "OLE MiniStream is larger than MiniFAT")
        b = self.read_chain(self.d, self.sectorsize, self.sectorsize, self.fat, self.first_mini_fat_sector, stream_size)
        self.minifat = self.sect2list(b[:len(b) // 4 * 4])[:nb]
        self.ministream = self.read_chain(self.d, self.sectorsize, self.sectorsize, self.fat, self.root.isectStart, self.root.size)

    def openstream(self, path):
        e = self.entry(path)
        if e is None: raise IOError("file not found")
        if e.type != 2: raise IOError("this file is not a stream")
        if e.size < self.minisectorcutoff:
            if self.ministream is None: self.load_minifat()
            data = self.read_chain(self.ministream, 0, self.minisectorsize, self.minifat, e.isectStart, e.size)
        else:
            data = self.read_chain(self.d, self.sectorsize, self.sectorsize, self.fat, e.isectStart, e.size)
        return io.BytesIO(data)


###############################################################################################################################
# beagyazott kepek (OfficeArt BLIP rekordok: doc Data stream, ppt Pictures stream, xls MSODRAWINGGROUP):
# a JPEG/PNG kepeket a testjpeg/testpng-vel ellenorizzuk
###############################################################################################################################

# recType -> (formatum, recInstance-ek 1 UID-dal, recInstance-ek 2 UID-dal)
blip_types = {0xF01D: ("jpg", (0x46A, 0x6E2), (0x46B, 0x6E3)), 0xF02A: ("jpg", (0x46A, 0x6E2), (0x46B, 0x6E3)), 0xF01E: ("png", (0x6E0,), (0x6E1,))}


_image_checkers = {}

def image_checker(fmt, log):
    """
    kep ellenorzo fuggveny (kep -> hibapont), vagy None. A testjpeg/testpng csak akkor kell, ha van kep; ha nincs meg a
    modul (pl. a testole.py-t onmagaban hasznaljak), a kep ellenorzes kimarad (figyelmeztetessel).
    """
    if fmt not in _image_checkers:
        try:
            if fmt == "jpg":
                from testjpeg import testjpeg
                _image_checkers[fmt] = lambda img: testjpeg(img, embedded=True)
            else:
                from testpng import testpng
                _image_checkers[fmt] = testpng
        except ImportError as e:
            _image_checkers[fmt] = None
            _image_checkers[fmt + "_err"] = str(e)
    if _image_checkers[fmt] is None: log("WARNING: embedded %s images not checked: %s" % (fmt, _image_checkers[fmt + "_err"]))
    return _image_checkers[fmt]


###############################################################################################################################
# Thumbs.db (Windows XP/2003 Intezo belyegkep gyorsitotar): Catalog stream (az eredeti fajlnevek es datumok) +
# belyegkepenkent egy stream (a nev a sorszam visszafele: 12 -> "21"), benne JPEG
###############################################################################################################################

# a regi (Windows 2000/ME) belyegkepek JPEG-jebol hianyoznak a Huffman tablak: a szabvanyos tablakat (ITU T.81 K.3-K.6) tesszuk ele
def _dht(tc_th, bits, vals): return bytes([tc_th]) + bytes(bits) + bytes.fromhex(vals)
_STD_DHT_BODY = (
    _dht(0x00, [0,1,5,1,1,1,1,1,1,0,0,0,0,0,0,0], "000102030405060708090a0b") +
    _dht(0x10, [0,2,1,3,3,2,4,3,5,5,4,4,0,0,1,0x7d],
         "01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a"
         "434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aa"
         "b2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa") +
    _dht(0x01, [0,3,1,1,1,1,1,1,1,1,1,0,0,0,0,0], "000102030405060708090a0b") +
    _dht(0x11, [0,2,1,2,4,4,3,4,7,5,4,4,0,1,2,0x77],
         "000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a35363738393a"
         "434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aa"
         "b2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa"))
STD_DHT = b'\xff\xc4' + (len(_STD_DHT_BODY) + 2).to_bytes(2, 'big') + _STD_DHT_BODY


def check_thumbs(ole, log):
    """
    Thumbs.db: a Catalog bejegyzesei (hossz, sorszam, FILETIME, UTF-16 nev), minden bejegyzeshez van belyegkep stream,
    a stream fejlece (fejlec hossz, tipus, meret) es a JPEG dekodolhato.
    visszaad: (hibauzenet vagy None, [(sorszam, eredeti nev, datum, OK|BAD|MISSING|-)])
    """
    c = ole.openstream('Catalog').read()
    if len(c) < 16: return "Catalog stream too short", []
    hl, ver, cnt, w, h = unpack_from('<HHLLL', c, 0)
    log("DB: Thumbs.db catalog version %d, %d entries, thumbnails %dx%d" % (ver, cnt, w, h))
    p = hl
    entries = []
    err = None
    while p + 16 <= len(c) and len(entries) < cnt:
        l, idx, ft = unpack_from('<LLQ', c, p)
        if l < 16 or p + l > len(c):
            err = "bad catalog entry #%d at %d (length %d)" % (len(entries) + 1, p, l)
            break
        entries.append((idx, c[p + 16:p + l].decode('utf-16le', 'replace').split('\x00')[0], _filetime(ft)))
        p += l
    if not err and len(entries) != cnt: err = "catalog has %d of %d entries (truncated?)" % (len(entries), cnt)
    check = image_checker("jpg", log)
    streams = {s[0] for s in ole.listdir() if len(s) == 1}
    out = []
    bad = missing = 0
    first = None
    for idx, name, t in entries:
        sn = str(idx)[::-1]
        if sn not in streams:
            missing += 1
            out.append((idx, name, t, "MISSING"))
            if first is None: first = "no thumbnail stream for #%d %s" % (idx, name)
            continue
        b = ole.openstream(sn).read()
        e = 0
        if len(b) < 12: e = 10
        else:
            hlen, typ, size = unpack_from('<LLL', b, 0)
            img = b[hlen:]
            if size != len(img) or hlen < 12: e = 10
            elif img[:3] != b'\xff\xd8\xff' and len(img) >= 16:   # regi tipus: meg 16 byte fejlec, JPEG Huffman tablak nelkul
                img = img[16:]
                if b'\xff\xc4' not in img[:512]: img = img[:2] + STD_DHT + img[2:]
            if not e and check: e = check(img)
        state = "BAD" if e else "OK" if check else "-"
        if e:
            bad += 1
            if first is None: first = "thumbnail #%d (%s) bad" % (idx, name)
        log("DB: #%d %s %s %s" % (idx, name, t.strftime('%Y-%m-%d %H:%M:%S') if t else "-", state))
        out.append((idx, name, t, state))
    extra = streams - {str(i)[::-1] for i, n, t in entries} - {"Catalog"}
    if extra: log("WARNING: %d thumbnail streams without catalog entry" % len(extra))
    if not err and (bad or missing): err = "%d of %d thumbnails bad, %d missing, first: %s" % (bad, len(entries), missing, first)
    return err, out


def check_blips(d, log):
    """ visszaad: (kepek szama, hibas kepek szama, elso hiba leirasa) """
    cnt = bad = 0
    first = None
    checker = lambda fmt: image_checker(fmt, log)
    for rt, (fmt, inst1, inst2) in blip_types.items():
        pat = bytes([rt & 0xFF, rt >> 8])
        i = d.find(pat, 2)
        while i >= 0:
            p = i - 2
            verinst, l = unpack_from('<HxxL', d, p) if p + 8 <= len(d) else (1, 0)
            inst = verinst >> 4
            if verinst & 0xF == 0 and (inst in inst1 or inst in inst2):
                start = p + 8 + (16 if inst in inst1 else 32) + 1   # recHeader + UID(-ok) + tag
                end = p + 8 + l
                img = d[start:end]
                if img[:3] == b'\xff\xd8\xff' or img[:8] == b'\x89PNG\r\n\x1a\n':
                    c = checker(fmt)
                    if end > len(d) or c is not None:
                        cnt += 1
                        e = 10 if end > len(d) else c(img)
                        log("OLE: embedded %s image at %d, %d bytes%s" % (fmt, start, len(img), " BAD" if e else ""))
                        if e:
                            bad += 1
                            if first is None: first = "%s image at %d (%d bytes)" % (fmt, start, l)
            i = d.find(pat, i + 1)
    return cnt, bad, first


###############################################################################################################################
# FAT konzisztencia: minden lanc pontosan akkora, mint a stream, ENDOFCHAIN-nel zarul, es egy szektor csak egy lanchoz tartozik
# (az olefile csak azt nezi, hogy ket stream ne ugyanazon a szektoron kezdodjon, es a tul hosszu lancot eltuti)
###############################################################################################################################

def check_fat(ole):
    """ visszaad: hibauzenet vagy None. A streameket elotte vegig kell olvasni (a minifat-ot csak akkor tolti be). """
    owners = {"big": {}, "mini": {}}

    def walk(domain, fat, start, count, name):
        """ count: az elvart lanchossz (None: ismeretlen, pl. konyvtar) """
        own = owners[domain]
        s = start
        n = 0
        while s != ENDOFCHAIN:
            if s >= len(fat): return "%s: sector index %d out of range" % (name, s)
            if s in own: return "%s: sector %d also used by %s" % (name, s, own[s])
            own[s] = name
            n += 1
            if count is not None and n > count: return "%s: chain longer than stream size (%d sectors expected)" % (name, count)
            s = fat[s]
            if s >= 0xFFFFFFFA and s != ENDOFCHAIN: return "%s: chain ends with 0x%X instead of ENDOFCHAIN" % (name, s)
        if count is not None and n != count: return "%s: chain has %d of %d sectors" % (name, n, count)
        return None

    ss = ole.sectorsize
    err = walk("big", ole.fat, ole.first_dir_sector, None, "directory")
    if not err and ole.num_mini_fat_sectors: err = walk("big", ole.fat, ole.first_mini_fat_sector, ole.num_mini_fat_sectors, "MiniFAT")
    root = ole.root
    if not err and root.size: err = walk("big", ole.fat, root.isectStart, (root.size + ss - 1) // ss, "MiniStream")
    for e in ole.listdir(streams=True, storages=False):
        if err: break
        ent = ole.entry(e)
        if ent.size == 0: continue
        if ent.size >= ole.minisectorcutoff: err = walk("big", ole.fat, ent.isectStart, (ent.size + ss - 1) // ss, "/".join(e))
        elif ole.minifat is not None: err = walk("mini", ole.minifat, ent.isectStart, (ent.size + ole.minisectorsize - 1) // ole.minisectorsize, "/".join(e))
    return err


###############################################################################################################################
# property set streamek (\x05SummaryInformation, \x05DocumentSummaryInformation, ...): MS-OLEPS szerkezet ellenorzese.
# Szinte minden OLE alapu program irja oket, igy az ismeretlen formatumoknal is van legalabb egy tartalmi ellenorzes.
###############################################################################################################################

FMTID_SummaryInformation = b'\xe0\x85\x9f\xf2\xf9\x4f\x68\x10\xab\x91\x08\x00\x2b\x27\xb3\xd9'

# VT tipus -> fix meret (byte)
vt_sizes = {0: 0, 1: 0, 2: 2, 3: 4, 4: 4, 5: 8, 6: 8, 7: 8, 0x0A: 4, 0x0B: 2, 0x10: 1, 0x11: 1, 0x12: 2, 0x13: 4, 0x14: 8, 0x15: 8, 0x16: 4, 0x17: 4, 0x40: 8, 0x48: 16}


def vt_value_end(d, p, vt, end, unicode):
    """
    egy (tipus fejlec nelkuli) ertek vege, vagy None ha ismeretlen tipus. Kivetelt dob, ha kilog.
    unicode: a property set kodlapja CP_WINUNICODE (1200), ekkor a vektorban levo LPSTR-ek 4 byte-ra kerekitettek
    """
    def pad4(x): return (x + 3) & ~3
    if vt in vt_sizes: return p + vt_sizes[vt]
    if vt in (0x08, 0x1E, 0x41, 0x47):         # BSTR, LPSTR, BLOB, CF: meret + adat
        n, = unpack_from('<L', d, p)
        return p + 4 + n
    if vt == 0x1F:                              # LPWSTR: karakterszam + UTF-16
        n, = unpack_from('<L', d, p)
        return p + 4 + n * 2
    if vt & 0x1000:                             # VECTOR
        cnt, = unpack_from('<L', d, p)
        base = vt & 0xFFF
        p += 4
        if cnt > end - p: raise ValueError("vector count %d too large" % cnt)
        for i in range(cnt):
            if base == 0x0C:                    # VARIANT: minden elem sajat tipussal
                t, = unpack_from('<H', d, p)
                q = vt_value_end(d, p + 4, t, end, unicode)
                if q is None: return None
                p = pad4(q)
            else:
                q = vt_value_end(d, p, base, end, unicode)
                if q is None: return None
                p = pad4(q) if base in (0x1F, 0x41, 0x47) or (base in (0x08, 0x1E) and unicode) else q
        return p
    return None


def check_propset(d, log):
    """ visszaad: (hibauzenet vagy None, AppName vagy None) """
    if len(d) < 48: return "stream too short (%d bytes)" % len(d), None
    order, version, sysid = unpack_from('<HHL', d, 0)
    nsets, = unpack_from('<L', d, 24)
    if order != 0xFFFE or version > 1 or nsets < 1 or nsets > 2 or 28 + nsets * 20 > len(d):
        return "bad header (byte order 0x%04X, version %d, %d sets)" % (order, version, nsets), None
    appname = None
    for s in range(nsets):
        fmtid = d[28 + s * 20:44 + s * 20]
        off, = unpack_from('<L', d, 44 + s * 20)
        def valid(o):
            if o < 0 or o + 8 > len(d): return False
            size, nprop = unpack_from('<LL', d, o)
            return o + size <= len(d) and 8 + nprop * 8 <= size
        if not valid(off):
            # a Mac-es Excel paratlan hosszu elso set utan 1 byte-tal elszamolja a masodik set helyet
            near = [o for o in (off - 1, off + 1, off - 2, off + 2, off - 3, off + 3) if valid(o)]
            if not near:
                if off + 8 > len(d): return "property set #%d offset %d outside of stream" % (s, off), None
                return "property set #%d: bad size %d / %d properties" % ((s,) + unpack_from('<LL', d, off)), None
            log("WARNING: property set #%d found at %d instead of %d" % (s, near[0], off))
            off = near[0]
        size, nprop = unpack_from('<LL', d, off)
        end = off + size
        codepage = None
        for i in range(nprop):   # a kodlap (property 1) kell a stringek meretehez
            pid, poff = unpack_from('<LL', d, off + 8 + i * 8)
            if pid == 1 and poff + 8 <= size and unpack_from('<H', d, off + poff)[0] == 2: codepage, = unpack_from('<H', d, off + poff + 4)
        for i in range(nprop):
            pid, poff = unpack_from('<LL', d, off + 8 + i * 8)
            if poff < 8 + nprop * 8 or poff + 4 > size: return "property set #%d: property 0x%X offset %d outside of set" % (s, pid, poff), None
            if pid == 0: continue   # dictionary: nincs tipus fejlece
            vt, = unpack_from('<H', d, off + poff)
            try:
                q = vt_value_end(d, off + poff + 4, vt, end, codepage == 1200)
            except Exception as e:
                return "property set #%d: property 0x%X (type 0x%X) unreadable: %s" % (s, pid, vt, e), None
            if q is not None and q > end: return "property set #%d: property 0x%X (type 0x%X) value outside of set" % (s, pid, vt), None
            if fmtid == FMTID_SummaryInformation and pid == 0x12 and vt == 0x1E:   # PIDSI_APPNAME
                n, = unpack_from('<L', d, off + poff + 4)
                raw = d[off + poff + 8:off + poff + 8 + n]
                try: appname = raw.decode('utf-16le' if codepage == 1200 else 'cp%d' % codepage if codepage else 'latin1').rstrip('\x00')
                except Exception: appname = raw.decode('latin1').rstrip('\x00')
    return None, appname


###############################################################################################################################
# XLS: a BIFF rekordok lefedik a Workbook streamet, BOF/EOF parok, a BOUNDSHEET-ek BOF rekordra mutatnak
###############################################################################################################################

def check_biff(d, log):
    """ visszaad: (hibauzenet vagy None, a MSODRAWINGGROUP rekordok (+CONTINUE) osszefuzott adata) """
    p = 0
    depth = 0
    bofs = set()
    sheets = []
    encrypted = False
    isBIFF8 = True
    drawing = []
    lastop = 0
    while p + 4 <= len(d):
        op, l = unpack_from('<HH', d, p)
        if depth == 0 and bofs:
            # az utolso EOF utan csak 0 kitoltes lehet (az Excel min. 4096 byte-ra egesziti ki a streamet), vagy ujabb BOF
            if not any(d[p:]): break
            if op != 0x0809: return "garbage after EOF record at %d" % p, None
        if p + 4 + l > len(d): return "record 0x%04X at %d overruns stream (%d+%d > %d)" % (op, p, p + 4, l, len(d)), None
        if op == 0x0809:                  # BOF
            if l >= 4:
                vers, dt = unpack_from('<HH', d, p + 4)
                if depth == 0: isBIFF8 = vers == 0x0600
                dStreamType = {5: 'workbook', 6: 'Visual Basic Module', 0x10: 'dialog sheet/worksheet', 0x20: 'chart sheet', 0x40: 'Excel 4.0 macro sheet', 0x100: 'Workspace file'}
                log('XLS.BOF - %s %s' % ({0x0500: 'BIFF5/BIFF7', 0x0600: 'BIFF8'}.get(vers, '0x%04x' % vers), dStreamType.get(dt, '0x%04x' % dt)))
            bofs.add(p)
            depth += 1
        elif op == 0x000A:                # EOF
            depth -= 1
            if depth < 0: return "EOF record without BOF at %d" % p, None
        elif op == 0x0085 and l >= 6:     # BOUNDSHEET
            positionBOF, sheetState, sheetType = unpack_from('<IBB', d, p + 4)
            sheets.append(positionBOF)
            dSheetType = {0: 'worksheet or dialog sheet', 1: 'Excel 4.0 macro sheet', 2: 'chart', 6: 'Visual Basic module'}
            dSheetState = {0: 'visible', 1: 'hidden', 2: 'very hidden', 3: 'visibility=3'}
            log('XLS.Sheet %s, %s : %s' % (dSheetType.get(sheetType, '%02x' % sheetType), dSheetState[sheetState & 3], ShortXLUnicodeString(d[p + 10:p + 4 + l], isBIFF8) if not encrypted else "?"))
        elif op == 0x002F:                # FILEPASS: titkositott, de a rekordszerkezet olvashato
            encrypted = True
            log("XLS: encrypted")
        if op == 0x00EB or (op == 0x003C and lastop == 0x00EB): drawing.append(d[p + 4:p + 4 + l])   # MSODRAWINGGROUP (+CONTINUE)
        if op != 0x003C: lastop = op     # CONTINUE: az elozo "valodi" rekord folytatasa
        p += 4 + l
    if not bofs: return "no BOF record", None
    if depth > 0: return "missing EOF record (truncated?)", None
    for s in sheets:
        if s not in bofs: return "BOUNDSHEET points to %d, not to a BOF record" % s, None
    return None, (None if encrypted else b''.join(drawing))


###############################################################################################################################
# DOC: FIB ellenorzese, a FibRgFcLcb tablazat hivatkozasai a table streamen belul vannak, a piece table a WordDocument-en belul
###############################################################################################################################

def check_word(ole, wd, log):
    """ visszaad: (hibauzenet vagy None, titkositott-e) """
    err = check_word_fib(ole, wd, log)
    return err, len(wd) >= 0x0C and unpack_from('<H', wd, 0)[0] == 0xA5EC and bool(unpack_from('<H', wd, 0x0A)[0] & 0x0100)


def check_word_fib(ole, wd, log):
    """ visszaad: hibauzenet vagy None """
    if len(wd) < 0x20: return "WordDocument stream too short"
    wIdent, nFib = unpack_from('<HH', wd, 0)
    if wIdent == 0xA5DC:   # Word 6/95: a szoveg a WordDocument streamben, fcMin..fcMac
        fcMin, fcMac = unpack_from('<LL', wd, 0x18)
        log("DOC: Word 6/95 FIB nFib=%d fcMin=%d fcMac=%d" % (nFib, fcMin, fcMac))
        if fcMin > fcMac or fcMac > len(wd): return "bad fcMin/fcMac %d/%d (stream size %d)" % (fcMin, fcMac, len(wd))
        return None
    if wIdent != 0xA5EC: return "bad FIB magic 0x%04X" % wIdent
    flags, = unpack_from('<H', wd, 0x0A)
    encrypted = flags & 0x0100
    table = "1Table" if flags & 0x0200 else "0Table"
    log("DOC: Word 97+ FIB nFib=%d table=%s%s" % (nFib, table, " encrypted" if encrypted else ""))
    if not ole.exists(table): return "missing %s stream" % table
    if encrypted: return None   # a table stream titkositott
    ts = ole.openstream(table).read()
    p = 32
    csw, = unpack_from('<H', wd, p)
    p += 2 + csw * 2
    cslw, = unpack_from('<H', wd, p)
    p += 2 + cslw * 4
    cbRgFcLcb, = unpack_from('<H', wd, p)
    p += 2
    if p + cbRgFcLcb * 8 > len(wd): return "FIB overruns WordDocument stream"
    for i in range(cbRgFcLcb):
        if i == 87: continue   # FibRgFcLcb97 #87: nem fc/lcb par, hanem a modositas ideje (dwLowDateTime/dwHighDateTime)
        fc, lcb = unpack_from('<LL', wd, p + i * 8)
        if lcb and fc + lcb > len(ts): return "FIB entry #%d (%d+%d) outside of %s stream (%d)" % (i, fc, lcb, table, len(ts))
    if cbRgFcLcb <= 33: return None
    # CHPX/PAPX FKP lapok (FibRgFcLcb97 #12/#13: PlcfBteChpx/PlcfBtePapx): 512 byte-os lapok a WordDocument-ben,
    # az utolso byte a futasok szama (crun), elotte crun+1 db novekvo fajlpozicio
    for idx, name, maxrun in [(12, "CHPX", 0x65), (13, "PAPX", 0x1D)]:
        fc, lcb = unpack_from('<LL', wd, p + idx * 8)
        if lcb < 4 or (lcb - 4) % 8: continue
        n = (lcb - 4) // 8
        for pn in unpack_from('<%dL' % n, ts, fc + (n + 1) * 4):
            pg = (pn & 0x3FFFFF) * 512
            if pg + 512 > len(wd): return "%s page %d outside of WordDocument stream" % (name, pn & 0x3FFFFF)
            crun = wd[pg + 511]
            if crun == 0 or crun > maxrun: return "bad %s page %d (crun=%d)" % (name, pn & 0x3FFFFF, crun)
            rgfc = unpack_from('<%dL' % (crun + 1), wd, pg)
            if any(rgfc[i + 1] < rgfc[i] for i in range(crun)): return "bad %s page %d (positions not increasing)" % (name, pn & 0x3FFFFF)
    fcClx, lcbClx = unpack_from('<LL', wd, p + 33 * 8)   # FibRgFcLcb97.fcClx: a piece table
    if not lcbClx: return None
    q = fcClx
    end = fcClx + lcbClx
    while q < end and ts[q] == 0x01:   # Prc (formazasi adatok)
        cb, = unpack_from('<h', ts, q + 1)
        q += 3 + cb
    if q >= end or ts[q] != 0x02: return "bad piece table (Clx) at %d" % fcClx
    lcb, = unpack_from('<L', ts, q + 1)
    q += 5
    if q + lcb > end or lcb < 4 or (lcb - 4) % 12: return "bad piece table size %d" % lcb
    n = (lcb - 4) // 12
    cps = unpack_from('<%dL' % (n + 1), ts, q)
    for i in range(n):
        if cps[i + 1] < cps[i]: return "piece table CPs not increasing"
        fc, = unpack_from('<L', ts, q + (n + 1) * 4 + i * 8 + 2)
        if fc & 0x40000000: off, size = (fc & 0x3FFFFFFF) // 2, cps[i + 1] - cps[i]   # 8 bites szoveg
        else: off, size = fc, (cps[i + 1] - cps[i]) * 2                               # UTF-16 szoveg
        if off + size > len(wd): return "text piece #%d (%d+%d) outside of WordDocument stream (%d)" % (i, off, size, len(wd))
    log("DOC: %d text pieces, %d characters" % (n, cps[-1]))
    return None


###############################################################################################################################
# PPT: a rekordok lefedik a 'PowerPoint Document' streamet, a UserEdit lanc es a persist directory ervenyes rekordokra mutat
###############################################################################################################################

def check_ppt(ole, pd, log):
    """ visszaad: (hibauzenet vagy None, titkositott-e) """
    err = check_ppt_records(ole, pd, log)
    if err == "encrypted": return None, True
    return err, False


def check_ppt_records(ole, pd, log):
    """ visszaad: hibauzenet, "encrypted" vagy None """
    if not ole.exists('Current User'): return "missing Current User stream"
    cu = ole.openstream('Current User').read()
    if len(cu) < 24: return "Current User stream too short"
    rtype, = unpack_from('<H', cu, 2)
    token, offsetToCurrentEdit = unpack_from('<LL', cu, 12)
    if rtype != 0x0FF6: return "bad CurrentUserAtom"
    if token == 0xF3D1C4DF:
        log("PPT: encrypted")
        return "encrypted"   # a rekordok titkositottak
    records = {}
    p = 0
    while p + 8 <= len(pd):
        verinst, rtype, l = unpack_from('<HHL', pd, p)
        if p + 8 + l > len(pd): return "record 0x%04X at %d overruns stream (%d+%d > %d)" % (rtype, p, p + 8, l, len(pd))
        records[p] = rtype
        p += 8 + l
    if p != len(pd) and any(pd[p:]): return "%d bytes garbage at end of stream" % (len(pd) - p)
    log("PPT: %d top level records" % len(records))
    edit = offsetToCurrentEdit
    seen = set()
    while edit:
        if records.get(edit) != 0x0FF5: return "UserEditAtom expected at %d" % edit
        if edit in seen: return "loop in UserEdit chain"
        seen.add(edit)
        offsetLastEdit, offsetPersistDirectory = unpack_from('<LL', pd, edit + 8 + 8)
        if records.get(offsetPersistDirectory) != 0x1772: return "PersistDirectoryAtom expected at %d" % offsetPersistDirectory
        # persist directory: (persistId:20, cPersist:12) + cPersist db offset
        l, = unpack_from('<L', pd, offsetPersistDirectory + 4)
        q = offsetPersistDirectory + 8
        end = q + l
        while q + 4 <= end:
            hdr, = unpack_from('<L', pd, q)
            cnt = hdr >> 20
            for i in range(cnt):
                o, = unpack_from('<L', pd, q + 4 + i * 4)
                if o not in records: return "persist object offset %d is not a record" % o
            q += 4 + cnt * 4
        edit = offsetLastEdit
    return None


###############################################################################################################################


###############################################################################################################################
# OLE_INFO: letrehozas / utolso mentes datuma, szerzo, utoljara mentette, cim, program (a visszaallitott fileok azonositasahoz)
# Forras: a SummaryInformation property set; ha nincs benne utolso mentes (az Excel altalaban nem irja), a gyoker konyvtar
# bejegyzes modositasi ideje. Minden datum helyi idoben (a fileban UTC FILETIME).

def _filetime(x):
    """ FILETIME (100ns 1601 ota, UTC) -> helyi ido datetime, ertelmetlen erteknel None """
    try:
        t = (datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=x // 10)).replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        if datetime.datetime(1980, 1, 1) <= t <= datetime.datetime.now() + datetime.timedelta(days=2): return t
    except Exception:
        pass
    return None

def summary_properties(d):
    """ a SummaryInformation stream (sertult is) -> {pid: ertek}, csak a szoveg (VT_LPSTR/LPWSTR) es FILETIME tipusok """
    props = {}
    try:
        if len(d) < 48 or d[28:44] != FMTID_SummaryInformation: return props
        off, = unpack_from('<L', d, 44)
        size, nprop = unpack_from('<LL', d, off)
        vals = []
        codepage = None
        for i in range(min(nprop, 1000)):
            pid, poff = unpack_from('<LL', d, off + 8 + i * 8)
            p = off + poff
            if p + 8 > len(d): continue
            vt, = unpack_from('<H', d, p)
            if pid == 1 and vt == 2: codepage = unpack_from('<H', d, p + 4)[0]
            vals.append((pid, vt, p + 4))
        enc = {1200: 'utf-16le', 65001: 'utf-8', 10000: 'mac_roman'}.get(codepage, 'cp%d' % codepage if codepage else 'cp1252')
        for pid, vt, p in vals:
            try:
                if vt == 0x1E:
                    n, = unpack_from('<L', d, p)
                    raw = d[p + 4:p + 4 + min(n, 65536)]
                    try: v = raw.decode(enc)
                    except Exception: v = raw.decode('latin1')
                    props[pid] = v.split('\x00')[0].strip()
                elif vt == 0x1F:
                    n, = unpack_from('<L', d, p)
                    props[pid] = d[p + 4:p + 4 + min(n, 32768) * 2].decode('utf-16le', 'replace').split('\x00')[0].strip()
                elif vt == 0x40:
                    props[pid] = _filetime(unpack_from('<Q', d, p)[0])
            except Exception:
                pass
    except Exception:
        pass
    return props

def ole_info(ole):
    """ visszaad: (formatum verzio, letrehozas, modositas, datum forrasa, utoljara mentette, szerzo, cim, program) """
    fver = ""
    try:
        if ole.exists('Workbook'): fver = "BIFF8"
        elif ole.exists('Book'): fver = "BIFF5"
        elif ole.exists('WordDocument'):
            w = ole.openstream('WordDocument').read(4)
            fver = {0xA5DC: "Word6/95", 0xA5EC: "Word97+"}.get(unpack_from('<H', w, 0)[0], "")
        elif ole.exists('PowerPoint Document'): fver = "PPT97+"
    except Exception:
        pass
    props = {}
    try:
        if ole.exists('\x05SummaryInformation'): props = summary_properties(ole.openstream('\x05SummaryInformation').read())
    except Exception:
        pass
    created, modified = props.get(0x0C), props.get(0x0D)
    src_c = src_m = "meta"
    root = ole.root
    if not created:
        created, src_c = _filetime(getattr(root, 'createTime', 0) or 0), "ole"
    if not modified:
        modified, src_m = _filetime(getattr(root, 'modifyTime', 0) or 0), "ole"
    fmt = lambda t: t.strftime('%Y-%m-%d %H:%M:%S') if t else ""
    src = "" if not created and not modified else src_c if src_c == src_m or not created or not modified else src_c + "/" + src_m
    if not created and modified: src = src_m
    if created and not modified: src = src_c
    get = lambda pid: props.get(pid) if isinstance(props.get(pid), str) else ""
    return fver, fmt(created), fmt(modified), src, get(8), get(4), get(2), get(0x12)


def testole(d, debug=False, fname=""):
    """
    visszaad: (hibapont, kiterjesztes). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    Minden filerol kiir egy sort (grep -a -val CSV-be gyujtheto):
      OLE_INFO;filenev;formatum verzio;tipus;letrehozas;utolso mentes;datum forrasa (meta|ole);utoljara mentette;szerzo;cim;program;OK|BAD
    Thumbs.db eseten belyegkepenkent:
      THUMB_INFO;filenev;sorszam;az eredeti kep neve;datum;OK|BAD|MISSING|- (- : nincs testjpeg)
    """
    info = [("",) * 8, []]
    errcnt, ext = _testole(d, debug, info)
    def clean(x): return re.sub(r'[\x00-\x1f\x7f\ufeff]+', ' ', str(x).replace(";", ",")).strip()
    i = info[0]
    print("OLE_INFO;" + ";".join(clean(x) for x in (fname,) + i[:1] + (ext,) + i[1:] + ("OK" if errcnt == 0 else "BAD" if errcnt > 0 else "DUNNO",)))
    # Thumbs.db: a belyegkepek eredeti fajlnevei (a mappa kepei), datummal
    for idx, name, t, state in info[1]:
        print("THUMB_INFO;" + ";".join(clean(x) for x in (fname, idx, name, t.strftime('%Y-%m-%d %H:%M:%S') if t else "", state)))
    return errcnt, ext


def _testole(d, debug, info):

    def log(*args):
        if debug: print(*args)

    errcnt = 0
    ext = "ole"
    try:
        # a hibak (DEFECT_INCORRECT/FATAL szint) kivetelt dobnak, a regi irok artalmatlan furcsasagai csak figyelmeztetesek
        ole = OleFile(d)
    except Exception as e:
        print("ERROR! OLE open failed: %r" % e)
        try: info[0] = ole_info(OleFile(d, strict=False))   # a metaadatok serult filebol is, amennyi kiolvashato
        except Exception: pass
        return 10, ext
    try: info[0] = ole_info(ole)
    except Exception: pass
    for msg in ole.issues:
        log("WARNING: OLE: %s" % msg)
    clsid = ole.root.clsid or "-"
    log("OLE: root CLSID %s" % clsid)
    bad = 0
    propsets = []
    for i in ole.listdir(streams=True, storages=False):
        name = "/".join(i)
        try:
            sd = ole.openstream(i).read()
            log(str(len(sd)) + "\t" + name)
            if i[-1].startswith('\x05'): propsets.append((name, sd))   # property set stream
        except Exception as e:
            bad += 1
            if bad <= 10: print("ERROR! OLE stream %s: %r" % (name, e))
    if bad:
        if bad > 10: print("ERROR! ... %d bad streams total" % bad)
        print("OLE info: CLSID %s" % clsid)
        return errcnt + 10, ext
    err = check_fat(ole)
    if err:
        print("ERROR! OLE FAT: %s" % err)
        errcnt += 10

    appname = None
    for name, sd in propsets:
        err, app = check_propset(sd, log)
        if app and name == '\x05SummaryInformation': appname = app
        if err:
            print("ERROR! OLE property set %s: %s" % (name.replace('\x05', '\\x05'), err))
            errcnt += 10
    if appname: log("OLE: created by %s" % appname)

    err = None
    pictures = None   # a beagyazott kepeket tartalmazo adat
    try:
        if ole.exists('Workbook') or ole.exists('Book'):   # Book: BIFF5 (Excel 5/95)
            ext = "xls"
            for s in ['Workbook', 'Book']:
                if ole.exists(s):
                    err, pictures = check_biff(ole.openstream(s).read(), log)
                    if err:
                        err = "%s: %s" % (s, err)
                        break
        elif ole.exists('WordDocument'):
            ext = "doc"
            err, encrypted = check_word(ole, ole.openstream('WordDocument').read(), log)
            if not err and not encrypted and ole.exists('Data'): pictures = ole.openstream('Data').read()
        elif ole.exists('PowerPoint Document'):
            ext = "ppt"
            err, encrypted = check_ppt(ole, ole.openstream('PowerPoint Document').read(), log)
            if not err and not encrypted and ole.exists('Pictures'): pictures = ole.openstream('Pictures').read()
        elif ole.exists('Catalog'):
            ext = "db"
            err, info[1] = check_thumbs(ole, log)
        elif ole.exists('EncryptedPackage'): log("OLE: encrypted OOXML (docx/xlsx/pptx) document")
        if pictures:
            cnt, bad, first = check_blips(pictures, log)
            if bad:
                print("ERROR! %s: %d of %d embedded images bad, first: %s" % (ext.upper(), bad, cnt, first))
                errcnt += 10
    except Exception as e:
        err = "exception: %r" % e
    if err:
        print("ERROR! %s: %s" % (ext.upper(), err))
        errcnt += 10
    if errcnt: print("OLE info: type %s, CLSID %s%s" % (ext, clsid, ", created by " + appname if appname else ""))
    return errcnt, ext


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "ole/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res, ext = testole(f.read(), debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res, ext)
