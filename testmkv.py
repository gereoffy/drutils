#! /usr/bin/python3

# Matroska / WebM (MKV, MKA, WEBM) ellenorzes dekodolas nelkul: az EBML elemfa (ismeretlen meretu Segment/Cluster is),
# a blokkok (SimpleBlock/Block) es a lacing meretei, a H.264/HEVC kepkockak NAL keretezese (mint a testmp4-ben), a Cues es
# SeekHead index minden bejegyzese egy valodi elemre mutat, az opcionalis CRC-32 elemek. Metaadat: DateUTC (muxolas ideje),
# cim, program (WritingApp), eloado (Tags).
# Formatum leiras: RFC 8794 (EBML), RFC 9559 (Matroska).

import datetime
import zlib
from struct import unpack_from

from fileinfo import print_info, result, plausible, utc_to_local
from testmp4 import check_nal

EBML, SEGMENT, SEEKHEAD, INFO, TRACKS, CLUSTER, CUES, TAGS, ATTACH, CHAPTERS = (
    0x1A45DFA3, 0x18538067, 0x114D9B74, 0x1549A966, 0x1654AE6B, 0x1F43B675, 0x1C53BB6B, 0x1254C367, 0x1941A469, 0x1043A770)
LEVEL1 = {SEEKHEAD, INFO, TRACKS, CLUSTER, CUES, TAGS, ATTACH, CHAPTERS}
# a fa azon reszei, amelyekbe lemegyunk (a tobbi elemnek csak a meretet nezzuk)
MASTERS = {EBML, SEGMENT, SEEKHEAD, 0x4DBB, INFO, TRACKS, 0xAE, 0x6D80, 0x6240, 0x5034, CUES, 0xBB, 0xB7, CLUSTER, 0xA0, TAGS, 0x7373, 0x67C8}
CRC32_ID, VOID_ID = 0xBF, 0xEC
ZERO_RUN = bytes(64)
NAL_CODECS = {"V_MPEG4/ISO/AVC": 'avc', "V_MPEGH/ISO/HEVC": 'hevc'}


class El:
    __slots__ = ('id', 'start', 'data', 'size', 'kids')
    def __init__(self, eid, start, data, size):
        self.id, self.start, self.data, self.size, self.kids = eid, start, data, size, []
    def find(self, eid):
        for k in self.kids:
            if k.id == eid: return k
        return None
    def findall(self, eid):
        return [k for k in self.kids if k.id == eid]


def vint(d, p, keep):
    """ EBML valtozo hosszu egesz: (ertek, uj p, ismeretlen meret-e). keep: az ID-nel a jelzo bit is az ertek resze """
    b = d[p]
    if b == 0: raise ValueError("invalid EBML number (zero byte) at %d" % p)
    n, m = 1, 0x80
    while not b & m:
        n += 1
        m >>= 1
    v = b if keep else b & (m - 1)
    for i in range(1, n): v = (v << 8) | d[p + i]
    return v, p + n, (not keep and v == (1 << (7 * n)) - 1)


def mkv_kind(d):
    if d[:4] != b'\x1a\x45\xdf\xa3': return None
    p = d.find(b'\x42\x82', 4, 64)            # DocType
    if p < 0: return None
    try:
        n, q, _ = vint(d, p + 2, False)
    except (ValueError, IndexError):
        return None
    dt = d[q:q + n]
    return "webm" if dt == b'webm' else "mkv" if dt == b'matroska' else None


def parse(d, p, end, parent, err):
    """ a [p, end) elemei parent-be (a MASTERS-be rekurzivan). Hiba eseten err[0]-ba ir, es leall. visszaad: a vege """
    while p < end:
        try:
            eid, q, _ = vint(d, p, True)
            size, r, unknown = vint(d, q, False)
        except (ValueError, IndexError) as e:
            if not d[p:end].strip(b'\x00') and parent.id != CLUSTER:
                return end                      # nulla kitoltes a vegen (pl. Void helyett)
            err[0] = str(e)
            return p
        if unknown:
            if eid not in (SEGMENT, CLUSTER):
                err[0] = "element 0x%X at %d with unknown size" % (eid, p)
                return p
            size = end - r
        elif r + size > end:
            err[0] = "element 0x%X at %d: size %d, only %d bytes left in 0x%X (truncated?)" % (eid, p, size, end - r, parent.id)
            return p
        if parent.id == CLUSTER and eid in LEVEL1 and parent.size is None:
            return p                            # ismeretlen meretu Cluster vege: a kovetkezo felso szintu elem
        el = El(eid, p, r, size)
        parent.kids.append(el)
        if eid in MASTERS:
            if unknown and eid == CLUSTER: el.size = None
            e2 = parse(d, r, r + size, el, err)
            if err[0]: return e2
            if el.size is None: el.size = e2 - r
            size = el.size
        p = r + size
    return p


def uint(d, el): return int.from_bytes(d[el.data:el.data + el.size], 'big')
def text(d, el): return bytes(d[el.data:el.data + el.size]).split(b'\x00')[0].decode('utf-8', 'replace').strip()


def check_block(d, el, tracks):
    """ SimpleBlock / Block: track, lacing meretek, H.264/HEVC NAL keretezes. visszaad: hibauzenet vagy None """
    p, end = el.data, el.data + el.size
    try:
        tn, q, _ = vint(d, p, False)
    except (ValueError, IndexError) as e:
        return str(e)
    if q + 3 > end: return "block too short"
    flags = d[q + 2]
    q += 3
    tr = tracks.get(tn)
    if tr is None: return "block for unknown track %d" % tn
    lacing = (flags >> 1) & 3
    frames = []
    if lacing == 0:
        frames.append((q, end - q))
    else:
        cnt = d[q] + 1
        q += 1
        sizes = []
        if lacing == 1:                            # Xiph
            for i in range(cnt - 1):
                s = 0
                while True:
                    if q >= end: return "lacing truncated"
                    b = d[q]
                    q += 1
                    s += b
                    if b != 255: break
                sizes.append(s)
        elif lacing == 3:                          # EBML
            s, q, _ = vint(d, q, False)
            sizes.append(s)
            for i in range(cnt - 2):
                v, q2, _ = vint(d, q, False)
                n = q2 - q
                v -= (1 << (7 * n - 1)) - 1        # elojeles kulonbseg
                q = q2
                s += v
                sizes.append(s)
        else:                                      # fix
            if (end - q) % cnt: return "fixed lacing: %d bytes not divisible by %d frames" % (end - q, cnt)
            sizes = [(end - q) // cnt] * (cnt - 1)
        if any(s < 0 for s in sizes) or q + sum(sizes) > end: return "lace sizes exceed the block"
        for s in sizes:
            frames.append((q, s))
            q += s
        frames.append((q, end - q))
    strip = tr.get('strip')
    if strip:                                      # header stripping: a levagott byte-ok vissza a keret ele
        frames = [(strip + bytes(d[a:a + s]), 0, len(strip) + s) for a, s in frames]
    else:
        frames = [(d, a, s) for a, s in frames]
    if tr.get('nal'):
        for buf, a, s in frames:
            if s:
                e = check_nal(buf, a, s, tr['nlen'], tr['nal'])
                if e: return "track %d frame: %s" % (tn, e)
    elif tr['codec'] == "A_AAC":                   # AAC: tomoritett adatban nincs hosszu nullasor (a csend is rovid keret)
        for buf, a, s in frames:
            if buf.find(ZERO_RUN, a, a + s) >= 0: return "track %d (AAC) frame: zero bytes inside" % tn
    elif tr['codec'] in ("A_AC3", "A_EAC3"):       # AC3: minden keret szinkron szoval kezdodik (a csend lehet nulla, azt nem nezzuk)
        for buf, a, s in frames:
            if s >= 2 and buf[a:a + 2] != b'\x0b\x77': return "track %d (AC3) frame: no sync word" % tn
    return None


def testmkv(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py):
      MKV_INFO;filenev;kodekek;mkv|webm;muxolas ideje;;forras (mkv);;eloado;cim;program;;OK|BAD
    """
    meta = {}
    try:
        res = parse_mkv(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        created = meta.get('date')
        print_info("MKV", (fname, meta.get('codecs', ""), meta.get('kind', "mkv"), created, None, "mkv" if created else "", "",
                           meta.get('artist', ""), meta.get('title', ""), meta.get('app', ""), "", result(res)))
    return res


def parse_mkv(d, debug, meta):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    meta['kind'] = mkv_kind(d) or "mkv"
    root = El(0, 0, 0, n)
    err = [None]
    parse(d, 0, n, root, err)
    seg = root.find(SEGMENT)
    if err[0] and not seg:
        print("ERROR! MKV: %s" % err[0])
        return 10
    if not seg:
        print("ERROR! MKV: missing Segment")
        return 10
    sdata = seg.data
    # Info: datum, cim, program
    info = seg.find(INFO)
    if info:
        for k in info.kids:
            if k.id == 0x4461 and k.size == 8:
                ns = int.from_bytes(d[k.data:k.data + 8], 'big', signed=True)
                try: meta['date'] = plausible(utc_to_local(datetime.datetime(2001, 1, 1) + datetime.timedelta(microseconds=ns // 1000)))
                except OverflowError: pass
            elif k.id == 0x7BA9: meta['title'] = text(d, k)
            elif k.id == 0x5741: meta['app'] = text(d, k)
            elif k.id == 0x4D80 and 'app' not in meta: meta['app'] = text(d, k)
    tags = seg.find(TAGS)
    if tags:
        for tag in tags.findall(0x7373):
            for st in tag.findall(0x67C8):
                nm, val = st.find(0x45A3), st.find(0x4487)
                if nm and val and text(d, nm).upper() in ("ARTIST", "PERFORMER") and 'artist' not in meta: meta['artist'] = text(d, val)
    # Tracks
    tracks = {}
    trk = seg.find(TRACKS)
    codecs = []
    if trk:
        for te in trk.findall(0xAE):
            num, cid, priv = te.find(0xD7), te.find(0x86), te.find(0x63A2)
            if not num: continue
            t = {'codec': text(d, cid) if cid else ""}
            codecs.append(t['codec'])
            # ContentEncodings: a "header stripping" (ContentCompAlgo 3) minden keret elejerol levagja ugyanazokat a byte-okat
            # (pl. AC3: 0B 77): ezeket visszatesszuk; mas kodolasnal (zlib, titkositas) a kodek ellenorzest kihagyjuk
            ce = te.find(0x6D80)
            if ce:
                encs = ce.findall(0x6240)
                comp = encs[0].find(0x5034) if len(encs) == 1 else None
                algo = comp.find(0x4254) if comp else None
                sett = comp.find(0x4255) if comp else None
                if comp and algo and uint(d, algo) == 3 and not encs[0].find(0x5035):
                    t['strip'] = bytes(d[sett.data:sett.data + sett.size]) if sett else b''
                else:
                    t['codec'] = ""
            nal = NAL_CODECS.get(t['codec'])
            if nal and priv:
                pv = d[priv.data:priv.data + priv.size]
                if nal == 'avc' and len(pv) > 4: t['nal'], t['nlen'] = nal, (pv[4] & 3) + 1
                if nal == 'hevc' and len(pv) > 21: t['nal'], t['nlen'] = nal, (pv[21] & 3) + 1
            tracks[uint(d, num)] = t
    # rovid nevek, ismetles nelkul: V_MPEG4/ISO/AVC -> AVC, A_AC3 -> AC3, S_TEXT/UTF8 -> TEXT
    short = []
    for c in codecs:
        parts = c[2:].split('/')
        nm = parts[-1] if 'ISO' in parts else parts[0]
        if nm and nm not in short: short.append(nm)
    meta['codecs'] = "+".join(short)
    log("MKV: %s, %d tracks: %s, segment %s" % (meta['kind'], len(tracks), " ".join(codecs), "unknown size" if seg.size == n - sdata else "%d bytes" % seg.size))
    if err[0]:
        print("ERROR! MKV: %s" % err[0])
        return 10
    if sdata + seg.size < n:
        rest = d[sdata + seg.size:]
        log("WARNING: %d %s bytes after the segment" % (len(rest), "zero" if not rest.strip(b'\x00') else "garbage"))
    # CRC-32 elemek (egy master elso gyereke: a tobbi gyerek adatanak CRC-je)
    crcs = bad = 0
    stack = [seg]
    while stack:
        el = stack.pop()
        stack += [k for k in el.kids if k.kids]
        if el.kids and el.kids[0].id == CRC32_ID and el.kids[0].size == 4:
            c = el.kids[0]
            crcs += 1
            if zlib.crc32(d[c.data + 4:el.data + el.size]) != unpack_from('<L', d, c.data)[0]:
                bad += 1
                if bad == 1: print("ERROR! MKV: CRC-32 mismatch in element 0x%X at %d" % (el.id, el.start))
    if crcs: log("MKV: %d CRC-32 elements checked" % crcs)
    if bad: return 10
    # klaszterek es blokkok
    clusters = {}
    blocks = set()
    nblocks = 0
    for cl in seg.findall(CLUSTER):
        clusters[cl.start] = cl
        for k in cl.kids:
            bl = k if k.id == 0xA3 else (k.find(0xA1) if k.id == 0xA0 else None)
            if bl is None: continue
            blocks.add(k.start - cl.data)
            nblocks += 1
            e = check_block(d, bl, tracks)
            if e:
                print("ERROR! MKV: block at %d (cluster at %d): %s" % (bl.start, cl.start, e))
                return 10
    log("MKV: %d clusters, %d blocks" % (len(clusters), nblocks))
    # index: SeekHead es Cues
    for sh in seg.findall(SEEKHEAD):
        for sk in sh.findall(0x4DBB):
            sid, spos = sk.find(0x53AB), sk.find(0x53AC)
            if not sid or not spos: continue
            want, pos = uint(d, sid), sdata + uint(d, spos)
            try: got = vint(d, pos, True)[0] if pos < n else None
            except (ValueError, IndexError): got = None
            if got != want:
                print("ERROR! MKV: SeekHead entry for 0x%X points to %d, %s" % (want, pos, "outside of file (truncated?)" if pos >= n else "found 0x%X" % got if got else "invalid data"))
                return 10
    cues = seg.find(CUES)
    if cues:
        ncue = badcue = 0
        first = None
        for cp in cues.findall(0xBB):
            for tp in cp.findall(0xB7):
                cpos, rel = tp.find(0xF1), tp.find(0xF0)
                if not cpos: continue
                ncue += 1
                pos = sdata + uint(d, cpos)
                e = None
                if pos not in clusters: e = "points to %d, no cluster there%s" % (pos, " (outside of file)" if pos >= n else "")
                elif rel and uint(d, rel) not in blocks: e = "relative position %d in cluster at %d is not a block" % (uint(d, rel), pos)
                if e:
                    badcue += 1
                    if first is None: first = e
        log("MKV: %d cue entries" % ncue)
        if badcue:
            print("ERROR! MKV: %d of %d cue entries bad, first: %s" % (badcue, ncue, first))
            return 10
    elif not seg.find(CUES): log("WARNING: no Cues (index)")
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "_MKV/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testmkv(f.read(), debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res)
