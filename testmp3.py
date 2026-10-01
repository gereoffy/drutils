#! /usr/bin/python3

# MP3 (MPEG-1/2/2.5 Layer I/II/III audio) ellenorzes dekodolas nelkul: a keretek (frame) hezag nelkul kovetik egymast (a
# fejlecbol a keret hossza kiszamolhato), a CRC-vel vedett keretek CRC-16-ja, a Xing/Info/VBRI fejlec keretszama, a LAME
# fejlec hangadat CRC-je, az ID3v2 tag szerkezete es a beagyazott boritokep. Metaadat: ID3v2/ID3v1 (cim, eloado, album).

import datetime
import re
from struct import unpack_from

from fileinfo import print_info, result, iso_local, plausible

BITRATES = {   # (verzio csoport, layer) -> kbit/s, index 1..14
    (1, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (1, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (1, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
SAMPLERATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}   # verzio bitek: 3=MPEG1, 2=MPEG2, 0=MPEG2.5
VERNAME = {3: "MPEG1", 2: "MPEG2", 0: "MPEG2.5"}


def frame_header(d, p):
    """ az MPEG audio keret fejlece p-n: (verzio, layer, vedett, hossz, mintaveteli frekv., csatorna mod) vagy None """
    if d[p] != 0xFF or d[p + 1] & 0xE0 != 0xE0: return None
    b1, b2, b3 = d[p + 1], d[p + 2], d[p + 3]
    ver = (b1 >> 3) & 3
    layer = 4 - ((b1 >> 1) & 3)          # 1, 2, 3 (4: fenntartott)
    if ver == 1 or layer == 4: return None
    bri, sri = b2 >> 4, (b2 >> 2) & 3
    if bri == 0 or bri == 15 or sri == 3 or b3 & 3 == 2: return None   # free format / hibas bitrata / frekvencia / emphasis
    br = BITRATES[(1 if ver == 3 else 2, layer)][bri] * 1000
    sr = SAMPLERATES[ver][sri]
    pad = (b2 >> 1) & 1
    if layer == 1: n = (12 * br // sr + pad) * 4
    elif layer == 3 and ver != 3: n = 72 * br // sr + pad
    else: n = 144 * br // sr + pad
    return ver, layer, not (b1 & 1), n, sr, b3 >> 6


def _crc_table(poly, reflected):
    t = []
    for i in range(256):
        if reflected:
            c = i
            for _ in range(8): c = (c >> 1) ^ poly if c & 1 else c >> 1
        else:
            c = i << 8
            for _ in range(8): c = ((c << 1) ^ poly) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
        t.append(c)
    return t

_CRC_MPEG = _crc_table(0x8005, False)    # MPEG audio: CRC-16, init 0xFFFF
_CRC_ARC = _crc_table(0xA001, True)      # LAME: CRC-16/ARC (reflektalt), init 0

def crc_mpeg(b, crc=0xFFFF):
    t = _CRC_MPEG
    for x in b: crc = ((crc << 8) & 0xFFFF) ^ t[(crc >> 8) ^ x]
    return crc

def crc_arc(b, crc=0):
    t = _CRC_ARC
    for x in b: crc = (crc >> 8) ^ t[(crc ^ x) & 0xFF]
    return crc


def side_info_len(ver, mode):
    """ Layer III oldalinformacio hossza (byte) """
    mono = mode == 3
    return (17 if mono else 32) if ver == 3 else (9 if mono else 17)


###############################################################################################################################
# ID3v2 tag(ek) a file elejen

def _syncsafe(b):
    return (b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | (b[3] & 0x7F)

def _text(b):
    """ ID3v2 szoveg frame tartalma (kodolas byte + szoveg) """
    if not b: return ""
    enc, s = b[0], b[1:]
    try:
        if enc == 1: t = s.decode('utf-16')
        elif enc == 2: t = s.decode('utf-16-be')
        elif enc == 3: t = s.decode('utf-8')
        else: t = s.decode('latin1')
    except UnicodeDecodeError:
        t = s.decode('latin1')
    return t.replace('\x00', ' ').strip()

def parse_id3v2(d, p, meta, log):
    """ egy ID3v2 tag p-n. visszaad: (a tag vege, hibauzenet vagy None) """
    major, rev, flags = d[p + 3], d[p + 4], d[p + 5]
    if major not in (2, 3, 4) or any(x & 0x80 for x in d[p + 6:p + 10]): return p, "bad ID3v2 header at %d" % p
    size = _syncsafe(d[p + 6:p + 10])
    end = p + 10 + size + (10 if flags & 0x10 else 0)
    if end > len(d): return end, "ID3v2 tag at %d: size %d, only %d bytes in file (truncated)" % (p, size, len(d) - p - 10)
    body = d[p + 10:p + 10 + size]
    if flags & 0x80 and major < 4: body = body.replace(b'\xff\x00', b'\xff')   # unsynchronisation (v2.2/2.3: az egesz tagra)
    q = 0
    if flags & 0x40 and major >= 3:                        # extended header
        q = 4 + (unpack_from('>L', body, 0)[0] if major == 3 else _syncsafe(body[:4]) - 4)
    meta.setdefault('id3', "ID3v2.%d" % major)
    idlen, hlen = (3, 6) if major == 2 else (4, 10)
    while q + hlen <= len(body):
        fid = body[q:q + idlen]
        if not re.match(rb'[A-Z0-9]{%d}$' % idlen, fid):
            if body[q:].strip(b'\x00'): log("WARNING: ID3v2: garbage at %d in tag (frame id %r)" % (q, fid))
            break
        if major == 2: fsize = int.from_bytes(body[q + 3:q + 6], 'big')
        elif major == 3: fsize, = unpack_from('>L', body, q + 4)
        else:
            # v2.4: syncsafe meret; az iTunes es nehany iro sima (nem syncsafe) meretet ir: akkor azt hasznaljuk, ha a
            # syncsafe meret utan nem frame / kitoltes / a tag vege jon, a sima meret utan viszont igen
            def fits(sz):
                nxt = q + hlen + sz
                return nxt <= len(body) and (nxt + 4 > len(body) or re.match(rb'[A-Z0-9]{4}', body[nxt:nxt + 4]) or not body[nxt:nxt + 4].strip(b'\x00'))
            fsize = _syncsafe(body[q + 4:q + 8])
            raw, = unpack_from('>L', body, q + 4)
            if raw != fsize and not fits(fsize) and fits(raw): fsize = raw
        if q + hlen + fsize > len(body): return end, "ID3v2 frame %s at %d: size %d exceeds the tag" % (fid.decode(), p + 10 + q, fsize)
        fd = body[q + hlen:q + hlen + fsize]
        if major == 4 and len(body) > q + 9 and body[q + 9] & 0x02: fd = fd.replace(b'\xff\x00', b'\xff')   # frame unsynchronisation
        fid = fid.decode()
        key = {"TT2": "TIT2", "TP1": "TPE1", "TAL": "TALB", "TYE": "TYER", "TEN": "TENC", "TSS": "TSSE", "PIC": "APIC"}.get(fid, fid)
        if key in ("TIT2", "TPE1", "TALB", "TYER", "TDRC", "TENC", "TSSE", "TDEN", "TDTG") and key not in meta:
            meta[key] = _text(fd)
        elif key == "APIC":
            meta.setdefault('pics', []).append((fid, fd))
        q += hlen + fsize
    return end, None


def check_picture(fid, fd):
    """ APIC/PIC: a kep adata (JPEG/PNG) a testjpeg/testpng-vel. visszaad: hibauzenet vagy None """
    from testjpeg import testjpeg
    from testpng import testpng
    for sig, fmt in ((b'\xff\xd8\xff', "jpg"), (b'\x89PNG\r\n\x1a\n', "png")):
        i = fd.find(sig, 0, 300)
        if i >= 0:
            img = fd[i:]
            e = testjpeg(img, embedded=True) if fmt == "jpg" else testpng(img)
            return "embedded %s cover image (%d bytes) bad" % (fmt, len(img)) if e else None
    return None


###############################################################################################################################

def testmp3(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py):
      MP3_INFO;filenev;MPEG verzio es layer;mp3;kodolas ideje;tageles ideje;forras (id3);;eloado;cim;program;album (ev);OK|BAD
    A felvetel eve nem a file datuma, ezert nem a datum mezokbe kerul.
    """
    meta = {}
    try:
        res = parse_mp3(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        v1 = meta.get('v1', {})
        artist = meta.get('TPE1') or v1.get('artist', "")
        title = meta.get('TIT2') or v1.get('title', "")
        album = meta.get('TALB') or v1.get('album', "")
        year = meta.get('TDRC') or meta.get('TYER') or v1.get('year', "")
        created, modified = iso_local(meta.get('TDEN', "")), iso_local(meta.get('TDTG', ""))
        # a Windows Media Player ismeretlen albumnal az album nevebe a rippeles idejet irja: 'Ismeretlen album (2010.05.23. 15:50:07)'
        m = re.search(r'\((\d{4})[.\-/](\d\d)[.\-/](\d\d)\.?\s+(\d\d?):(\d\d)(?::(\d\d))?\)', album)
        if m and not created:
            try: created = plausible(datetime.datetime(*(int(x or 0) for x in m.groups())))
            except ValueError: pass
        m = re.match(r'\s*(\d{4})', year)
        if not m or not 1900 <= int(m.group(1)) <= datetime.date.today().year: year = ""
        prog = meta.get('TSSE') or meta.get('TENC') or meta.get('lame', "")
        alb = "%s (%s)" % (album, year) if album and year else album or year
        print_info("MP3", (fname, meta.get('stream', ""), "mp3", created, modified, "id3" if created or modified else "", "",
                           artist, title, prog, alb, result(res)))
    return res


def parse_mp3(d, debug, meta):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    errcnt = 0
    # ID3v2 tag(ek) az elejen (nehany tagelo program a regi tag ele ir egy ujat)
    p = 0
    while d[p:p + 3] == b'ID3':
        end, err = parse_id3v2(d, p, meta, log)
        if err:
            print("ERROR! MP3: %s" % err)
            return 10
        log("MP3: %s tag at %d, %d bytes" % (meta.get('id3'), p, end - p))
        p = end
    for fid, fd in meta.get('pics', []):
        err = check_picture(fid, fd)
        if err:
            print("ERROR! MP3: ID3v2 %s" % err)
            errcnt = 10

    # a file vegi tagek: ID3v1 (128 byte), Lyrics3v2, APE
    aend = n
    if aend - 128 >= p and d[aend - 128:aend - 125] == b'TAG':
        t = d[aend - 128:aend]
        f = lambda a, b: t[a:b].split(b'\x00')[0].decode('latin1').strip()
        v1 = {'title': f(3, 33), 'artist': f(33, 63), 'album': f(63, 93), 'year': f(93, 97)}
        # egy kodolo alapertelmezett (kitoltetlen) tagje: nem informacio
        if not (v1['title'] == "The Title" and v1['artist'] == "The Author"): meta['v1'] = v1
        aend -= 128
    for _ in range(2):
        if aend - 15 >= p and d[aend - 9:aend] == b'LYRICS200' and d[aend - 15:aend - 9].isdigit():
            aend -= 15 + int(d[aend - 15:aend - 9])
        if aend - 32 >= p and d[aend - 32:aend - 24] == b'APETAGEX':
            ver, size, items, flags = unpack_from('<LLLL', d, aend - 24)
            aend -= size + (32 if flags & 0x80000000 else 0)
    if aend < p: aend = p

    # az elso keret: a tag utani nullak utan; ha nem ott van, keresunk (ket egymast koveto ervenyes kerettel)
    def chained(q):
        h = frame_header(d, q) if q + 4 <= aend else None
        if not h: return None
        r = q + h[3]
        if r == aend: return h
        h2 = frame_header(d, r) if r + 4 <= aend else None
        return h if h2 and h2[0] == h[0] and h2[1] == h[1] and h2[4] == h[4] else None

    start = p
    while p < aend and d[p] == 0: p += 1
    if p >= aend:
        print("ERROR! MP3: no MPEG audio frames%s" % (" (only an ID3 tag)" if start else ""))
        return 10
    if not chained(p):
        q = d.find(b'\xff', p)
        while 0 <= q < aend and not chained(q): q = d.find(b'\xff', q + 1)
        if q < 0 or q >= aend:
            print("ERROR! MP3: no MPEG audio frames")
            return 10
        log("WARNING: %d bytes before the first frame" % (q - p))
        p = q
    first = frame_header(d, p)
    ver, layer, sr = first[0], first[1], first[4]
    meta['stream'] = "%s L%s" % (VERNAME[ver], "I" * layer)

    # Xing/Info/VBRI fejlec az elso keretben
    fstart = p
    si = 4 + (2 if first[2] else 0) + (side_info_len(ver, first[5]) if layer == 3 else 0)
    xing = vbr_frames = None
    lame = None
    if d[p + si:p + si + 4] in (b'Xing', b'Info'):
        xing = p + si
        fl, = unpack_from('>L', d, xing + 4)
        q = xing + 8
        if fl & 1: vbr_frames, = unpack_from('>L', d, q); q += 4
        if fl & 2: q += 4
        if fl & 4: q += 100
        if fl & 8: q += 4
        if d[q:q + 4] == b'LAME' or d[q:q + 4] == b'Lavf' or d[q:q + 4] == b'Lavc':
            lame = q
            meta['lame'] = d[q:q + 9].split(b'\x00')[0].decode('latin1').strip()
    elif d[p + 36:p + 40] == b'VBRI':
        vbr_frames, = unpack_from('>L', d, p + 50)

    # a keretek vegigjarasa
    frames = crcbad = crcchecked = 0
    gaps = []
    trunc = None
    while p < aend:
        h = frame_header(d, p) if p + 4 <= aend else None
        if h and h[0] == ver and h[1] == layer and h[4] == sr:
            if p + h[3] > aend:
                trunc = (p, aend - p, h[3])
                break
            if h[2] and layer == 3:          # CRC-vel vedett keret: a fejlec 3-4. byte-ja + az oldalinformacio
                sl = side_info_len(ver, h[5])
                crcchecked += 1
                if crc_mpeg(d[p + 6:p + 6 + sl], crc_mpeg(d[p + 2:p + 4])) != unpack_from('>H', d, p + 4)[0]:
                    crcbad += 1
                    if crcbad == 1: meta['crcfirst'] = p
            frames += 1
            p += h[3]
            continue
        # szinkron vesztes: a kovetkezo ervenyes kerettel folytatjuk
        q = d.find(b'\xff', p + 1)
        while 0 <= q < aend and not chained(q): q = d.find(b'\xff', q + 1)
        if q < 0 or q >= aend: q = aend
        gaps.append((p, q - p, not d[p:q].strip(b'\x00')))
        p = q
    log("MP3: %s, %d Hz, %d frames%s" % (meta['stream'], sr, frames, ", %d CRC protected" % crcchecked if crcchecked else ""))

    # a hezagok: a vegen levo (klaszter vegeig kiirt) szemet csak figyelmeztetes, a kozepen hiba
    if gaps and gaps[-1][0] + gaps[-1][1] == aend and gaps[-1][1] < 4096:
        g = gaps.pop()
        log("WARNING: %d %s bytes after the last frame" % (g[1], "zero" if g[2] else "garbage"))
    if gaps:
        lost = sum(g[1] for g in gaps)
        print("ERROR! MP3: %d gap(s) in the frame sequence (%d bytes), first at %d (%d %s bytes)" %
              (len(gaps), lost, gaps[0][0], gaps[0][1], "zero" if gaps[0][2] else "garbage"))
        errcnt = 10
    if trunc:
        print("ERROR! MP3: last frame at %d truncated (%d of %d bytes)" % trunc)
        errcnt = 10
    if crcbad:
        if crcbad == crcchecked and crcchecked > 10:
            log("WARNING: CRC wrong in all %d frames (encoder bug?)" % crcchecked)
        else:
            print("ERROR! MP3: CRC error in %d of %d frames, first at %d" % (crcbad, crcchecked, meta['crcfirst']))
            errcnt = 10
    if vbr_frames is not None:
        log("MP3: VBR header: %d frames" % vbr_frames)
        if frames < vbr_frames:
            print("ERROR! MP3: VBR header says %d frames, only %d found (truncated?)" % (vbr_frames, frames))
            errcnt = 10
        elif frames > vbr_frames + 1:
            log("WARNING: VBR header says %d frames, %d found" % (vbr_frames, frames))
    # LAME: a hangadat CRC-je (az Info keret utantol a zene vegeig) es az Info keret elso 190 byte-janak CRC-je
    if lame and lame + 36 <= n:
        mlen, mcrc, tcrc = unpack_from('>LHH', d, lame + 28)
        if crc_arc(d[fstart:fstart + 190]) != tcrc:
            log("WARNING: LAME tag CRC mismatch (not a LAME tag?)")
        elif mlen:
            flen = first[3]
            if fstart + mlen > n:
                print("ERROR! MP3: LAME music length %d, file is shorter (truncated)" % mlen)
                errcnt = 10
            # a regi LAME (pl. 3.92) a zenehosszba a file vegi ID3v1 tagot is beleszamolja, a CRC-t viszont csak a hangadatra
            elif crc_arc(d[fstart + flen:min(fstart + mlen, aend)]) != mcrc:
                print("ERROR! MP3: LAME music CRC mismatch (audio data damaged)")
                errcnt = 10
            else:
                log("MP3: LAME music CRC OK (%d bytes)" % (mlen - flen))
    return errcnt


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "_MP3/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testmp3(f.read(), debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res)
