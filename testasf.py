#! /usr/bin/python3

# ASF (WMV, WMA) ellenorzes dekodolas nelkul: a GUID-os objektumok szerkezete, a File Properties szerinti file meret es
# csomagszam, minden adatcsomag fejlece es payloadjai (a megadott hosszak pontosan kitoltik a csomagot), a kuldesi idok
# sorrendje (egy kinullazott csomagnal visszaugrik), az index csomagszamai. Metaadat: letrehozas datuma (File Properties),
# cim, szerzo (Content Description), program, album, ev (Extended Content Description).
# Formatum leiras: Advanced Systems Format (ASF) Specification, Revision 01.20.05.

import datetime
import re
import uuid
from struct import unpack_from

from fileinfo import print_info, result, plausible, utc_to_local, date_source

def _g(s): return uuid.UUID(s).bytes_le
HEADER = _g("75B22630-668E-11CF-A6D9-00AA0062CE6C")
DATA = _g("75B22636-668E-11CF-A6D9-00AA0062CE6C")
FILE_PROPS = _g("8CABDCA1-A947-11CF-8EE4-00C00C205365")
STREAM_PROPS = _g("B7DC0791-A9B7-11CF-8EE6-00C00C205365")
HEADER_EXT = _g("5FBF03B5-A92E-11CF-8EE3-00C00C205365")
CONTENT_DESC = _g("75B22633-668E-11CF-A6D9-00AA0062CE6C")
EXT_CONTENT_DESC = _g("D2D0A440-E307-11D2-97F0-00A0C95EA850")
SIMPLE_INDEX = _g("33000890-E5B1-11CF-89F4-00A0C90349CB")
INDEX = _g("D6E229D3-35DA-11D1-9034-00A0C90349BE")
STREAM_TYPES = {_g("F8699E40-5B4D-11CF-A8FD-00805F5C442B"): "audio", _g("BC19EFC0-5B4D-11CF-A8FD-00805F5C442B"): "video"}

ZERO_RUN = bytes(64)        # tomoritett video adatban nem lehet ennyi nulla egymas utan: kinullazott szektor
LEN = (0, 1, 2, 4)          # a "length type" bitek: 0 = nincs mezo, 1 = BYTE, 2 = WORD, 3 = DWORD


def asf_kind(d):
    return d[:16] == HEADER and len(d) >= 30


def _filetime(x):
    try:
        return plausible(utc_to_local(datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=x // 10))) if x else None
    except (OverflowError, ValueError):
        return None


def _rd(d, p, t):
    """ t tipusu (0/1/2/3) mezo p-n: (ertek, uj p) """
    n = LEN[t]
    return (int.from_bytes(d[p:p + n], 'little') if n else 0), p + n


def check_packet(d, p, psize, video=()):
    """ egy adatcsomag fejlece es payloadjai. visszaad: (kuldesi ido, hibauzenet vagy None) """
    start, end = p, p + psize
    b = d[p]
    if b & 0x80:                                   # error correction data
        if b & 0x10 or b & 0x60: return None, "bad error correction flags 0x%02X" % b
        p += 1 + (b & 0x0F)
        b = d[p]
    if b & 0x80: return None, "bad length type flags 0x%02X" % b
    ltf, prop = b, d[p + 1]
    p += 2
    plen, p = _rd(d, p, (ltf >> 5) & 3)
    seq, p = _rd(d, p, (ltf >> 1) & 3)
    pad, p = _rd(d, p, (ltf >> 3) & 3)
    send, dur = unpack_from('<LH', d, p)
    p += 6
    if plen > psize: return send, "packet length %d > packet size %d" % (plen, psize)
    if plen: end = start + plen                    # rovidebb csomag: utana nulla kitoltes a csomagmeretig
    rt, ot, mt = prop & 3, (prop >> 2) & 3, (prop >> 4) & 3
    if (prop >> 6) & 3 != 1: return send, "bad stream number length type (property flags 0x%02X)" % prop
    if ltf & 1:                                    # tobb payload
        pf = d[p]
        p += 1
        count, plt = pf & 0x3F, pf >> 6
        if count == 0: return send, "multiple payloads with count 0"
    else:
        count, plt = 1, None
    for i in range(count):
        sn = d[p] & 0x7F                           # stream szam
        p += 1
        _, p = _rd(d, p, mt)
        _, p = _rd(d, p, ot)
        repl, p = _rd(d, p, rt)
        p += repl
        if plt is not None:
            n, p = _rd(d, p, plt)
        else:
            n = end - pad - p                      # egyetlen payload: a csomag vegeig (a padding elott)
        if n < 0 or p + n > end - (pad if i == count - 1 else 0): return send, "payload %d length %d exceeds the packet" % (i, n)
        # nulla blokk csak a videoban hiba (a hangban a csend lehet nulla)
        if sn in video and repl != 1 and d.find(ZERO_RUN, p, p + n) >= 0: return send, "zero bytes inside video payload %d" % i
        p += n
    if p + pad > end: return send, "payloads and padding exceed the packet"
    if d[p + pad:end].strip(b'\x00'): return send, "%d bytes left in packet after the payloads" % (end - p - pad)
    return send, None


def testasf(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py):
      ASF_INFO;filenev;stream-ek (video/audio);wmv|wma;letrehozas;utolso mentes;forras (asf|olympus|wm);;szerzo;cim;program;album (ev) vagy eszkoz;OK|BAD
    """
    meta = {}
    try:
        res = parse_asf(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        ext = meta.get('ext', {})
        album, year = ext.get('WM/AlbumTitle', ""), ext.get('WM/Year', "")
        alb = "%s (%s)" % (album, year) if album and year else album or year
        created, src_c = meta.get('created'), "asf"
        modified, src_m = None, ""
        rec = meta.get('rec')
        if rec and rec[0]:                                   # diktafon: a felvetel kezdete es vege
            created, src_c, modified, src_m = rec[0], "olympus", rec[1], "olympus"
        if not created and ext.get('WM/EncodingTime'): created, src_c = _filetime(int(ext['WM/EncodingTime'])), "wm"
        alb_or_dev = meta.get('device') or alb
        print_info("ASF", (fname, meta.get('streams', ""), "wmv" if "video" in meta.get('streams', "") else "wma", created, modified,
                           date_source(created, modified, src_c, src_m), "", meta.get('author') or ext.get('WM/AlbumArtist', ""),
                           meta.get('title', ""), ext.get('WM/ToolName', "") or ext.get('WM/EncodedBy', ""), alb_or_dev, result(res)))
    return res


def parse_asf(d, debug, meta):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    hsize, nobj = unpack_from('<QL', d, 16)
    if hsize < 30 or hsize > n:
        print("ERROR! ASF: header object size %d (file %d bytes)%s" % (hsize, n, " (truncated)" if hsize > n else ""))
        return 10
    # a header objektum gyerekei
    p, hend = 30, hsize
    props = None
    streams = []
    video = set()          # a video streamek szama
    k = 0
    while p < hend:
        if p + 24 > hend:
            print("ERROR! ASF: %d bytes of garbage at the end of the header object" % (hend - p))
            return 10
        g = d[p:p + 16]
        size, = unpack_from('<Q', d, p + 16)
        if size < 24 or p + size > hend:
            print("ERROR! ASF: header object #%d at %d: bad size %d" % (k, p, size))
            return 10
        if g == FILE_PROPS: props = p + 24
        elif g == STREAM_PROPS:
            st = STREAM_TYPES.get(d[p + 24:p + 40], "other")
            streams.append(st)
            if st == "video": video.add(unpack_from('<H', d, p + 24 + 48)[0] & 0x7F)
        elif g == CONTENT_DESC:
            ls = unpack_from('<5H', d, p + 24)
            q = p + 34
            vals = []
            for l in ls:
                vals.append(d[q:q + l].decode('utf-16le', 'replace').replace('\x00', '').strip())
                q += l
            meta['title'], meta['author'] = vals[0], vals[1]
        elif g == EXT_CONTENT_DESC:
            ext = meta.setdefault('ext', {})
            cnt, = unpack_from('<H', d, p + 24)
            q = p + 26
            for _ in range(cnt):
                nl, = unpack_from('<H', d, q)
                name = d[q + 2:q + 2 + nl].decode('utf-16le', 'replace').replace('\x00', '')
                q += 2 + nl
                vt, vl = unpack_from('<HH', d, q)
                v = d[q + 4:q + 4 + vl]
                q += 4 + vl
                if vt == 0: ext[name] = v.decode('utf-16le', 'replace').replace('\x00', '').strip()
                elif vt in (3, 4, 5) and vl in (2, 4, 8): ext[name] = str(int.from_bytes(v, 'little'))
                elif vt == 1 and name == "OLYMPUS":     # Olympus diktafon: tipus + a felvetel kezdete, vege (YYMMDDhhmmss), hossza
                    m = re.search(rb'(\d{12})(\d{12})\d{6}', v)
                    def yymmdd(x):
                        try: return plausible(datetime.datetime(2000 + int(x[0:2]), int(x[2:4]), int(x[4:6]), int(x[6:8]), int(x[8:10]), int(x[10:12])))
                        except ValueError: return None
                    if m: meta['rec'] = (yymmdd(m.group(1)), yymmdd(m.group(2)))
                    meta['device'] = ("OLYMPUS " + v[12:28].decode('latin1').strip()).strip()
        p += size
        k += 1
    if k != nobj: log("WARNING: header says %d objects, %d found" % (nobj, k))
    meta['streams'] = "+".join(sorted(set(streams), reverse=True))
    if props is None:
        print("ERROR! ASF: missing File Properties object")
        return 10
    fsize, cdate, packets, play, send, preroll, flags, minp, maxp = unpack_from('<QQQQQQLLL', d, props + 16)
    meta['created'] = _filetime(cdate)
    broadcast = flags & 1
    log("ASF: %s, file size %d (header: %d), %d packets of %d bytes, flags 0x%X" % (meta['streams'], n, fsize, packets, maxp, flags))
    if not broadcast:
        if fsize > n:
            print("ERROR! ASF: file is %d bytes, header says %d (truncated)" % (n, fsize))
            return 10
        if fsize < n: log("WARNING: %d bytes after the end of file (size %d in header)" % (n - fsize, fsize))
    psize = maxp
    if minp != maxp or not psize:
        print("ERROR! ASF: variable packet size (%d..%d) not supported" % (minp, maxp))
        return 10

    # data objektum
    p = hsize
    if d[p:p + 16] != DATA:
        print("ERROR! ASF: data object expected at %d" % p)
        return 10
    dsize, = unpack_from('<Q', d, p + 16)
    dpackets, = unpack_from('<Q', d, p + 40)
    if not broadcast and dpackets != packets: log("WARNING: data object says %d packets, file properties %d" % (dpackets, packets))
    if dsize and p + dsize > n:
        print("ERROR! ASF: data object %d bytes, only %d in file (truncated)" % (dsize, n - p))
        return 10
    if dsize and dsize != 50 + dpackets * psize:
        print("ERROR! ASF: data object size %d, %d packets x %d + 50 = %d" % (dsize, dpackets, psize, 50 + dpackets * psize))
        return 10
    dend = p + dsize if dsize else n
    # a csomagok
    q = p + 50
    last = -1
    bad = 0
    first = None
    cnt = 0
    while q + psize <= dend:
        send, err = check_packet(d, q, psize, video)
        if not err and send is not None and send + 2000 < last: err = "send time %d ms after %d ms" % (send, last)   # kis visszaugras megengedett
        if err:
            bad += 1
            if first is None: first = "packet %d at %d: %s" % (cnt, q, err)
        elif send is not None: last = max(last, send)
        q += psize
        cnt += 1
    log("ASF: %d data packets checked" % cnt)
    if q < dend: log("WARNING: %d bytes after the last packet" % (dend - q))
    if bad:
        print("ERROR! ASF: %d of %d data packets bad, first: %s" % (bad, cnt, first))
        return 10
    # a data utani objektumok (index)
    p = dend
    while p + 24 <= n:
        g = d[p:p + 16]
        size, = unpack_from('<Q', d, p + 16)
        if size < 24 or p + size > n:
            if not d[p:].strip(b'\x00'): break
            print("ERROR! ASF: object at %d after the data: bad size %d (file %d bytes)%s" % (p, size, n, " (truncated)" if p + size > n else ""))
            return 10
        if g == SIMPLE_INDEX and size >= 56:
            ecount, = unpack_from('<L', d, p + 52)
            badidx = 0
            for i in range(min(ecount, (size - 56) // 6)):
                pk, = unpack_from('<L', d, p + 56 + 6 * i)
                if pk >= cnt: badidx += 1
            log("ASF: simple index, %d entries" % ecount)
            if badidx:
                print("ERROR! ASF: %d simple index entries point beyond the %d packets" % (badidx, cnt))
                return 10
        p += size
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "_WMV/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testasf(f.read(), debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res)
