#! /usr/bin/python3

from struct import unpack
import zlib

# szintipus -> csatornak szama, megengedett bitmelysegek
colortypes = {0: (1, (1, 2, 4, 8, 16)), 2: (3, (8, 16)), 3: (1, (1, 2, 4, 8)), 4: (2, (8, 16)), 6: (4, (8, 16))}

# Adam7 passok: x0, y0, dx, dy  (https://www.w3.org/TR/png/#8Interlace)
adam7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


def scanlines(w, h, bits, interlace):
    """ a kitomoritett kepadat sorainak hossza (filter byte-tal egyutt), sorrendben """
    if not interlace: return [1 + (w * bits + 7) // 8] * h
    rows = []
    for x0, y0, dx, dy in adam7:
        pw = (w - x0 + dx - 1) // dx if w > x0 else 0
        ph = (h - y0 + dy - 1) // dy if h > y0 else 0
        if pw and ph: rows += [1 + (pw * bits + 7) // 8] * ph   # az ures passnak nincs filter byte-ja sem
    return rows


class ImageStream:
    """ az IDAT (APNG-nel fdAT) adatok kitomoritese darabonkent, kozben a sorok filter byte-jainak ellenorzese """
    def __init__(self, rows, raw_deflate=False):
        self.zo = zlib.decompressobj(-15 if raw_deflate else 15)
        self.rows = rows
        self.expected = sum(rows)
        self.ri = 0          # kovetkezo sor indexe
        self.rowrem = 0      # az aktualis sorbol hatralevo byte-ok (0: filter byte kovetkezik)
        self.size = 0
        self.extra = 0
        self.badfilter = 0
        self.firstbad = None
        self.error = None

    def feed(self, data):
        if self.error: return
        try:
            out = self.zo.decompress(data, 1 << 20)   # max. 1MB darabokban, hogy a memoria ne szalljon el
            while True:
                self.scan(out)
                if not self.zo.unconsumed_tail: break
                out = self.zo.decompress(self.zo.unconsumed_tail, 1 << 20)
        except zlib.error as e:
            self.error = "zlib: %s" % e

    def scan(self, out):
        n = len(out)
        self.size += n
        off = 0
        rows = self.rows
        while off < n:
            if self.rowrem == 0:
                if self.ri >= len(rows):
                    self.extra += n - off
                    return
                if out[off] > 4:
                    self.badfilter += 1
                    if self.firstbad is None: self.firstbad = self.ri
                self.rowrem = rows[self.ri]
                self.ri += 1
            take = min(self.rowrem, n - off)
            off += take
            self.rowrem -= take

    def finish(self):
        """ visszaad: hibauzenetek listaja """
        if not self.error:
            try: self.scan(self.zo.flush())
            except zlib.error as e: self.error = "zlib: %s" % e
        errs = []
        if self.error: errs.append(self.error)
        elif not self.zo.eof: errs.append("zlib stream truncated")
        if self.size < self.expected: errs.append("%d of %d bytes image data" % (self.size, self.expected))
        if self.extra: errs.append("%d extra bytes of image data" % self.extra)
        if self.badfilter: errs.append("%d scanlines with bad filter type, first: row #%d" % (self.badfilter, self.firstbad))
        return errs


def testpng(data, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_png(data, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_png(data, debug):

    def log(*args):
        if debug: print(*args)

    if data[0:8] != b'\x89PNG\r\n\x1a\n':   #    137 80 78 71 13 10 26 10
        print("ERROR! not a PNG file")
        return 100

    errcnt = 0
    crcerr = []
    chunks = []
    ihdr = None
    cgbi = False       # Apple "optimalizalt" PNG (iOS): nyers deflate zlib fejlec nelkul
    stream = None
    idat_done = False
    frames = 0         # APNG
    frame = None       # az aktualis APNG frame (fcTL) stream-je
    iend = False
    p = 8
    while p < len(data):
        if p + 12 > len(data):
            print("ERROR! truncated chunk header at %d" % p)
            errcnt += 10
            break
        l, = unpack(">L", data[p:p + 4])
        c = data[p + 4:p + 8] # chunk name
        log(p, c, l)
        if not c.isalpha() or l > 0x7FFFFFFF:
            print("ERROR! bad chunk %r (length %d) at %d" % (c, l, p))
            errcnt += 10
            break
        if p + 12 + l > len(data):
            print("ERROR! chunk %s truncated: %d of %d bytes" % (c.decode(), len(data) - p - 12, l))
            errcnt += 10
            break
        cd = data[p + 8:p + 8 + l]
        ocrc, = unpack(">L", data[p + 8 + l:p + 12 + l])
        if zlib.crc32(data[p + 4:p + 8 + l]) != ocrc: crcerr.append(c.decode())
        if not chunks and c not in [b'IHDR', b'CgBI']:
            print("ERROR! first chunk is %s instead of IHDR" % c.decode())
            errcnt += 10
        chunks.append(c)
        p += 12 + l

        if c == b'CgBI': cgbi = True
        elif c == b'IHDR':
            if ihdr or l != 13:
                print("ERROR! bad/duplicate IHDR")
                errcnt += 10
                continue
            w, h, depth, color, compr, filt, ilace = unpack(">LLBBBBB", cd)
            log("IHDR: %d x %d  depth=%d color=%d compr=%d filter=%d interlace=%d%s" % (w, h, depth, color, compr, filt, ilace, "  CgBI" if cgbi else ""))
            if color not in colortypes or depth not in colortypes[color][1] or compr != 0 or filt != 0 or ilace > 1 or w == 0 or h == 0 or w > 0x7FFFFFFF or h > 0x7FFFFFFF:
                print("ERROR! bad IHDR: %d x %d depth=%d color=%d compr=%d filter=%d interlace=%d" % (w, h, depth, color, compr, filt, ilace))
                return errcnt + 10
            bits = depth * colortypes[color][0] # bits/pixel
            ihdr = (w, h, bits, ilace)
        elif c == b'PLTE':
            if stream or l % 3 or l == 0 or l > 768:
                print("ERROR! bad PLTE chunk (length %d)" % l)
                errcnt += 10
        elif c == b'IDAT':
            if not ihdr:
                print("ERROR! IDAT before IHDR")
                return errcnt + 10
            if idat_done:
                print("ERROR! IDAT chunks are not consecutive")
                errcnt += 10
                idat_done = False
            if stream is None:
                if ihdr and color == 3 and b'PLTE' not in chunks:
                    print("ERROR! missing PLTE for indexed color image")
                    errcnt += 10
                stream = ImageStream(scanlines(*ihdr), cgbi)
                if frame is not None: frame = stream   # APNG: az elso frame az IDAT
            stream.feed(cd)
        elif c == b'fcTL' and l == 26:   # APNG frame control
            seq, fw, fh, fx, fy = unpack(">LLLLL", cd[0:20])
            frames += 1
            if frame is not None and frame is not stream: errcnt += check_frame(frame, frames - 1)
            if ihdr and (fx + fw > ihdr[0] or fy + fh > ihdr[1] or fw == 0 or fh == 0):
                print("ERROR! APNG frame #%d: bad frame region %dx%d+%d+%d" % (frames, fw, fh, fx, fy))
                errcnt += 10
                frame = None
            elif ihdr:
                frame = ImageStream(scanlines(fw, fh, ihdr[2], ihdr[3])) if stream else True   # True: az IDAT lesz ez a frame
        elif c == b'fdAT':               # APNG frame data: sorszam + zlib adat
            if isinstance(frame, ImageStream) and frame is not stream: frame.feed(cd[4:])
        elif c == b'IEND':
            iend = True
            break
        if stream and c != b'IDAT': idat_done = True

    if isinstance(frame, ImageStream) and frame is not stream: errcnt += check_frame(frame, frames)
    if crcerr:
        print("ERROR! chunk CRC failed: %s" % ",".join(crcerr))
        errcnt += 10
    if not ihdr:
        print("ERROR! missing IHDR")
        return errcnt + 10
    if stream is None:
        print("ERROR! missing IDAT")
        return errcnt + 10
    errs = stream.finish()
    log("image data: %d bytes (%d expected)  %d x %d  %d bits/pixel  interlace=%d  %d scanlines" % (stream.size, stream.expected, ihdr[0], ihdr[1], ihdr[2], ihdr[3], len(stream.rows)))
    if errs:
        print("ERROR! image data: %s" % "; ".join(errs))
        errcnt += 10
    if frames: log("APNG: %d frames" % frames)
    if not iend:
        print("ERROR! missing IEND")
        errcnt += 10
    elif p != len(data):
        log("WARNING: %d bytes after IEND" % (len(data) - p))
    return errcnt


def check_frame(frame, n):
    errs = frame.finish()
    if errs:
        print("ERROR! APNG frame #%d: %s" % (n, "; ".join(errs)))
        return 10
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "png/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testpng(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
