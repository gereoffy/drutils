#!/usr/bin/python3

import os
import struct
import sys
import zlib

tagnames={}
try:
    for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"tiff.csv"),"rt"):
        td,th,tn=line.strip().split("\t",2)
        tagnames[int(td)]=tn
except: pass

tiffcompress={
   1:"UNCOMPRESSED",
   2:"CCITTRLE",
   3:"CCITTFAX3",
   4:"CCITTFAX4",
   5:"LZW",
   6:"OJPEG",
   7:"JPEG",
   8:"ADOBE_DEFLATE",
   32766:"NEXT",
   32771:"CCITTRLEW",
   32773:"PACKBITS",
   32809:"THUNDERSCAN",
   32895:"IT8CTPAD",
   32896:"IT8LW",
   32897:"IT8MP",
   32898:"IT8BL",
   32908:"PIXARFILM",
   32909:"PIXARLOG",
   32946:"DEFLATE",
   32947:"DCS",
   34661:"JBIG",
   34676:"SGILOG",
   34677:"SGILOG24",
   34712:"JP2000"}

typmap={1:"BYTE",2:"ASCII",3:"SHORT",4:"LONG",5:"RATIONAL",6:"SBYTE",7:"UNDEFINED",8:"SSHORT",9:"SLONG",10:"SRATIONAL",11:"FLOAT",12:"DOUBLE",13:"IFD"}
typlen={1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8,13:4}
typfmt={1:"B",3:"H",4:"I",6:"b",8:"h",9:"i",13:"I"}


###############################################################################################################################
# strip/tile dekodolok: csak a kimeneti byte-okat szamoljuk. Mint a libtiff, az elvart meretnel tobb kimenetet elfogadjuk,
# de a vart meret utan legfeljebb az EOI kod / par byte maradhat (kulonben a stream serult).
# visszaad: hibauzenet vagy None
###############################################################################################################################

def lzw_check(d, o, l, expected):
    """ TIFF LZW (MSB-first, early change), ill. a regi (TIFF 5 elotti) LSB-first valtozat """
    p = o
    end = o + l
    old = l >= 2 and d[o] == 0 and (d[o + 1] & 1)   # libtiff: regi stilusu LZW felismerese
    early = 0 if old else 1
    lens = [1] * 256 + [0, 0]     # kod -> string hossz (a string maga nem kell)
    nextc = 258
    clen = 9
    prevlen = 0
    acc = 0
    nb = 0
    out = 0
    while True:
        while nb < clen:
            if p >= end:
                if out < expected: return "%d of %d bytes decoded: LZW data ended without EOI" % (out, expected)
                return None
            if old: acc |= d[p] << nb
            else: acc = ((acc & ((1 << nb) - 1)) << 8) | d[p]
            p += 1
            nb += 8
        if old:
            code = acc & ((1 << clen) - 1)
            acc >>= clen
            nb -= clen
        else:
            nb -= clen
            code = (acc >> nb) & ((1 << clen) - 1)
        if out >= expected:
            # a kep megvan: jo, ha itt EOI jon, vagy mar csak 1-2 byte van hatra (egyes irok rossz bitszelesseggel irjak az EOI-t)
            if code == 257 or end - p <= 2: return None
            return "%d extra bytes of LZW data after %d decoded bytes" % (end - p, expected)
        if code == 256:
            del lens[258:]
            nextc = 258
            clen = 9
            prevlen = 0
            continue
        if code == 257: return "%d of %d bytes decoded: early LZW EOI code" % (out, expected)
        if code < nextc: L = lens[code]
        elif code == nextc and prevlen: L = prevlen + 1   # KwKwK eset
        else: return "%d of %d bytes decoded: invalid LZW code %d (next free code %d)" % (out, expected, code, nextc)
        out += L
        if prevlen and nextc < 4096:
            lens.append(prevlen + 1)
            nextc += 1
            if nextc >= (1 << clen) - early and clen < 12: clen += 1
        prevlen = L


def packbits_check(d, o, l, expected):
    p = o
    end = o + l
    out = 0
    while out < expected:
        if p >= end: return "%d of %d bytes decoded: PackBits data ended" % (out, expected)
        c = d[p]
        p += 1
        if c < 128:        # literal run
            if p + c + 1 > end: return "%d of %d bytes decoded: PackBits literal run past end of data" % (out, expected)
            p += c + 1
            out += c + 1
        elif c > 128:      # ismetles
            if p >= end: return "%d of %d bytes decoded: PackBits data ended" % (out, expected)
            p += 1
            out += 257 - c
    if end - p > 1: return "%d extra bytes of PackBits data after %d decoded bytes" % (end - p, out)
    return None


def deflate_check(d, o, l, expected):
    """ vegig kitomoritjuk, hogy az adler32 ellenorzes is lefusson """
    zo = zlib.decompressobj()
    try:
        out = len(zo.decompress(d[o:o + l]))
    except zlib.error as e:
        return "zlib: %s" % e
    if out < expected: return "%d of %d bytes decoded: zlib stream %s" % (out, expected, "ended" if zo.eof else "truncated")
    return None


def uncompressed_check(d, o, l, expected):
    if l < expected: return "%d of %d bytes" % (l, expected)
    return None


def jpeg_checker(tables):
    """ JPEG (compression=7): a strip/tile rovidített JPEG stream, a DQT/DHT tablak a JPEGTables tagben lehetnek """
    from testjpeg import testjpeg
    head = tables[:-2] if isinstance(tables, bytes) and tables[:2] == b'\xff\xd8' and tables[-2:] == b'\xff\xd9' else None
    def jpeg_check(d, o, l, expected):
        s = d[o:o + l]
        if s[:2] != b'\xff\xd8': return "no JPEG SOI marker"
        if head: s = head + s[2:]
        e = testjpeg(s, embedded=True)
        return "JPEG errors (%d)" % e if e else None
    return jpeg_check


checkers = {1: uncompressed_check, 5: lzw_check, 8: deflate_check, 32946: deflate_check, 32773: packbits_check}


###############################################################################################################################


def testtif(data, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_tif(data, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_tif(data, debug):

    def log(*args):
        if debug: print(*args)

    magic = data[0:2]
    if magic not in [b'II', b'MM']:
        print("ERROR! not a TIFF file")
        return 100
    E = "<" if magic == b'II' else ">"
    def getint(i, l, s=False): return int.from_bytes(data[i:i + l], byteorder=("little" if magic == b'II' else "big"), signed=s)
    version = getint(2, 2)
    ifd = getint(4, 4)
    log(magic, version, ifd)
    if version != 42:
        print("ERROR! bad TIFF version %d%s" % (version, " (BigTIFF not supported)" if version == 43 else ""))
        return 100

    errcnt = 0
    ifdno = 0
    visited = set()
    while ifd != 0:
      ifdno += 1
      if ifd in visited:
          print("ERROR! IFD #%d: loop in IFD chain (offset %d)" % (ifdno, ifd))
          return errcnt + 10
      visited.add(ifd)
      if ifd < 8 or ifd + 2 > len(data):
          print("ERROR! IFD #%d: bad IFD pointer %d (file size %d)" % (ifdno, ifd, len(data)))
          return errcnt + 10
      num = getint(ifd, 2)
      if num < 4 or ifd + 2 + 12 * num + 4 > len(data):  # typical range: 12..19
          print("ERROR! IFD #%d: bad number of tags: %d" % (ifdno, num))
          return errcnt + 10
      log("---- IFD #%d at %d: %d tags" % (ifdno, ifd, num))

      tagvalues = {}
      for i in range(num):
        p = ifd + 2 + 12 * i
        tag = getint(p, 2)   # The tag identifier
        typ = getint(p + 2, 2) # The scalar type of the data items
        cnt = getint(p + 4, 4) # The number of items in the tag data
        ofs = getint(p + 8, 4) # The byte offset to the data items
        if typ not in typmap:
            log("WARNING: tag %d: unknown type %d, skipped" % (tag, typ))
            continue
        size = typlen[typ] * cnt
        if size <= 4: ofs = p + 8 # az ertek maga a tag-ben van
        elif ofs + size > len(data):
            print("ERROR! IFD #%d: tag %d (%s) data outside of file: %d+%d > %d" % (ifdno, tag, tagnames.get(tag, "?"), ofs, size, len(data)))
            errcnt += 10
            continue
        value = "#%d" % ofs
        if typ == 2: value = data[ofs:ofs + cnt - 1] # ascii
        elif typ == 7: value = data[ofs:ofs + cnt]    # undefined (pl. JPEGTables)
        elif typ in typfmt: value = list(struct.unpack_from("%s%d%s" % (E, cnt, typfmt[typ]), data, ofs))
        elif typ == 5: value = "%d/%d" % (getint(ofs, 4), getint(ofs + 4, 4))
        elif typ == 10: value = "%d/%d" % (getint(ofs, 4, True), getint(ofs + 4, 4, True))
        tagvalues[tag] = value
        if debug:
            v = tiffcompress.get(value[0], value) if tag == 259 else value
            print("ifd#%d: " % i, tag, tagnames.get(tag, "%d" % tag), typmap[typ], "x", cnt, "=", str(v)[:100])
      # end of IFD
      errcnt += check_image_data(data, tagvalues, ifdno, log)
      ifd = getint(ifd + 2 + 12 * num, 4)
      log("Next IFD:", ifd)
    return errcnt


def check_image_data(data, t, ifdno, log):
    """ egy IFD kepadatainak (strip-ek/tile-ok) ellenorzese. visszaad: hibapont """
    def first(tag, default):
        v = t.get(tag)
        return v[0] if isinstance(v, list) and v else default

    W = first(256, 0)
    H = first(257, 0)
    spp = first(277, 1)
    comp = first(259, 1)
    planar = first(284, 1)
    photometric = first(262, -1)
    bits = t.get(258, [1])
    if not isinstance(bits, list) or not bits: bits = [1]
    if len(bits) < spp: bits = bits + [bits[-1]] * (spp - len(bits))  # nehany iro csak 1 erteket ad meg
    compname = tiffcompress.get(comp, str(comp))

    if 324 in t:   # tiled
        offsets, counts = t.get(324), t.get(325)
        tw, tl = first(322, 0), first(323, 0)
        if not tw or not tl:
            print("ERROR! IFD #%d: missing tile size" % ifdno)
            return 10
        across, down = (W + tw - 1) // tw, (H + tl - 1) // tl
        def expected(k, sbits): return tl * ((tw * sbits + 7) // 8)
        per_plane = across * down
        kind = "tile"
    elif 273 in t: # strips
        offsets, counts = t.get(273), t.get(279)
        rps = min(first(278, H) or H, H) or 1
        per_plane = (H + rps - 1) // rps
        ycbcr = photometric == 6 and comp not in (6, 7) and planar == 1
        sh, sv = (t.get(530) or [2, 2])[:2] if ycbcr else (1, 1)
        def expected(k, sbits):
            rows = min(rps, H - (k % per_plane) * rps)
            if ycbcr and (sh > 1 or sv > 1):  # subsampled YCbCr: h*v luma + 2 chroma blokkonkent
                return ((rows + sv - 1) // sv) * (((W + sh - 1) // sh) * (sh * sv + 2) * bits[0] + 7) // 8
            return rows * ((W * sbits + 7) // 8)
        kind = "strip"
    else:
        print("ERROR! IFD #%d: no image data (no StripOffsets/TileOffsets)" % ifdno)
        return 10

    if not isinstance(offsets, list) or not offsets:
        print("ERROR! IFD #%d: bad %s offsets" % (ifdno, kind))
        return 10
    if not isinstance(counts, list) or len(counts) < len(offsets):
        # hianyzo byte count: a kovetkezo offsetig / a file vegeig
        ends = sorted(offsets[1:]) + [len(data)]
        counts = [e - o for o, e in zip(offsets, ends)]
        log("WARNING: missing %s byte counts, estimated" % kind)

    planes = spp if planar == 2 else 1
    needed = per_plane * planes
    log("TIFF %s %dx%d spp=%d bits=%s planar=%d photometric=%d  %d %ss (%d needed)" % (compname, W, H, spp, bits, planar, photometric, len(offsets), kind, needed))
    if W == 0 or H == 0:
        print("ERROR! IFD #%d: bad image size %d x %d" % (ifdno, W, H))
        return 10
    if len(offsets) < needed:
        print("ERROR! IFD #%d: only %d of %d %ss" % (ifdno, len(offsets), needed, kind))
        return 10

    checker = jpeg_checker(t.get(347)) if comp == 7 else checkers.get(comp)
    if not checker: log("TIFF: %s compression is not decoded, only %s positions checked" % (compname, kind))
    bad = []
    rawsize = 0
    datasize = 0
    for k in range(needed):
        o, l = offsets[k], counts[k]
        sbits = bits[k // per_plane] if planar == 2 else sum(bits)
        exp = expected(k, sbits)
        rawsize += exp
        datasize += l
        if o + l > len(data):
            bad.append((k, "data outside of file: %d+%d > %d" % (o, l, len(data))))
            continue
        if l == 0 and exp > 0:
            bad.append((k, "zero length"))
            continue
        err = checker(data, o, l, exp) if checker else None
        if err: bad.append((k, err))
    log("TIFF %s datasize=%d rawsize=%d" % (compname, datasize, rawsize))
    if bad:
        k, msg = bad[0]
        print("ERROR! IFD #%d: %d of %d %ss bad, first: %s #%d: %s" % (ifdno, len(bad), needed, kind, kind, k, msg))
        return 10
    return 0


if __name__ == "__main__":
  path = sys.argv[1] if len(sys.argv) > 1 else "tif/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testtif(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
