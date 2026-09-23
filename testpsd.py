#! /usr/bin/python3

from struct import unpack
import zlib

###############################################################################################################################
##############################################  PSD  ##########################################################################
###############################################################################################################################

def rle_rows_check(data, pos, counts, rowbytes):
    """
    PackBits (RLE) sorok ellenorzese: minden sornak pontosan rowbytes byte-ra kell kitomorulnie es pontosan
    a megadott hosszat kell elhasznalnia. Csak szamolunk, nem bontjuk ki.
    visszaad: (uj pozicio, hibas sorok szama, elso hiba leirasa)
    """
    bad = 0
    first = None
    for row, l in enumerate(counts):
        p = pos
        end = pos + l
        out = 0
        err = None
        if end > len(data): err = "row data outside of file"
        else:
            while p < end:
                c = data[p]
                p += 1
                if c < 128:          # literal run
                    p += c + 1
                    out += c + 1
                elif c > 128:        # ismetles
                    p += 1
                    out += 257 - c
            if p > end: err = "run past end of row data"
            elif out != rowbytes: err = "%d of %d bytes" % (out, rowbytes)
        if err:
            bad += 1
            if first is None: first = "row #%d at 0x%X: %s" % (row, pos, err)
        pos = end
    return pos, bad, first


def zip_check(data, pos, length, expected):
    """ ZIP (zlib) tomoritett csatorna adat. visszaad: hibauzenet vagy None """
    if pos + length > len(data): return "data outside of file"
    zo = zlib.decompressobj()
    try:
        out = len(zo.decompress(data[pos:pos + length]))
    except zlib.error as e:
        return "zlib: %s" % e
    if not zo.eof: return "zlib stream truncated"
    if out != expected: return "%d of %d bytes" % (out, expected)
    return None



def check_layers(data, p, end, psb, depth, log):
    """
    Layer info: a layer rekordok alapjan a csatornak adatmereteinek es (RLE/ZIP eseten) a tomoritett adatnak az ellenorzese.
    A maszk csatornak (-2, -3) meretet nem szamoljuk ki, azoknal csak a hosszakat nezzuk.
    visszaad: hibapont
    """
    LS = 8 if psb else 4
    cnt, = unpack(">h", data[p:p + 2])
    cnt = abs(cnt)   # negativ: az elso alfa csatorna a merged kep atlatszosaga
    p += 2
    log("Layers:", cnt)
    layers = []
    for i in range(cnt):
        if p + 18 > end:
            print("ERROR! layer #%d: layer records overflow layer info section" % i)
            return 10
        top, left, bottom, right, nch = unpack(">llllH", data[p:p + 18])
        p += 18
        if nch > 56 or p + nch * (2 + LS) + 16 > end:
            print("ERROR! layer #%d: bad layer record (%d channels)" % (i, nch))
            return 10
        chans = []
        for j in range(nch):
            cid, = unpack(">h", data[p:p + 2])
            clen, = unpack(">Q" if psb else ">L", data[p + 2:p + 2 + LS])
            chans.append((cid, clen))
            p += 2 + LS
        sig, blend, opacity, clipping, flags, filler, extra = unpack(">4s4sBBBBL", data[p:p + 16])
        if sig != b'8BIM':
            print("ERROR! layer #%d: bad blend mode signature %r" % (i, sig))
            return 10
        p += 16 + extra
        if bottom < top or right < left:
            print("ERROR! layer #%d: bad layer rectangle %d,%d,%d,%d" % (i, top, left, bottom, right))
            return 10
        layers.append((bottom - top, right - left, chans))
        log("  layer #%d: %dx%d  %d channels" % (i, right - left, bottom - top, nch))
    if p > end:
        print("ERROR! layer records overflow layer info section")
        return 10

    # channel image data
    bad = 0
    first = None
    for i, (h, w, chans) in enumerate(layers):
        rb = (w * depth + 7) // 8
        for cid, clen in chans:
            if clen < 2 or p + clen > end:
                print("ERROR! layer #%d channel %d: bad data length %d" % (i, cid, clen))
                return 10
            comp, = unpack(">H", data[p:p + 2])
            q = p + 2
            err = None
            if cid >= -1 and h > 0 and w > 0:   # a maszkok meretet nem ismerjuk
                if comp == 0:
                    if clen - 2 != rb * h: err = "%d of %d bytes" % (clen - 2, rb * h)
                elif comp == 1:
                    cs = 4 if psb else 2
                    counts = list(unpack(">%d%s" % (h, "L" if psb else "H"), data[q:q + h * cs]))
                    q, b, f = rle_rows_check(data, q + h * cs, counts, rb)
                    if b: err = "%d of %d RLE rows bad, first: %s" % (b, h, f)
                    elif q != p + clen: err = "RLE data length mismatch"
                elif comp in [2, 3]:
                    err = zip_check(data, q, clen - 2, rb * h)
                else:
                    err = "unknown compression %d" % comp
            elif comp > 3: err = "unknown compression %d" % comp
            if err:
                bad += 1
                if first is None: first = "layer #%d channel %d: %s" % (i, cid, err)
            p += clen
    if bad:
        print("ERROR! %d bad layer channels, first: %s" % (bad, first))
        return 10
    if end - p > 3 or p > end:
        print("ERROR! layer info: %d bytes left after channel data" % (end - p))
        return 1
    return 0


def parse_psd(data, debug):

    def log(*args):
        if debug: print(*args)

    errcnt = 0

    magic, version, resvd1, resvd2 = unpack(">4sHHL", data[0:12])
    channels, height, width, depth, color = unpack(">HLLHH", data[12:12 + 14])
    pos = 12 + 14
    psb = version == 2   # Large Document Format: nehany hossz 8 byte-os
    L = ">Q" if psb else ">L"
    LS = 8 if psb else 4

    log(magic, version, resvd1, resvd2)
    if magic != b'8BPS' or version not in [1, 2] or resvd1 != 0 or resvd2 != 0:
        print("ERROR! bad PSD header")
        return 100

    log("dimension: %d x %d x %d (%d bits)  colormode=%d%s" % (width, height, channels, depth, color, "  PSB" if psb else ""))
    maxdim = 300000 if psb else 30000
    if not (1 <= channels <= 56) or not (1 <= width <= maxdim) or not (1 <= height <= maxdim) or depth not in [1, 8, 16, 32] or color not in [0, 1, 2, 3, 4, 7, 8, 9]:
        print("ERROR! bad PSD header: %d x %d x %d (%d bits) colormode=%d" % (width, height, channels, depth, color))
        return 100

    def rowbytes(w): return (w * depth + 7) // 8

    # Color Mode Data Section
    l, = unpack(">L", data[pos:pos + 4])
    log("Color Mode Data Section", l)
    pos += 4 + l

    # Image Resources Section
    l, = unpack(">L", data[pos:pos + 4])
    log("Image Resources Section", l)
    pos += 4
    p = pos
    pos += l
    while p + 12 <= pos:
        # b'8BIM  \x03\xed  \x00\x00  \x00\x00\x00\x10  \x01,\x00\x00'
        sig, ui, nl = unpack(">4sHB", data[p:p + 7])
        if sig not in [b'8BIM', b'MeSa', b'AgHg', b'PHUT', b'DCSR']: break
        nev = data[p + 7:p + 7 + nl]
        nl += 7
        if nl & 1: nl += 1
        p += nl
        rl, = unpack(">L", data[p:p + 4])
        p += 4
        log("\t", sig, ui, nev, rl)
        if rl & 1: rl += 1
        p += rl
    if pos != p:
        print("ERROR! image resources: %d bytes left" % (pos - p))
        errcnt += 1

    # Layer and Mask Information
    l, = unpack(L, data[pos:pos + LS])
    log("Layer and Mask Information", l)
    p = pos + LS
    pos += LS + l
    if pos > len(data):
        print("ERROR! layer and mask section outside of file: %d > %d" % (pos, len(data)))
        return errcnt + 10
    if l > 0:
        l2, = unpack(L, data[p:p + LS])
        p += LS
        layerend = p + l2
        if l2 > 0: errcnt += check_layers(data, p, layerend, psb, depth, log)
        p = layerend
        # Global layer mask info:
        if p + 4 <= pos:
            l3, = unpack(">L", data[p:p + 4])
            log("Global layer mask info", l3)
            p += 4 + l3
        # Additional Layer Information:
        while p + 12 <= pos:
            sig, key = data[p:p + 4], data[p + 4:p + 8]
            if sig not in [b'8BIM', b'8B64']: break
            if psb and key in [b'LMsk', b'Lr16', b'Lr32', b'Layr', b'Mt16', b'Mt32', b'Mtrn', b'Alph', b'FMsk', b'lnk2', b'FEid', b'FXid', b'PxSD']:
                l1, = unpack(">Q", data[p + 8:p + 16])
                p += 16
            else:
                l1, = unpack(">L", data[p + 8:p + 12])
                p += 12
            log("\t", sig, key, l1)
            p += (l1 + 3) & ~3
        if pos != p:
            print("ERROR! layer information: %d bytes left" % (pos - p))
            errcnt += 1

    # Image Data (merged/composite image)
    if pos + 2 > len(data):
        print("ERROR! EOF before image data")
        return errcnt + 10
    c, = unpack(">H", data[pos:pos + 2])
    pos += 2
    rb = rowbytes(width)
    if c == 0: # uncompressed
        pos += rb * height * channels
    elif c == 1: # RLE
        n = height * channels
        cs = 4 if psb else 2
        counts = list(unpack(">%d%s" % (n, "L" if psb else "H"), data[pos:pos + n * cs]))
        pos += n * cs
        log("%d bytes image data (%d rows) - checking RLE..." % (sum(counts), n))
        pos, bad, first = rle_rows_check(data, pos, counts, rb)
        if bad:
            print("ERROR! image data: %d of %d RLE rows bad, first: %s" % (bad, n, first))
            errcnt += 10
    elif c in [2, 3]: # ZIP / ZIP with prediction
        err = zip_check(data, pos, len(data) - pos, rb * height * channels)
        if err:
            print("ERROR! image data: %s" % err)
            errcnt += 10
        pos = len(data)
    else:
        print("ERROR! unsupported image data compression: %d" % c)
        return errcnt + 10

    log("%d of %d decoded     ===>  %d left" % (pos, len(data), len(data) - pos))
    if pos > len(data):
        print("ERROR! image data truncated: %d bytes missing" % (pos - len(data)))
        errcnt += 10
    elif pos < len(data):
        print("ERROR! %d extra bytes after image data" % (len(data) - pos))
        errcnt += 10
    return errcnt


def testpsd(data, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_psd(data, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


if __name__ == "__main__":
  import os,sys
  args=sys.argv[1:]
  path=args[0] if args else "psd/"
  if os.path.isdir(path):
    files=[os.path.join(path,n) for n in os.listdir(path)]
  else:
    files=args
  for n in files:
    print("\n\n==================== %s ======================\n"%(os.path.basename(n)))
    with open(n,"rb") as f: res=testpsd(f.read(),debug=True)
    if res>0: print("!!!HIBAS!!!",res)
