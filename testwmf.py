#! /usr/bin/python3

# Windows Metafile (WMF: placeable/Aldus es sima) es Enhanced Metafile (EMF) ellenorzes.
# Formatum leiras: [MS-WMF] Windows Metafile Format, [MS-EMF] Enhanced Metafile Format.

from struct import unpack_from

PLACEABLE_KEY = b'\xd7\xcd\xc6\x9a'

# [MS-WMF] 2.1.1.1 RecordType: az ismert rekord tipusok
wmf_functions = {
    0x0000: "EOF", 0x001E: "SAVEDC", 0x0035: "REALIZEPALETTE", 0x0037: "SETPALENTRIES", 0x00F7: "CREATEPALETTE",
    0x0102: "SETBKMODE", 0x0103: "SETMAPMODE", 0x0104: "SETROP2", 0x0105: "SETRELABS", 0x0106: "SETPOLYFILLMODE",
    0x0107: "SETSTRETCHBLTMODE", 0x0108: "SETTEXTCHAREXTRA", 0x0127: "RESTOREDC", 0x012A: "INVERTREGION", 0x012B: "PAINTREGION",
    0x012C: "SELECTCLIPREGION", 0x012D: "SELECTOBJECT", 0x012E: "SETTEXTALIGN", 0x0139: "RESIZEPALETTE", 0x0142: "DIBCREATEPATTERNBRUSH",
    0x0149: "SETLAYOUT", 0x01F0: "DELETEOBJECT", 0x01F9: "CREATEPATTERNBRUSH", 0x0201: "SETBKCOLOR", 0x0209: "SETTEXTCOLOR",
    0x020A: "SETTEXTJUSTIFICATION", 0x020B: "SETWINDOWORG", 0x020C: "SETWINDOWEXT", 0x020D: "SETVIEWPORTORG", 0x020E: "SETVIEWPORTEXT",
    0x020F: "OFFSETWINDOWORG", 0x0211: "OFFSETVIEWPORTORG", 0x0213: "LINETO", 0x0214: "MOVETO", 0x0220: "OFFSETCLIPRGN",
    0x0228: "FILLREGION", 0x0231: "SETMAPPERFLAGS", 0x0234: "SELECTPALETTE", 0x02FA: "CREATEPENINDIRECT", 0x02FB: "CREATEFONTINDIRECT",
    0x02FC: "CREATEBRUSHINDIRECT", 0x0324: "POLYGON", 0x0325: "POLYLINE", 0x0410: "SCALEWINDOWEXT", 0x0412: "SCALEVIEWPORTEXT",
    0x0415: "EXCLUDECLIPRECT", 0x0416: "INTERSECTCLIPRECT", 0x0418: "ELLIPSE", 0x0419: "FLOODFILL", 0x041B: "RECTANGLE",
    0x041F: "SETPIXEL", 0x0429: "FRAMEREGION", 0x0436: "ANIMATEPALETTE", 0x0521: "TEXTOUT", 0x0538: "POLYPOLYGON",
    0x0548: "EXTFLOODFILL", 0x061C: "ROUNDRECT", 0x061D: "PATBLT", 0x0626: "ESCAPE", 0x06FF: "CREATEREGION", 0x0817: "ARC",
    0x081A: "PIE", 0x0830: "CHORD", 0x0922: "BITBLT", 0x0940: "DIBBITBLT", 0x0A32: "EXTTEXTOUT", 0x0B23: "STRETCHBLT",
    0x0B41: "DIBSTRETCHBLT", 0x0D33: "SETDIBTODEV", 0x0F43: "STRETCHDIB",
}

# fix meretu rekordok (word-ben, a 3 word-os rekord fejleccel egyutt). Nehany rekord vegen opcionalis kitolto word lehet.
fixed_sizes = {0x001E: (3,), 0x0127: (4,), 0x012D: (4,), 0x01F0: (4,), 0x012C: (4,), 0x0103: (4,),
               0x0102: (4, 5), 0x0104: (4, 5), 0x0106: (4, 5), 0x012E: (4, 5),
               0x0201: (5,), 0x0209: (5,), 0x020B: (5,), 0x020C: (5,), 0x020D: (5,), 0x020E: (5,), 0x0213: (5,), 0x0214: (5,),
               0x0416: (7,), 0x0415: (7,), 0x0418: (7,), 0x041B: (7,), 0x02FC: (7,), 0x02FA: (8, 9), 0x081A: (11,), 0x0817: (11,), 0x0830: (11,)}

# DIB-et tartalmazo rekordok: a BITMAPINFOHEADER elotti parameterek merete byte-ban
dib_offsets = {0x0940: 16, 0x0B41: 20, 0x0F43: 22, 0x0142: 4}


def check_dib(d, p, end):
    """ beagyazott DIB (BITMAPINFOHEADER + paletta + pixelek) merete. visszaad: hibauzenet vagy None """
    if p + 16 > end: return "DIB header truncated"
    bisize, = unpack_from('<L', d, p)
    if bisize == 12:
        w, h, planes, bits = unpack_from('<HHHH', d, p + 4)
        comp = 0
        clr = 0
    elif bisize in (40, 52, 56, 64, 108, 124):
        if p + 40 > end: return "DIB header truncated"
        w, h, planes, bits, comp, isize, xr, yr, clr = unpack_from('<llHHLLllL', d, p + 4)
    else:
        return "bad DIB header size %d" % bisize
    if planes != 1 or bits not in (1, 4, 8, 16, 24, 32): return "bad DIB header (planes %d, %d bits/pixel)" % (planes, bits)
    if comp in (0, 3):    # tomoritetlen: a pixel adat merete kiszamolhato
        ncolors = clr if clr else (1 << bits if bits <= 8 else 0)
        palette = ncolors * (3 if bisize == 12 else 4) + (12 if comp == 3 and bisize == 40 else 0)
        stride = ((abs(w) * bits + 31) // 32) * 4
        if p + bisize + palette + stride * abs(h) > end: return "DIB pixel data truncated (%dx%d, %d bits)" % (w, h, bits)
    return None


def check_record(d, p, size, fn):
    """ az ismert rekordok parametereinek osszhangja. visszaad: hibauzenet vagy None """
    q = p + 6
    end = p + size * 2
    if fn in fixed_sizes and size not in fixed_sizes[fn]: return "size %d instead of %s" % (size, "/".join(map(str, fixed_sizes[fn])))
    if fn in (0x0324, 0x0325):          # POLYGON, POLYLINE: pontok szama + pontok
        n, = unpack_from('<h', d, q)
        if n < 0 or size != 4 + 2 * n: return "%d points in %d words" % (n, size)
    elif fn == 0x0538:                  # POLYPOLYGON: poligonok szama, pontszamok, pontok
        np_, = unpack_from('<H', d, q)
        if 4 + np_ > size: return "%d polygons in %d words" % (np_, size)
        pts = sum(unpack_from('<%dH' % np_, d, q + 2))
        if size != 4 + np_ + 2 * pts: return "%d polygons / %d points in %d words" % (np_, pts, size)
    elif fn == 0x0521:                  # TEXTOUT: hossz, szoveg (paros), y, x
        n, = unpack_from('<H', d, q)
        if size != 4 + (n + 1) // 2 + 2: return "string length %d in %d words" % (n, size)
    elif fn == 0x0A32:                  # EXTTEXTOUT: y, x, hossz, opciok, [rect], szoveg, [dx tomb]
        y, x, n, opt = unpack_from('<hhhH', d, q)
        base = 7 + (4 if opt & 0x0006 else 0) + (n + 1) // 2
        if n < 0 or not (base <= size <= base + n + 1): return "string length %d in %d words" % (n, size)
    elif fn in dib_offsets and size * 2 > 6 + dib_offsets[fn] + 16:
        err = check_dib(d, q + dib_offsets[fn], end)
        if err: return err
    return None


def testwmf(data, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_wmf(data, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_wmf(d, debug):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    p = 0
    if d[:4] == PLACEABLE_KEY:
        # Aldus placeable header: key, hmf, bbox, inch, reserved, checksum (az elso 10 word XOR-ja)
        if n < 22 + 18:
            print("ERROR! WMF: truncated header")
            return 10
        w = unpack_from('<10H', d, 0)
        ck = 0
        for x in w: ck ^= x
        left, top, right, bottom, inch = unpack_from('<hhhhH', d, 6)
        log("WMF: placeable, bbox %d,%d-%d,%d, %d units/inch" % (left, top, right, bottom, inch))
        if ck != unpack_from('<H', d, 20)[0]:
            print("ERROR! WMF: bad placeable header checksum")
            return 10
        p = 22
    # METAHEADER: tipus (1: memoria, 2: disk), header meret (9 word), verzio, meret (word), objektumok, max. rekord, 0
    ftyp, hsize, vers, size, objs, maxr, memb = unpack_from('<HHHLHLH', d, p)
    log("WMF: type %d, version 0x%04X, %d words, %d objects, max record %d words" % (ftyp, vers, size, objs, maxr))
    if ftyp not in (1, 2) or hsize != 9 or vers not in (0x0100, 0x0300):
        print("ERROR! WMF: bad header (type %d, header size %d, version 0x%04X)" % (ftyp, hsize, vers))
        return 10
    start = p
    p += 18
    nrec = 0
    eof = None
    while p + 6 <= n:
        rsize, fn = unpack_from('<LH', d, p)
        if rsize < 3 or p + rsize * 2 > n:
            print("ERROR! WMF: record #%d at %d: bad size %d words (file %d bytes)" % (nrec, p, rsize, n))
            return 10
        if fn not in wmf_functions:
            print("ERROR! WMF: record #%d at %d: unknown function 0x%04X" % (nrec, p, fn))
            return 10
        if rsize > maxr:
            print("ERROR! WMF: record #%d at %d (%s): %d words, larger than max record size %d" % (nrec, p, wmf_functions[fn], rsize, maxr))
            return 10
        err = check_record(d, p, rsize, fn)
        if err:
            print("ERROR! WMF: record #%d at %d (%s): %s" % (nrec, p, wmf_functions[fn], err))
            return 10
        nrec += 1
        p += rsize * 2
        if fn == 0:
            eof = p
            break
    if eof is None:
        print("ERROR! WMF: missing EOF record (truncated?)")
        return 10
    log("WMF: %d records" % nrec)
    if start + size * 2 > eof + 6 and start + size * 2 <= n:
        # a fejlec szerint meg adatnak kellene jonnie: a (hamis) EOF rekordot valoszinuleg serules hozta letre
        print("ERROR! WMF: EOF record at word %d, but header size is %d words" % ((eof - start) // 2, size))
        return 10
    if start + size * 2 != eof: log("WARNING: size in header %d words, data ends at %d words" % (size, (eof - start) // 2))
    if eof < n:
        if d[eof:].strip(b'\x00'): log("WARNING: %d bytes of garbage after EOF record" % (n - eof))
        else: log("WARNING: %d zero bytes after EOF record" % (n - eof))
    return 0


###############################################################################################################################
# EMF: 32 bites rekordok (tipus, meret), az elso EMR_HEADER (" EMF" alairas, file meret, rekordszam), az utolso EMR_EOF
###############################################################################################################################

EMR_HEADER = 1
EMR_EOF = 14
EMR_MAX = 122     # [MS-EMF] 2.1.1 RecordType: 1..122

def check_emf_record(d, p, size, typ):
    """ az ismert EMF rekordok parametereinek osszhangja. visszaad: hibauzenet vagy None """
    if typ in (2, 3, 4, 5, 6, 85, 86, 87, 88, 89):     # POLY*: bounds, pontszam, pontok (32 ill. 16 bites)
        if size < 28: return "record too short"
        n, = unpack_from('<L', d, p + 24)
        ps = 4 if typ >= 85 else 8
        if size != 28 + n * ps: return "%d points in %d bytes" % (n, size)
    elif typ in (7, 8, 90, 91):                         # POLYPOLYLINE/POLYPOLYGON: bounds, poligonok, pontok, pontszamok, pontok
        if size < 32: return "record too short"
        npoly, cpts = unpack_from('<LL', d, p + 24)
        ps = 4 if typ >= 90 else 8
        if size != 32 + npoly * 4 + cpts * ps: return "%d polygons / %d points in %d bytes" % (npoly, cpts, size)
        if sum(unpack_from('<%dL' % npoly, d, p + 32)) != cpts: return "polygon point counts do not add up to %d" % cpts
    elif typ == 84:                                     # EXTTEXTOUTW: a szoveg es a dx tomb a rekordon belul
        if size < 76: return "record too short"
        nchars, offstr = unpack_from('<LL', d, p + 44)
        offdx, = unpack_from('<L', d, p + 72)
        if nchars and offstr + nchars * 2 > size: return "string (%d chars at %d) outside of record" % (nchars, offstr)
        if nchars and offdx and offdx + nchars * 4 > size: return "dx array outside of record"
    elif typ in (76, 77, 81):                           # BITBLT, STRETCHBLT, STRETCHDIBITS: a bitkep a rekordon belul
        o = {76: 84, 77: 92, 81: 48}[typ]
        if size < o + 16: return "record too short"
        offbmi, cbbmi, offbits, cbbits = unpack_from('<4L', d, p + o)
        if cbbmi and (offbmi + cbbmi > size or offbits + cbbits > size): return "bitmap outside of record"
    elif typ == 70:                                     # COMMENT
        n, = unpack_from('<L', d, p + 8)
        if 12 + n > size: return "comment data (%d bytes) outside of record" % n
    return None


def testemf(data, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_emf(data, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_emf(d, debug):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    if n < 88 or unpack_from('<L', d, 0)[0] != EMR_HEADER or d[40:44] != b' EMF':
        print("ERROR! EMF: bad header")
        return 10
    hsize, = unpack_from('<L', d, 4)
    version, nbytes, nrec, nhandles, reserved, ndesc, offdesc = unpack_from('<LLLHHLL', d, 44)
    log("EMF: version 0x%X, %d bytes, %d records, %d handles" % (version, nbytes, nrec, nhandles))
    if hsize < 88 or hsize % 4 or reserved != 0 or (ndesc and offdesc + ndesc * 2 > hsize):
        print("ERROR! EMF: bad header (size %d, description %d chars at %d)" % (hsize, ndesc, offdesc))
        return 10
    if nbytes > n:
        print("ERROR! EMF: file is %d bytes, header says %d (truncated?)" % (n, nbytes))
        return 10
    p = 0
    cnt = 0
    while p + 8 <= nbytes:
        typ, size = unpack_from('<LL', d, p)
        if size < 8 or size % 4 or p + size > nbytes:
            print("ERROR! EMF: record #%d at %d: bad size %d" % (cnt, p, size))
            return 10
        if not 1 <= typ <= EMR_MAX or (typ == EMR_HEADER and p):
            print("ERROR! EMF: record #%d at %d: bad record type %d" % (cnt, p, typ))
            return 10
        err = check_emf_record(d, p, size, typ)
        if err:
            print("ERROR! EMF: record #%d at %d (type %d): %s" % (cnt, p, typ, err))
            return 10
        cnt += 1
        p += size
        if typ == EMR_EOF: break
    if typ != EMR_EOF:
        print("ERROR! EMF: missing EOF record")
        return 10
    if cnt != nrec or p != nbytes:
        print("ERROR! EMF: %d records / %d bytes, header says %d / %d" % (cnt, p, nrec, nbytes))
        return 10
    if nbytes < n:
        if d[nbytes:].strip(b'\x00'): log("WARNING: %d bytes of garbage after EOF record" % (n - nbytes))
        else: log("WARNING: %d zero bytes after EOF record" % (n - nbytes))
    log("EMF: %d records" % cnt)
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "wmf/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: d = f.read()
    res = testemf(d, debug=True) if d[40:44] == b' EMF' else testwmf(d, debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
