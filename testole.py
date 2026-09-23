#! /usr/bin/python3

# OLE2 (Compound File) alapu fileok: doc, xls, ppt, Thumbs.db, msg, ...
# pip3 install olefile

from struct import unpack, unpack_from

try:
  import olefile
  support_ole=True
except:
  support_ole=False


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


def check_blips(d, log):
    """ visszaad: (kepek szama, hibas kepek szama, elso hiba leirasa) """
    from testjpeg import testjpeg
    from testpng import testpng
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
                    e = 10 if end > len(d) else (testjpeg(img, embedded=True) if fmt == "jpg" else testpng(img))
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
    """ visszaad: hibauzenet vagy None. A streameket elotte vegig kell olvasni (a minifat-ot az olefile csak akkor tolti be). """
    ENDOFCHAIN = olefile.ENDOFCHAIN
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
        ent = ole.direntries[ole._find(e)]
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


def testole(d, debug=False):
    """ visszaad: (hibapont, kiterjesztes). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """

    def log(*args):
        if debug: print(*args)

    errcnt = 0
    ext = "ole"
    try:
        # a DEFECT_UNSURE/POTENTIAL hibakat (pl. szemet a stream meret felso 32 bitjeben regi iroknal) csak jelezzuk
        ole = olefile.OleFileIO(d, raise_defects=olefile.DEFECT_INCORRECT)
    except Exception as e:
        print("ERROR! OLE open failed: %r" % e)
        return 10, ext
    with ole:
        for exctype, msg in ole.parsing_issues:
            log("WARNING: %s: %s" % (exctype.__name__, msg))
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
            elif ole.exists('Catalog'): ext = "db"
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
    with open(n, "rb") as f: res, ext = testole(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res, ext)
