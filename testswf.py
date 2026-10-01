#! /usr/bin/python3

# SWF (Flash) ellenorzes: FWS (tomoritetlen), CWS (zlib: teljes kitomorites, Adler-32), ZWS (LZMA). A fejlecben levo
# (kitomoritett) meret, a tagek lancolata pontosan az End taggel zarul, a beagyazott JPEG/PNG/GIF kepek, a zlib-es
# (lossless) kepek kitomorithetok. Metaadat: Metadata tag (XMP), ProductInfo (a Flex fordito forditasi ideje).

import datetime
import lzma
import zlib
from struct import unpack_from

from fileinfo import print_info, result, xmp_meta, plausible, utc_to_local, date_source


def swf_kind(d):
    """ felismeres: 'FWS'/'CWS'/'ZWS' es ertelmes fejlec (a visszaallitok sok veletlen 'ZWS' kezdetu adatot talalnak) """
    if len(d) < 21 or d[:3] not in (b'FWS', b'CWS', b'ZWS') or not 1 <= d[3] <= 50: return None
    flen, = unpack_from('<L', d, 4)
    if flen < 21: return None
    if d[:3] == b'CWS' and (d[8] & 0x0F != 8 or (d[8] << 8 | d[9]) % 31): return None   # zlib fejlec
    if d[:3] == b'ZWS':
        # LZMA props < 225, a szotar meret 2^n vagy 3*2^(n-1) (az LZMA kodolo igy kerekit): veletlen adat ezen nem megy at
        dsz, = unpack_from('<L', d, 13)
        if d[12] >= 225 or dsz < 4096 or not any(dsz == m << k for m in (2, 3) for k in range(11, 31)): return None
    if d[:3] == b'FWS' and d[8] >> 3 > 31: return None
    return d[:3].decode()


def testswf(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py):
      SWF_INFO;filenev;SWF verzio (tomorites);swf;letrehozas;modositas;forras (xmp|productinfo);;szerzo;cim;program;;OK|BAD
    """
    meta = {}
    try:
        res = parse_swf(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        x = xmp_meta(meta['xmp']) if 'xmp' in meta else {}
        created, src_c = x.get('created'), "xmp"
        if not created and meta.get('compiled'): created, src_c = meta['compiled'], "productinfo"
        modified = x.get('modified')
        print_info("SWF", (fname, meta.get('ver', ""), "swf", created, modified, date_source(created, modified, src_c, "xmp"), "",
                           x.get('artist', ""), x.get('title', ""), x.get('software', "") or meta.get('product', ""), "", result(res)))
    return res


def parse_swf(d, debug, meta):

    def log(*args):
        if debug: print(*args)

    sig, ver = d[:3], d[3]
    flen, = unpack_from('<L', d, 4)
    meta['ver'] = "SWF %d%s" % (ver, {b'CWS': " zlib", b'ZWS': " lzma"}.get(sig, ""))
    log("SWF: %s, version %d, uncompressed length %d, file %d bytes" % (sig.decode(), ver, flen, len(d)))
    errcnt = 0
    if sig == b'FWS':
        body = d[8:]
        if len(d) < flen:
            print("ERROR! SWF: file is %d bytes, header says %d (truncated)" % (len(d), flen))
            return 10
        if len(d) > flen: log("WARNING: %d bytes after the end of SWF" % (len(d) - flen))
        body = d[8:flen]
    elif sig == b'CWS':
        z = zlib.decompressobj()
        try:
            body = z.decompress(d[8:], flen)
        except zlib.error as e:
            print("ERROR! SWF: zlib: %s" % e)
            return 10
        if not z.eof:
            if len(body) >= flen - 8: print("ERROR! SWF: zlib stream longer than the header says (corrupt)")
            else: print("ERROR! SWF: zlib stream truncated (%d of %d bytes)" % (len(body) + 8, flen))
            return 10
        if len(body) != flen - 8:
            print("ERROR! SWF: %d bytes uncompressed, header says %d" % (len(body) + 8, flen))
            errcnt = 10
        if z.unused_data: log("WARNING: %d bytes after the zlib stream" % len(z.unused_data))
    else:                                                    # ZWS: 4 byte tomoritett meret, 5 byte LZMA props, nyers LZMA
        clen, = unpack_from('<L', d, 8)
        if 17 + clen > len(d):
            print("ERROR! SWF: LZMA data %d bytes, only %d in file (truncated)" % (clen, len(d) - 17))
            return 10
        try:
            dec = lzma.LZMADecompressor(lzma.FORMAT_ALONE)
            body = dec.decompress(d[12:17] + (flen - 8).to_bytes(8, 'little') + d[17:17 + clen])
        except lzma.LZMAError as e:
            print("ERROR! SWF: LZMA: %s" % e)
            return 10
        if len(body) != flen - 8:
            print("ERROR! SWF: %d bytes uncompressed, header says %d" % (len(body) + 8, flen))
            return 10
        if len(d) > 17 + clen: log("WARNING: %d bytes after the LZMA data" % (len(d) - 17 - clen))

    # fejlec maradek: RECT (5 bit nbits + 4 * nbits bit), frame rate, frame count
    nbits = body[0] >> 3
    p = (5 + 4 * nbits + 7) // 8 + 4
    rate, frames = unpack_from('<HH', body, p - 4)
    log("SWF: frame rate %.2f, %d frames" % (rate / 256.0, frames))

    tags = badimg = shown = 0
    firstbad = None
    end = False
    from testjpeg import testjpeg
    from testpng import testpng
    from testgif import testgif
    import io
    while p + 2 <= len(body):
        code_len, = unpack_from('<H', body, p)
        code, tl = code_len >> 6, code_len & 0x3F
        p += 2
        if tl == 0x3F:
            if p + 4 > len(body): break
            tl, = unpack_from('<L', body, p)
            p += 4
        if p + tl > len(body):
            print("ERROR! SWF: tag %d at %d: length %d, only %d bytes left (truncated?)" % (code, p, tl, len(body) - p))
            return 10
        t = body[p:p + tl]
        tags += 1
        err = None
        if code == 1: shown += 1                   # ShowFrame
        if code == 0:
            end = True
            p += tl
            break
        elif code in (21, 35, 90):                           # DefineBitsJPEG2/3/4: JPEG (vagy Flash 8+: PNG/GIF)
            img = t[2:] if code == 21 else t[6:6 + unpack_from('<L', t, 2)[0]] if code == 35 else t[8:8 + unpack_from('<L', t, 2)[0]]
            if img[:4] == b'\xff\xd9\xff\xd8': img = img[4:]   # regi Flash iro: hibas EOI+SOI az elejen
            if img[:2] == b'\xff\xd8':
                # a regi iroknal a tablakat es a kepet kulon EOI/SOI valaszthatja el: a kozbulso EOI+SOI-t kivesszuk
                img = img[:2] + img[2:].replace(b'\xff\xd9\xff\xd8', b'', 1) if img.count(b'\xff\xd8') > 1 else img
                if testjpeg(img, embedded=True): err = "JPEG"
            elif img[:8] == b'\x89PNG\r\n\x1a\n':
                if testpng(img): err = "PNG"
            elif img[:3] == b'GIF':
                if testgif(io.BytesIO(img)): err = "GIF"
        elif code in (20, 36):                               # DefineBitsLossless(2): zlib tomoritett kep
            try:
                z = zlib.decompressobj()
                z.decompress(t[7 + (1 if t[2] == 3 else 0):] if code == 20 else t[7 + (1 if t[2] == 3 else 0):])
                if not z.eof: err = "lossless (zlib truncated)"
            except zlib.error as e:
                err = "lossless (zlib: %s)" % e
        elif code == 77:                                     # Metadata: XMP
            meta['xmp'] = t
        elif code == 41 and tl >= 26:                        # ProductInfo: termek, verzio, build, forditasi ido (ms, UTC)
            pid, ed, maj, mnr = unpack_from('<LLBB', t, 0)
            ms, = unpack_from('<Q', t, 18)
            meta['product'] = "%s %d.%d" % ({1: "Macromedia Flex for J2EE", 2: "Macromedia Flex for .NET", 3: "Adobe Flex"}.get(pid, "product %d" % pid), maj, mnr)
            try: meta['compiled'] = plausible(utc_to_local(datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=ms)))
            except (OverflowError, ValueError): pass
        if err:
            badimg += 1
            if firstbad is None: firstbad = "tag %d at %d: %s image bad" % (code, p + 8, err)
        p += tl
    log("SWF: %d tags, %d frames (header: %d)" % (tags, shown, frames))
    if not end:
        print("ERROR! SWF: no End tag (truncated?)")
        return 10
    # az End tag az utolso: utana csak nagyon kevés kitoltes lehet. Kinullazott / hianyzo adat eseten a nulla byte maga is
    # End tag, ezert a lanc "szabalyosan" veget er - a fejlecben levo hossz es kepkockaszam alapjan derul ki
    if len(body) - p > 512:
        print("ERROR! SWF: %d %s bytes after the End tag at %d (zeroed or missing data?)" % (len(body) - p, "zero" if not body[p:].strip(b'\x00') else "garbage", p + 8))
        return 10
    if len(body) > p and body[p:].strip(b'\x00'): log("WARNING: %d bytes after the End tag" % (len(body) - p))
    if shown < frames:
        print("ERROR! SWF: only %d of %d frames (truncated?)" % (shown, frames))
        return 10
    if badimg:
        print("ERROR! SWF: %d bad embedded images, first: %s" % (badimg, firstbad))
        errcnt = 10
    return errcnt


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "_SWF/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: d = f.read()
    if not swf_kind(d):
        print("not an SWF file (bad header)")
        continue
    res = testswf(d, debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res)
