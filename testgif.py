#!/usr/bin/python3

# based on:  https://github.com/deshipu/circuitpython-gif/blob/master/code.py

import os
import struct
import sys


def lzw_count(data, code_size):
    """
    GIF LZW stream vegigdekodolasa. A pixelek erteke nem kell, csak a darabszamuk, ezert a szotarban
    kodonkent csak a string hosszat taroljuk (a string maga nem kell).
    visszaad: (pixelszam, hibauzenet vagy None, end code megvolt-e, felhasznalt byte-ok)
    """
    clear = 1 << code_size
    end = clear + 1
    lens = [1] * clear + [0, 0]      # kod -> string hossz
    nextc = end + 1
    clen = code_size + 1
    prevlen = 0                      # 0: nincs elozo kod (clear utan)
    acc = 0
    nb = 0
    p = 0
    n = len(data)
    pixels = 0
    while True:
        while nb < clen:
            if p >= n: return pixels, None, False, p
            acc |= data[p] << nb
            p += 1
            nb += 8
        code = acc & ((1 << clen) - 1)
        acc >>= clen
        nb -= clen
        if code == clear:
            del lens[end + 1:]
            nextc = end + 1
            clen = code_size + 1
            prevlen = 0
            continue
        if code == end: return pixels, None, True, p
        if code < nextc: L = lens[code]
        elif code == nextc and prevlen: L = prevlen + 1   # KwKwK eset
        else: return pixels, "invalid LZW code %d (next free code %d)" % (code, nextc), False, p
        pixels += L
        if prevlen and nextc < 4096:
            lens.append(prevlen + 1)
            nextc += 1
            if nextc == (1 << clen) and clen < 12: clen += 1
        prevlen = L


def testgif(f, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_gif(f, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_gif(f, debug):

    def log(*args):
        if debug: print(*args)

    d = f.read()
    p = 0

    def read_blockstream():
        """ sub-block lanc osszefuzese, visszaad: (adat, hibauzenet vagy None) """
        nonlocal p
        parts = []
        while True:
            if p >= len(d): return b''.join(parts), "unexpected EOF in data sub-blocks"
            size = d[p]
            p += 1
            if size == 0: break
            if p + size > len(d):
                parts.append(d[p:])
                p = len(d)
                return b''.join(parts), "unexpected EOF in data sub-blocks"
            parts.append(d[p:p + size])
            p += size
        data = b''.join(parts)
        log("GIF blockstream len:", len(data))
        return data, None

    # header
    if d[0:6] not in [b'GIF87a', b'GIF89a']:
        print("ERROR! not a GIF file")
        return 100
    if len(d) < 13:
        print("ERROR! truncated GIF header")
        return 100
    w, h, flags, background, aspect = struct.unpack('<HHBBB', d[6:13])
    p = 13
    palette_flag = (flags & 0x80) != 0
    palette_size = 1 << ((flags & 0x07) + 1)
    log("GIF:", w, h, palette_size if palette_flag else -1, flags, background, aspect) # GIF: 721 721 64 213 0 0
    if w > 8192 or h > 4096:  # gif/Auflage_Gasfeder.GIF: GIF image data, version 87a, 4277 x 3024
        print("ERROR! bad size: %d x %d" % (w, h))
        return 10
    if palette_flag: p += 3 * palette_size

    errcnt = 0
    frames = 0
    trailer = False
    while p < len(d):
        block_type = d[p]
        p += 1
        log("GIF: block 0x%X at %d" % (block_type, p - 1))
        if block_type == 0x3b:
            trailer = True
            break
        elif block_type == 0x2c:
            frames += 1
            if p + 10 > len(d):
                print("ERROR! frame #%d: truncated image descriptor" % frames)
                errcnt += 10
                break
            x, y, fw, fh, fflags = struct.unpack('<HHHHB', d[p:p + 9])
            p += 9
            if fflags & 0x80: p += 3 * (1 << ((fflags & 0x07) + 1))  # local color table
            log("GIF-frame:", x, y, 1 << ((fflags & 0x07) + 1) if fflags & 0x80 else -1, fw, fh, fflags) # GIF-frame: 0 0 2 721 721 0
            if x + fw > w or y + fh > h: log("WARNING: frame #%d (%d,%d %dx%d) outside of logical screen %dx%d" % (frames, x, y, fw, fh, w, h))
            if p >= len(d):
                print("ERROR! frame #%d: unexpected EOF" % frames)
                errcnt += 10
                break
            min_code_sz = d[p]
            p += 1
            data, err = read_blockstream()
            if err:
                print("ERROR! frame #%d: %s" % (frames, err))
                errcnt += 10
            if min_code_sz < 2 or min_code_sz > 8:
                print("ERROR! frame #%d: bad LZW minimum code size %d" % (frames, min_code_sz))
                errcnt += 10
                continue
            pixels, err, endcode, used = lzw_count(data, min_code_sz)
            log("GIF frame pixels:", pixels, fw * fh, "end code" if endcode else "no end code", "%d/%d bytes" % (used, len(data)))
            if err:
                print("ERROR! frame #%d: %s after %d of %d pixels" % (frames, err, pixels, fw * fh))
                errcnt += 10
            elif pixels != fw * fh:
                print("ERROR! frame #%d: %d of %d pixels decoded" % (frames, pixels, fw * fh))
                errcnt += 10
            elif not endcode: log("WARNING: frame #%d: missing LZW end code" % frames)
            elif used < len(data) - 1: log("WARNING: frame #%d: %d extra bytes after LZW end code" % (frames, len(data) - used))
        elif block_type == 0x21:
            if p >= len(d):
                print("ERROR! unexpected EOF in extension block")
                errcnt += 10
                break
            extension_type = d[p]  # 0x01 = label, 0xf9 = graphic control, 0xfe = comment, 0xff = application
            p += 1
            ext_data, err = read_blockstream()
            if err:
                print("ERROR! extension 0x%02X: %s" % (extension_type, err))
                errcnt += 10
        else:
            print("ERROR! bad block type 0x%02X at %d" % (block_type, p - 1))
            return errcnt + 20

    if frames == 0:
        print("ERROR! no image frames")
        errcnt += 10
    if not trailer:
        print("ERROR! EOF reached before GIF trailer (0x3B)")
        errcnt += 10
    elif p < len(d): log("WARNING: %d bytes after GIF trailer" % (len(d) - p))
    log("GIF: %d frames" % frames)
    return errcnt


if __name__ == "__main__":
  path = sys.argv[1] if len(sys.argv) > 1 else "gif/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testgif(f, debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
