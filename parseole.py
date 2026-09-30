#! /usr/bin/python3

# parseole.py: onallo OLE2 (Compound File Binary, MS-CFB) olvaso az olefile kivaltasara, csak a Python standard konyvtarat
# hasznalja. doc, xls, ppt, msg, Thumbs.db, ... fileok stream-jeinek es metaadatainak kiolvasasa.
#
#   ole = OleFile(data)                   # strict: a hibak (serult file) OleFileError kivetelt dobnak
#   ole = OleFile(data, strict=False)     # megengedo: csak a nem OLE file dob kivetelt, a hibak az ole.issues listaba
#   ole.listdir(), ole.exists(path), ole.openstream(path).read(), ole.root, ole.issues
#   summary_properties(ole.openstream('\x05SummaryInformation').read())   # {pid: ertek}
#   ole_info(ole)                         # formatum verzio, datumok, szerzo, cim, program
#   thumbs_catalog(ole)                   # Thumbs.db: az eredeti fajlnevek es datumok
#   check_fat(ole), check_propset(data)   # a kontener (FAT/MiniFAT lancok) es a property setek szerkezete: hibauzenet vagy None
#
# A doc/xls/ppt szerkezet es a beagyazott kepek ellenorzese a testole.py-ban van.

import datetime
import io
from struct import unpack_from


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
        if ss not in (512, 4096):
            # megengedo mod: ertelmetlen szektor meretnel (pl. 1 byte) a parser sokat dolgozna feleslegesen, es a file
            # tartalma sem latszana (egy byte atirasaval elrejtheto lenne): a verzio szerinti szabvanyos meretet hasznaljuk
            ss = self.sectorsize = 4096 if self.dll_version == 4 else 512
        self.minisectorsize = 1 << min(mini_shift, 16)
        if self.minisectorsize != 64:
            self.defect(INCORRECT, "incorrect mini_sector_size in OLE header")
            self.minisectorsize = 64
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
        """ a streamek (es storage-ok) utvonalai, melysegi bejarassal. Iterativ: a melyen egymasba agyazott (rosszindulatu) fa sem dob RecursionError-t """
        out = []
        if self.root is None: return out
        todo = [(iter(self.root.kids), [])]
        while todo:
            k = next(todo[-1][0], None)
            if k is None:
                todo.pop()
                continue
            prefix = todo[-1][1]
            if k.type == 1:
                if storages: out.append(prefix + [k.name])
                todo.append((iter(k.kids), prefix + [k.name]))
            elif k.type == 2 and streams:
                out.append(prefix + [k.name])
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
# FAT konzisztencia: minden lanc pontosan akkora, mint a stream, ENDOFCHAIN-nel zarul, es egy szektor csak egy lanchoz tartozik
# (az OleFile megnyitaskor csak azt nezi, hogy ket stream ne ugyanazon a szektoron kezdodjon, es a tul hosszu lancot levagja)
###############################################################################################################################

def check_fat(ole):
    """ visszaad: hibauzenet vagy None """
    if ole.minifat is None and ole.root is not None and ole.root.size:
        # ha meg nem volt kis stream olvasva: betoltjuk; ha a (hasznalaton kivuli) MiniFAT serult, a kis streamek lancait kihagyjuk
        try: ole.load_minifat()
        except OleFileError: ole.minifat = None
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
    if root is None: return err or "missing root directory entry"   # megengedo modban, pl. ures konyvtar lanc
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

# VT tipus -> fix meret (byte)
vt_sizes = {0: 0, 1: 0, 2: 2, 3: 4, 4: 4, 5: 8, 6: 8, 7: 8, 0x0A: 4, 0x0B: 2, 0x10: 1, 0x11: 1, 0x12: 2, 0x13: 4, 0x14: 8, 0x15: 8, 0x16: 4, 0x17: 4, 0x40: 8, 0x48: 16}


def vt_value_end(d, p, vt, end, unicode, variant_pad=True):
    """
    egy (tipus fejlec nelkuli) ertek vege, vagy None ha ismeretlen tipus. Kivetelt dob, ha kilog.
    unicode: a property set kodlapja CP_WINUNICODE (1200), ekkor a vektorban levo LPSTR-ek 4 byte-ra kerekitettek
    variant_pad: a VARIANT vektor elemei 4 byte-ra kerekitettek (False: a nem unicode LPSTR/BSTR elemek nem, pl. egyes
    Excel verziok a HeadingPairs-ben)
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
                q = vt_value_end(d, p + 4, t, end, unicode, variant_pad)
                if q is None: return None
                if variant_pad: p = pad4(q)
                elif t in (0x08, 0x1E) and not unicode: p = q          # kerekites nelkuli szoveg
                else: p = p + pad4(q - p)                            # az elemhez kepest kerekitve
            else:
                q = vt_value_end(d, p, base, end, unicode, variant_pad)
                if q is None: return None
                p = pad4(q) if base in (0x1F, 0x41, 0x47) or (base in (0x08, 0x1E) and unicode) else q
        return p
    return None


def check_propset(d, log=lambda *args: None):
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
                if q is not None and q > end: raise ValueError("outside")
            except Exception as e:
                # VARIANT vektorban kerekites nelkuli szovegek (iroi furcsasag): ha igy olvashato, csak figyelmeztetes
                try:
                    q = vt_value_end(d, off + poff + 4, vt, end, codepage == 1200, variant_pad=False) if vt & 0x1000 else None
                except Exception:
                    q = None
                if q is None or q > end:
                    if str(e) == "outside": return "property set #%d: property 0x%X (type 0x%X) value outside of set" % (s, pid, vt), None
                    return "property set #%d: property 0x%X (type 0x%X) unreadable: %s" % (s, pid, vt, e), None
                log("WARNING: property set #%d: property 0x%X: VARIANT vector with unpadded strings" % (s, pid))
            if q is not None and q > end: return "property set #%d: property 0x%X (type 0x%X) value outside of set" % (s, pid, vt), None
            if fmtid == FMTID_SummaryInformation and pid == 0x12 and vt == 0x1E:   # PIDSI_APPNAME
                n, = unpack_from('<L', d, off + poff + 4)
                raw = d[off + poff + 8:off + poff + 8 + n]
                try: appname = raw.decode('utf-16le' if codepage == 1200 else 'cp%d' % codepage if codepage else 'latin1').rstrip('\x00')
                except Exception: appname = raw.decode('latin1').rstrip('\x00')
    return None, appname


###############################################################################################################################
# metaadatok
###############################################################################################################################

FMTID_SummaryInformation = b'\xe0\x85\x9f\xf2\xf9\x4f\x68\x10\xab\x91\x08\x00\x2b\x27\xb3\xd9'

# OLE_INFO (testole): letrehozas / utolso mentes datuma, szerzo, utoljara mentette, cim, program (a visszaallitott fileok azonositasahoz)
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



def thumbs_catalog(ole):
    """
    Thumbs.db (Windows XP/2003 Intezo belyegkep gyorsitotar) Catalog stream: bejegyzesenkent hossz, sorszam, FILETIME,
    UTF-16 nev. A belyegkepek streamjeinek neve a sorszam visszafele (12 -> "21").
    visszaad: (hibauzenet vagy None, (verzio, bejegyzesek szama, szelesseg, magassag), [(sorszam, eredeti nev, datum)])
    """
    c = ole.openstream('Catalog').read()
    if len(c) < 16: return "Catalog stream too short", None, []
    hl, ver, cnt, w, h = unpack_from('<HHLLL', c, 0)
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
    return err, (ver, cnt, w, h), entries


if __name__ == "__main__":
    # a streamek listaja es a metaadatok (megengedo modban, serult filera is)
    import sys
    for n in sys.argv[1:]:
        print("==================== %s" % n)
        try:
            ole = OleFile(open(n, "rb").read(), strict=False)
        except Exception as e:
            print("ERROR: %r" % e)
            continue
        for msg in ole.issues: print("issue:", msg)
        for path in ole.listdir():
            e = ole.entry(path)
            print("%10d  %s" % (e.size, "/".join(path)))
        print("info:", ole_info(ole))
        if ole.exists('Catalog'):
            err, hdr, entries = thumbs_catalog(ole)
            for idx, name, t in entries: print("thumb #%d %s %s" % (idx, name, t or ""))
            if err: print("catalog error:", err)
