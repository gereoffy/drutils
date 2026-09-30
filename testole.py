#! /usr/bin/python3

# OLE2 (Compound File) alapu fileok ellenorzese: doc, xls, ppt, Thumbs.db, msg, ...
# Az OLE olvaso (a streamek es a metaadatok kiolvasasa) a parseole.py-ban van, itt az ervenyesseg ellenorzese.

from struct import unpack, unpack_from

from parseole import OleFile, check_fat, check_propset, ole_info, thumbs_catalog
from fileinfo import print_info, result
from testjpeg import testjpeg
from testpng import testpng


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
# beagyazott kepek (OfficeArt BLIP rekordok: doc Data stream, ppt Pictures stream, xls MSODRAWINGGROUP):
# a JPEG/PNG kepeket a testjpeg/testpng-vel ellenorizzuk
###############################################################################################################################

# recType -> (formatum, recInstance-ek 1 UID-dal, recInstance-ek 2 UID-dal)
blip_types = {0xF01D: ("jpg", (0x46A, 0x6E2), (0x46B, 0x6E3)), 0xF02A: ("jpg", (0x46A, 0x6E2), (0x46B, 0x6E3)), 0xF01E: ("png", (0x6E0,), (0x6E1,))}


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
    Thumbs.db: a Catalog bejegyzesei hianytalanok, minden bejegyzeshez van belyegkep stream, a stream fejlece (fejlec
    hossz, tipus, meret) stimmel es a JPEG dekodolhato.
    visszaad: (hibauzenet vagy None, [(sorszam, eredeti nev, datum, OK|BAD|MISSING)])
    """
    err, hdr, entries = thumbs_catalog(ole)
    if hdr: log("DB: Thumbs.db catalog version %d, %d entries, thumbnails %dx%d" % hdr)
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
            if not e: e = testjpeg(img, embedded=True)
        state = "BAD" if e else "OK"
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
                    cnt += 1
                    e = 10 if end > len(d) else testjpeg(img, embedded=True) if fmt == "jpg" else testpng(img)
                    log("OLE: embedded %s image at %d, %d bytes%s" % (fmt, start, len(img), " BAD" if e else ""))
                    if e:
                        bad += 1
                        if first is None: first = "%s image at %d (%d bytes)" % (fmt, start, l)
            i = d.find(pat, i + 1)
    return cnt, bad, first


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


def testole(d, debug=False, fname=""):
    """
    visszaad: (hibapont, kiterjesztes). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    Minden filerol kiir egy sort (grep -a -val CSV-be gyujtheto):
      OLE_INFO;filenev;formatum verzio;tipus;letrehozas;utolso mentes;datum forrasa (meta|ole);utoljara mentette;szerzo;cim;program;OK|BAD
    Thumbs.db eseten belyegkepenkent:
      THUMB_INFO;filenev;sorszam;az eredeti kep neve;datum;OK|BAD|MISSING
    """
    info = [("",) * 8, []]
    errcnt, ext = _testole(d, debug, info)
    i = info[0]
    print_info("OLE", (fname,) + i[:1] + (ext,) + i[1:] + (result(errcnt),))
    # Thumbs.db: a belyegkepek eredeti fajlnevei (a mappa kepei), datummal
    for idx, name, t, state in info[1]:
        print_info("THUMB", (fname, idx, name, t, state), set_time=False)
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
