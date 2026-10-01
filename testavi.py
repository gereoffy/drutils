#! /usr/bin/python3

# RIFF alapu formatumok: AVI, WebP, WAV es CorelDRAW (lent).
# AVI (RIFF) ellenorzes: a chunk szerkezet, az index (idx1, OpenDML indx/ix##) minden bejegyzese egy ervenyes chunkra
# mutat-e, es a felvetel datuma (IDIT, LIST INFO, Fuji strd EXIF). A kodekeket nem dekodoljuk (lassu es a nagy fileoknal
# ertelmetlen), csak a videokockak elejet (MJPEG: FFD8, MPEG-4/H.264: 00 00 01), es hogy nincs-e bennuk nulla blokk.
# Formatum leiras: Microsoft AVI RIFF File Reference, OpenDML AVI File Format Extensions 1.02.

import datetime
import re
import zlib
from struct import unpack_from

from fileinfo import print_info, result, iso_local, tiff_meta, xmp_meta, image_info, device, plausible, date_source

fourcc_re = re.compile(rb'[\x20-\x7e]{4}$')
# azok a LIST-ek, amelyek tartalma nem chunk szerkezetu (CorelDRAW: tomoritett blokk, stilusok), ezekbe nem megyunk bele
OPAQUE_LISTS = {b'cmpr', b'stlt'}
# a movi listaban: ##dc (video), ##db (tomoritetlen video), ##wb (hang), ##pc (paletta), ##tx (felirat), ix## (OpenDML index)
movi_id_re = re.compile(rb'(\d\d)(dc|db|wb|pc|tx)$|ix\d\d$')
JPEG_CODECS = {b'MJPG', b'mjpg', b'AVRn', b'dmb1', b'JPEG', b'jpeg', b'MJPA'}
MPEG4_CODECS = {b'XVID', b'xvid', b'DIVX', b'divx', b'DX50', b'dx50', b'FMP4', b'fmp4', b'MP4V', b'mp4v', b'DIV3', b'3IV2'}
ZERO_RUN = bytes(64)   # kodolt videoadatban (MJPEG, MPEG-4, H.264) nem lehet ennyi nulla egymas utan: kinullazott szektor
H264_CODECS = {b'H264', b'h264', b'X264', b'x264', b'AVC1', b'avc1'}


class Chunk:
    __slots__ = ('id', 'start', 'data', 'size', 'form', 'kids')
    def __init__(self, cid, start, size, form=None):
        self.id, self.start, self.data, self.size, self.form, self.kids = cid, start, start + 8, size, form, []
    def find(self, cid, form=None):
        for k in self.kids:
            if k.id == cid and (form is None or k.form == form): return k
        return None


def parse_chunks(d, start, end, parent, where, big=None):
    """ a [start, end) tartomany chunkjai (a LIST-ek rekurzivan). visszaad: hibauzenet vagy None """
    p = start
    while p < end:
        if end - p < 8:
            if not d[p:end].strip(b'\x00'): return None   # nulla kitoltes a lista vegen
            return "%d bytes of garbage at %d (in %s)" % (end - p, p, where)
        cid = d[p:p + 4]
        size, = unpack_from('<L', d, p + 4)
        if big and size == 0xFFFFFFFF and cid in big: size = big[cid]       # RF64: a valodi meret a ds64 chunkban
        if not fourcc_re.match(cid):
            if not d[p:end].strip(b'\x00'): return None
            # a movi listaban a ##dc/##wb chunk serult azonositoja (pl. Canon firmware hiba): az index alapjan dontunk rola
            if not (where == "movi" and cid[2:] in (b'dc', b'db', b'wb', b'pc', b'tx') and p + 8 + size <= end):
                return "bad chunk id %r at %d (in %s)" % (cid, p, where)
        if p + 8 + size > end: return "chunk %s at %d: size %d, only %d bytes left in %s (truncated?)" % (cid.decode('latin1'), p, size, end - p - 8, where)
        if cid in (b'LIST', b'RIFF'):
            form = d[p + 8:p + 12]
            if size < 4 or not fourcc_re.match(form): return "bad %s at %d (form %r)" % (cid.decode(), p, form)
            c = Chunk(cid, p, size, form)
            parent.kids.append(c)
            if form not in OPAQUE_LISTS:
                err = parse_chunks(d, p + 12, p + 8 + size, c, form.decode('latin1').strip(), big)
                if err: return err
        else:
            parent.kids.append(Chunk(cid, p, size))
        p += 8 + size + (size & 1)
    return None


def parse_riff(d, form, next_form, label, log, riff_size=None):
    """
    a RIFF szegmens(ek) a file elejetol: RIFF <form>, utana (OpenDML-nel) RIFF <next_form>-ok. A file vege utani
    maradek (visszaallitasnal a klaszter vegeig kiirt resz) csak figyelmeztetes. riff_size: az elso szegmens merete a
    fejlecben levo helyett. visszaad: (szegmensek, hibauzenet vagy None)
    """
    n = len(d)
    segs = []
    p = 0
    big = None
    while p + 12 <= n and (d[p:p + 4] == b'RIFF' or (p == 0 and d[:4] == b'RF64')):
        size, = unpack_from('<L', d, p + 4)
        f = d[p + 8:p + 12]
        if f != (form if p == 0 else next_form): break
        if p == 0 and riff_size is not None: size = riff_size
        if d[p:p + 4] == b'RF64' and size == 0xFFFFFFFF and d[12:16] == b'ds64':   # RF64 (4 GB folotti WAV): 64 bites meretek
            rsize, dsize = unpack_from('<QQ', d, 20)
            size, big = rsize, {b'data': dsize}
        if p + 8 + size > n:
            return segs, "RIFF %s at %d: size %d, only %d bytes in file (truncated)" % (f.decode('latin1').strip(), p, size, n - p - 8)
        seg = Chunk(b'RIFF', p, size, f)
        segs.append(seg)
        err = parse_chunks(d, p + 12, p + 8 + size, seg, f.decode('latin1').strip(), big)
        if err: return segs, err
        p += 8 + size + (size & 1)
    if not segs: return segs, "not a RIFF %s file" % form.decode('latin1').strip()
    if p < n:
        if not d[p:].strip(b'\x00'): log("WARNING: %d zero bytes after the end of %s" % (n - p, label))
        else: log("WARNING: %d bytes of garbage after the end of %s (recovered file?)" % (n - p, label))
    return segs, None


def _avi_date(s):
    """ IDIT / ICRD: 'Wed Feb 02 15:05:50 2011', '2011:02:02 15:05:50', '2011-02-02' ... -> helyi ido """
    s = s.split(b'\x00')[0].decode('latin1', 'replace').strip()
    m = re.match(r'\w{3}\s+(\w{3})\s+(\d+)\s+(\d+):(\d+):(\d+)\s+(\d{4})', s)
    if m:
        try:
            mon = "jan feb mar apr may jun jul aug sep oct nov dec".split().index(m.group(1).lower()) + 1
            return plausible(datetime.datetime(int(m.group(6)), mon, int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))))
        except ValueError:
            return None
    return iso_local(s)


def avi_info(d, segs, codec):
    """ visszaad: (letrehozas, modositas, forras, szerzo, cim, program, eszkoz) """
    created = modified = None
    src_c = src_m = ""
    info = {}
    make = model = ""
    for seg in segs:
        stack = [seg]
        while stack:
            c = stack.pop()
            if c.form == b'movi': continue                         # a kepkockak kozott nincs metaadat
            stack += c.kids
            if c.id not in (b'IDIT', b'strd', b'JUNK', b'ICRD', b'ISFT', b'INAM', b'IART', b'ICMT'): continue
            body = d[c.data:c.data + min(c.size, 1 << 16)]
            if c.id == b'IDIT' and not created:
                created, src_c = _avi_date(body), "idit"
            elif c.id == b'strd' and body[:4] == b'AVIF':          # Fujifilm: EXIF IFD fejlec nelkul
                m = tiff_meta(body[8:], ifd0=0)
                if m.get('created') and not created: created, src_c = m['created'], "exif"
                if m.get('modified'): modified, src_m = m['modified'], "exif"
                make, model = m.get('make', ""), m.get('model', "")
            elif c.id == b'strd' and not make:                     # mas kamerak: a gyarto szovegesen
                s = re.search(rb'[ -~]{6,}', body[:256])
                if s: make = s.group().decode('latin1').strip()
            elif c.id == b'JUNK' and body[:4] == b'IIII':          # HP: a tipus szovegesen
                s = re.search(rb'[ -~]{4,}', body[4:64])
                if s: model = s.group().decode('latin1').strip()
            elif c.id == b'JUNK':                                  # a VirtualDub a nevet a kitoltesbe irja
                s = re.match(rb'\x00*([ -~]{8,})', body)
                if s and re.search(rb'[A-Za-z]{3}', s.group(1)): info.setdefault(b'JUNKSW', s.group(1).decode('latin1').strip())
            elif c.id[:1] == b'I':
                v = body.split(b'\x00')[0]
                try: v = v.decode('utf-8')
                except UnicodeDecodeError: v = v.decode('latin1')
                info.setdefault(c.id, v.strip())
    if not created and info.get(b'ICRD'): created, src_c = _avi_date(info[b'ICRD'].encode('latin1')), "info"
    return (created, modified, date_source(created, modified, src_c, src_m), info.get(b'IART', ""), info.get(b'INAM', ""),
            info.get(b'ISFT', "") or info.get(b'JUNKSW', ""), device(make, model))


def check_index(d, entries, chunks, label):
    """ entries: [(chunk id, chunk fejlec pozicio, meret)], chunks: {pozicio: (id, meret)}. visszaad: (hibas, elso hiba) """
    bad = 0
    first = None
    for cid, pos, size in entries:
        c = chunks.get(pos)
        err = None
        if c is None: err = "points to %d, no chunk there" % pos if pos + 8 <= len(d) else "points to %d, outside of file (truncated?)" % pos
        elif c[0] != cid: err = "points to %s instead of %s at %d" % (c[0].decode('latin1'), cid.decode('latin1'), pos)
        elif cid != b'rec ' and c[1] != size: err = "%s at %d: size %d, index says %d" % (cid.decode('latin1'), pos, c[1], size)
        if err:
            bad += 1
            if first is None: first = "%s entry %s" % (label, err)
    return bad, first


def testavi(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py):
      AVI_INFO;filenev;video kodek;avi;letrehozas;modositas;forras (idit|info|exif);;szerzo;cim;program;eszkoz;OK|BAD
    """
    meta = {}
    try:
        res = parse_avi(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        try: i = avi_info(data, meta.get('segs', []), meta.get('codec', b''))
        except Exception: i = (None, None, "", "", "", "", "")
        print_info("AVI", (fname, meta.get('codec', b'').decode('latin1').strip(), "avi") + i[:3] + ("",) + i[3:] + (result(res),))
    return res


def parse_avi(d, debug, meta):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    # RIFF szegmensek: RIFF AVI, OpenDML-nel utana RIFF AVIX-ek
    segs, err = parse_riff(d, b'AVI ', b'AVIX', "AVI", log)
    meta['segs'] = segs
    if err:
        print("ERROR! AVI: %s" % err)
        return 10

    first = segs[0]
    hdrl = first.find(b'LIST', b'hdrl')
    if not hdrl or not hdrl.find(b'avih'):
        print("ERROR! AVI: missing hdrl/avih")
        return 10
    avih = hdrl.find(b'avih')
    usec, maxbps, pad, flags, frames, init, nstreams = unpack_from('<7L', d, avih.data)
    strls = [c for c in hdrl.kids if c.id == b'LIST' and c.form == b'strl']
    log("AVI: %d RIFF segment(s), %d streams (avih: %d), %d frames, flags 0x%X" % (len(segs), len(strls), nstreams, frames, flags))
    if len(strls) != nstreams: log("WARNING: avih says %d streams, %d strl lists" % (nstreams, len(strls)))
    streams = []
    for i, s in enumerate(strls):
        strh, strf = s.find(b'strh'), s.find(b'strf')
        if not strh or strh.size < 48:
            print("ERROR! AVI: stream %d: missing strh" % i)
            return 10
        typ, handler = d[strh.data:strh.data + 4], d[strh.data + 4:strh.data + 8]
        length, = unpack_from('<L', d, strh.data + 32)
        comp = d[strf.data + 16:strf.data + 20] if typ == b'vids' and strf and strf.size >= 20 else b''
        streams.append({'type': typ, 'handler': handler, 'comp': comp, 'length': length, 'indx': s.find(b'indx'), 'frames': 0})
        log("AVI: stream %d: %s %r %r, length %d" % (i, typ.decode('latin1'), handler, comp, length))
        if typ == b'vids' and not meta.get('codec'): meta['codec'] = comp or handler

    # a movi listak chunkjai (a rec listakon belul is): pozicio -> (id, meret)
    chunks = {}
    movis = []
    badids = {}            # hibas azonositoju chunkok: pozicio -> (id, meret); az index alapjan dontunk roluk
    badframes = 0
    firstbad = None
    for seg in segs:
        movi = seg.find(b'LIST', b'movi')
        if not movi:
            if seg is first:
                print("ERROR! AVI: missing movi list")
                return 10
            continue
        movis.append(movi)
        stack = [movi]
        while stack:
            lst = stack.pop()
            for c in lst.kids:
                if c.id == b'LIST':
                    if c.form == b'rec ':
                        chunks[c.start] = (b'rec ', c.size)
                        stack.append(c)
                    continue
                chunks[c.start] = (c.id, c.size)
                if c.id == b'JUNK': continue
                m = movi_id_re.match(c.id)
                if not m or (m.group(1) and int(m.group(1)) >= len(streams)):
                    badids[c.start] = (c.id, c.size)
                    continue
                if not m.group(1): continue
                st = streams[int(m.group(1))]
                st['frames'] += 1
                # a videokocka eleje (nem dekodolunk): MJPEG FFD8, MPEG-4/H.264 start kod; csupa nulla eleje: kinullazott szektor
                if st['type'] == b'vids' and c.size >= 16:
                    head = d[c.data:c.data + 16]
                    codec = st['comp'] or st['handler']
                    ok = (head.strip(b'\x00') != b'' and
                          (head[:2] == b'\xff\xd8' if codec in JPEG_CODECS else
                           head[:3] == b'\x00\x00\x01' if codec in MPEG4_CODECS else
                           head[:3] == b'\x00\x00\x01' or head[:4] == b'\x00\x00\x00\x01' if codec in H264_CODECS else True))
                    if not ok:
                        badframes += 1
                        if firstbad is None: firstbad = "%s at %d starts with %s" % (c.id.decode(), c.start, head[:8].hex(' '))
                    else:
                        # nulla blokk a kocka belsejeben (a vegi nulla kitoltes megengedett); bytes.find: gyors, nem dekodol
                        z = d.find(ZERO_RUN, c.data, c.data + c.size)
                        if z >= 0 and d[z:c.data + c.size].strip(b'\x00'):
                            badframes += 1
                            if firstbad is None: firstbad = "%s at %d: zero bytes at %d inside the frame" % (c.id.decode(), c.start, z)
    for i, st in enumerate(streams):
        log("AVI: stream %d: %d chunks in movi" % (i, st['frames']))
        if st['type'] == b'vids' and st['length'] and st['frames'] and st['frames'] != st['length']:
            log("WARNING: stream %d: strh length %d, %d chunks" % (i, st['length'], st['frames']))
    if badframes:
        print("ERROR! AVI: %d video frames with bad start, first: %s" % (badframes, firstbad))
        return 10

    # idx1: a regi index, az eltolas a movi lista 'movi' fourcc-jahoz vagy a file elejehez kepest
    idx1 = first.find(b'idx1')
    nidx = 0
    if idx1:
        cnt = idx1.size // 16
        raw = [unpack_from('<4sLLL', d, idx1.data + 16 * i) for i in range(cnt)]
        # a chunk fejlec helye: base + eltolas, ahol base a 'movi' fourcc helye (szokasos) vagy 0 (file eleje)
        base = None
        for cid, fl, off, size in raw[:20]:
            if chunks.get(movis[0].data + off, (None,))[0] == cid: base = movis[0].data; break
            if chunks.get(off, (None,))[0] == cid: base = 0; break
        if base is None: base = movis[0].data
        entries = [(cid, base + off, size) for cid, fl, off, size in raw]
        # hibas chunk azonosito, de az index ugyanide ugyanilyen meretu, ugyanolyan vegu (dc/wb) chunkot mutat: egyes
        # Canon fenykepezogepek a hangcsomag utan 2 byte-tal felulirjak a kovetkezo chunk azonositojat (iroi hiba, nem serules)
        byidx = {pos: (cid, size) for cid, pos, size in entries}
        for pos, (cid, size) in list(badids.items()):
            e = byidx.get(pos)
            if e and e[1] == size and e[0][2:] == cid[2:] and movi_id_re.match(e[0]):
                log("WARNING: chunk id %r at %d overwritten, index says %r (writer bug)" % (cid, pos, e[0]))
                chunks[pos] = e
                del badids[pos]
        bad, firsterr = check_index(d, entries, chunks, "idx1")
        log("AVI: idx1: %d entries, offsets relative to %s" % (cnt, "movi" if base else "file start"))
        if bad:
            print("ERROR! AVI: %d of %d idx1 entries bad, first: %s" % (bad, cnt, firsterr))
            return 10
        nidx += cnt
    if badids:
        pos = min(badids)
        print("ERROR! AVI: bad chunk id %r at %d in movi%s" % (badids[pos][0], pos, " (%d bad chunk ids)" % len(badids) if len(badids) > 1 else ""))
        return 10
    # OpenDML: strl/indx (super index -> ix## chunkok, vagy kozvetlenul standard index)
    for i, st in enumerate(streams):
        ix = st['indx']
        if not ix or ix.size < 24: continue
        lpe, sub, itype, inuse = unpack_from('<HBBL', d, ix.data)
        stdidx = []
        if itype == 0:                            # AVI_INDEX_OF_INDEXES
            for k in range(min(inuse, (ix.size - 24) // 16)):
                off, size, dur = unpack_from('<QLL', d, ix.data + 24 + 16 * k)
                c = chunks.get(off)
                if c is None or c[0][:2] != b'ix' or c[1] + 8 != size:
                    print("ERROR! AVI: stream %d: super index entry %d points to %d, not to an ix## chunk%s" % (i, k, off, " (truncated?)" if off >= len(d) else ""))
                    return 10
                stdidx.append(off + 8)
        elif itype == 1:                          # AVI_INDEX_OF_CHUNKS kozvetlenul az indx-ben
            stdidx.append(ix.data)
        entries = []
        for q in stdidx:
            lpe2, sub2, t2, inuse2, cid = unpack_from('<HBBL4s', d, q)
            base, = unpack_from('<Q', d, q + 12)
            for k in range(inuse2):
                off, size = unpack_from('<LL', d, q + 24 + 8 * k)
                entries.append((cid, base + off - 8, size & 0x7FFFFFFF))
        bad, firsterr = check_index(d, entries, chunks, "stream %d OpenDML index" % i)
        log("AVI: stream %d: OpenDML index, %d entries" % (i, len(entries)))
        if bad:
            print("ERROR! AVI: %d of %d OpenDML index entries bad, first: %s" % (bad, len(entries), firsterr))
            return 10
        nidx += len(entries)
    if not nidx: log("WARNING: no index (idx1 / OpenDML)")
    return 0



###############################################################################################################################
# WebP (RIFF WEBP) ellenorzes dekodolas nelkul: a RIFF es a chunkok merete (csonkolas), a VP8X jelzobitek osszhangja a
# chunkokkal, a VP8 / VP8L kepfejlec (start kod, meret, az elso particio a chunkon belul), a vesztesegmentes (VP8L) es a
# tomoritett alfa adat nulla blokkjai, animacio: minden ANMF keret a vasznon belul es benne kepadat. A veszteseges VP8
# adatban az egyszinu teruleteken hosszu nullasor is lehet, ott a kinullazott szektor dekodolas nelkul nem derul ki.
# Metaadat: EXIF (keszites, modositas, eszkoz, program), XMP. Formatum leiras: RFC 9649 (WebP), RFC 6386 (VP8).
###############################################################################################################################

WEBP_ZERO_RUN = bytes(64)   # a VP8L (prefix kodolt) es a tomoritett alfa adatban ennyi nulla nem lehet: kinullazott szektor


def webp_kind(d):
    return len(d) >= 20 and d[:4] == b'RIFF' and d[8:12] == b'WEBP'


def check_vp8(d, p, size):
    """ VP8 (veszteseges) kepadat: (szelesseg, magassag, hibauzenet vagy None) """
    if size < 10: return 0, 0, "VP8 chunk too short"
    tag = d[p] | d[p + 1] << 8 | d[p + 2] << 16
    if tag & 1: return 0, 0, "VP8: not a key frame"
    if (tag >> 1) & 7 > 3: return 0, 0, "VP8: bad version %d" % ((tag >> 1) & 7)
    first = tag >> 5
    if d[p + 3:p + 6] != b'\x9d\x01\x2a': return 0, 0, "VP8: bad start code %s" % d[p + 3:p + 6].hex()
    w, h = unpack_from('<HH', d, p + 6)
    w, h = w & 0x3FFF, h & 0x3FFF
    if not w or not h: return w, h, "VP8: zero image size"
    if 10 + first > size: return w, h, "VP8: first partition (%d bytes) exceeds the chunk (%d)" % (first, size)
    return w, h, None


def check_vp8l(d, p, size):
    """ VP8L (vesztesegmentes) kepadat: (szelesseg, magassag, hibauzenet vagy None) """
    if size < 5 or d[p] != 0x2F: return 0, 0, "VP8L: bad signature"
    v = int.from_bytes(d[p + 1:p + 5], 'little')
    w, h = (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
    if v >> 29: return w, h, "VP8L: bad version %d" % (v >> 29)
    z = d.find(WEBP_ZERO_RUN, p, p + size)
    if z >= 0: return w, h, "VP8L: zero bytes at %d inside the image data" % z
    return w, h, None


def testwebp(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py):
      WEBP_INFO;filenev;szelesseg x magassag;webp;keszites;modositas;forras (exif|xmp);;szerzo;cim;program;eszkoz;OK|BAD
    """
    meta = {}
    try:
        res = parse_webp(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        i = image_info(meta.get('exif'), meta.get('xmp'))
        print_info("WEBP", (fname, meta.get('dims', ""), "webp") + i[:3] + ("",) + i[3:] + (result(res),))
    return res


def parse_webp(d, debug, meta):

    def log(*args):
        if debug: print(*args)

    segs, err = parse_riff(d, b'WEBP', None, "WebP", log)
    if err:
        print("ERROR! WEBP: %s" % err)
        return 10
    chunks = segs[0].kids
    ids = [c.id for c in chunks]
    log("WEBP: %d bytes, chunks: %s" % (len(d), " ".join(i.decode('latin1').strip() for i in ids)))
    if not chunks:
        print("ERROR! WEBP: no chunks")
        return 10
    for c in chunks:
        if c.id == b'EXIF':
            b = d[c.data:c.data + c.size]
            meta['exif'] = tiff_meta(b[6:] if b[:6] == b'Exif\x00\x00' else b)
        elif c.id == b'XMP ':
            meta['xmp'] = xmp_meta(d[c.data:c.data + c.size])
    image = lambda c: (check_vp8 if c.id == b'VP8 ' else check_vp8l)(d, c.data, c.size)
    first = chunks[0]
    err = None
    if first.id in (b'VP8 ', b'VP8L'):
        w, h, err = image(first)
    elif first.id == b'VP8X':
        if first.size < 10:
            print("ERROR! WEBP: VP8X chunk too short")
            return 10
        q = first.data
        flags = d[q]
        w, h = int.from_bytes(d[q + 4:q + 7], 'little') + 1, int.from_bytes(d[q + 7:q + 10], 'little') + 1
        # a jelzobitek es a chunkok osszhangja (a hianyzo chunk adatvesztes, a felesleges csak iroi pontatlansag)
        for bit, cid, name in ((0x20, b'ICCP', "ICC profile"), (0x08, b'EXIF', "EXIF"), (0x04, b'XMP ', "XMP")):
            if flags & bit and cid not in ids: log("WARNING: VP8X says %s, but no %s chunk" % (name, cid.decode().strip()))
        if flags & 0x02:                                     # animacio: minden keret a vasznon belul, benne kepadat
            frames = [c for c in chunks if c.id == b'ANMF']
            if b'ANIM' not in ids or not frames: err = "animated, but no ANIM/ANMF chunks"
            for fr in frames:
                if err: break
                q = fr.data
                if fr.size < 16 + 8:
                    err = "ANMF chunk at %d too short" % fr.start
                    break
                fx, fy = 2 * int.from_bytes(d[q:q + 3], 'little'), 2 * int.from_bytes(d[q + 3:q + 6], 'little')
                fw, fh = int.from_bytes(d[q + 6:q + 9], 'little') + 1, int.from_bytes(d[q + 9:q + 12], 'little') + 1
                if fx + fw > w or fy + fh > h:
                    err = "ANMF frame at %d (%dx%d+%d+%d) outside of the canvas %dx%d" % (fr.start, fw, fh, fx, fy, w, h)
                    break
                e = parse_chunks(d, q + 16, q + fr.size, fr, "ANMF")   # a keret alchunkjai ugyanugy, mint a fo szinten
                if e: err = e; break
                img = [c for c in fr.kids if c.id in (b'VP8 ', b'VP8L')]
                if not img: err = "ANMF frame at %d without image data" % fr.start
                else: err = image(img[0])[2]
            log("WEBP: animation, %d frames" % len(frames))
        else:
            img = [c for c in chunks if c.id in (b'VP8 ', b'VP8L')]
            if not img: err = "no image data (VP8/VP8L chunk)"
            else:
                iw, ih, err = image(img[0])
                if not err and (iw, ih) != (w, h): err = "image size %dx%d differs from the canvas %dx%d" % (iw, ih, w, h)
            alph = [c for c in chunks if c.id == b'ALPH']
            if alph and not err:
                c = alph[0]
                if c.size < 1 or d[c.data] >> 6: err = "bad ALPH header"
                elif d[c.data] & 3 == 0 and c.size - 1 != w * h: err = "raw ALPH: %d bytes for %dx%d" % (c.size - 1, w, h)
                elif d[c.data] & 3 == 1 and d.find(WEBP_ZERO_RUN, c.data, c.data + c.size) >= 0: err = "zero bytes inside the compressed alpha data"
    else:
        print("ERROR! WEBP: unknown first chunk %r" % first.id)
        return 10
    meta['dims'] = "%dx%d" % (w, h)
    if err:
        print("ERROR! WEBP: %s" % err)
        return 10
    return 0



###############################################################################################################################
# WAV (RIFF WAVE, RF64): a RIFF es a chunkok merete (csonkolas), a fmt adatainak osszhangja, a felbeszakadt felvetel (a
# fejlecben 0 / regi hangadat meret, utana meg sok adat), ADPCM blokkfejlecek, az MP3-at tartalmazo WAV MP3 keretlanca.
# A PCM adatban a nulla a csend is lehet, ott a kinullazott szektor dekodolas nelkul nem derul ki.
# Metaadat: Broadcast WAV (bext: felveteli datum, ido, eszkoz), LIST INFO, ID3 chunk.
###############################################################################################################################

WAV_FORMATS = {1: "PCM", 2: "MS ADPCM", 3: "float", 6: "A-law", 7: "mu-law", 0x11: "IMA ADPCM", 0x31: "GSM", 0x50: "MPEG",
               0x55: "MP3", 0x161: "WMA", 0x2000: "AC3", 0xFFFE: "extensible"}


def wav_kind(d):
    return len(d) >= 12 and d[:4] in (b'RIFF', b'RF64') and d[8:12] == b'WAVE'


def testwav(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py):
      WAV_INFO;filenev;formatum (pl. PCM 16bit 44100Hz 2ch);wav;felvetel ideje;;forras (bext|info|id3);;eloado;cim;program;eszkoz;OK|BAD
    """
    meta = {}
    try:
        res = parse_wav(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        try: created, modified, src, author, title, prog, dev = avi_info(data, meta.get('segs', []), b'')
        except Exception: created, modified, src, author, title, prog, dev = None, None, "", "", "", "", ""
        b = meta.get('bext')
        if b and b.get('date'): created, src = b['date'], "bext"
        dev = (b or {}).get('originator') or dev
        id3 = meta.get('id3', {})
        author, title = author or id3.get('TPE1', ""), title or id3.get('TIT2', "")
        if (id3.get('TPE1') or id3.get('TIT2')) and not src: src = "id3"
        print_info("WAV", (fname, meta.get('fmt', ""), "wav", created, modified, src, "", author, title, prog, dev, result(res)))
    return res


def parse_wav(d, debug, meta):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    segs, err = parse_riff(d, b'WAVE', None, "WAV", log)
    if err and d[:4] == b'RIFF':
        # sok iro rossz RIFF meretet ir (pl. a fact chunk nelkul szamolja): ha a file meretevel minden chunk stimmel, csak figyelmeztetes
        segs2, err2 = parse_riff(d, b'WAVE', None, "WAV", log, riff_size=n - 8)
        if not err2:
            log("WARNING: RIFF size %d in header, file is %d bytes" % (unpack_from('<L', d, 4)[0] + 8, n))
            segs, err = segs2, None
    meta['segs'] = segs
    if err:
        print("ERROR! WAV: %s" % err)
        return 10
    chunks = segs[0].kids
    ids = [c.id for c in chunks]
    log("WAV: %s, %d bytes, chunks: %s" % (d[:4].decode(), n, " ".join(i.decode('latin1').strip() for i in ids)))
    fmt = next((c for c in chunks if c.id == b'fmt '), None)
    data = next((c for c in chunks if c.id == b'data'), None)
    for c in chunks:
        if c.id == b'bext' and c.size >= 346:              # Broadcast WAV: leiras, keszito, datum, ido
            b = d[c.data:c.data + c.size]
            # OriginationDate (10 karakter, yyyy-mm-dd; az elvalaszto barmi lehet), OriginationTime (8 karakter, hh:mm:ss)
            date = re.sub(r'\D', ':', b[320:330].decode('latin1'))
            time = re.sub(r'\D', ':', b[330:338].decode('latin1')).strip(':\x00 ') or "00:00:00"
            meta['bext'] = {'originator': b[256:288].split(b'\x00')[0].decode('latin1').strip(),
                            'date': iso_local(date + " " + time)}
        elif c.id in (b'id3 ', b'ID3 ') and d[c.data:c.data + 3] == b'ID3':
            from testmp3 import parse_id3v2
            m = {}
            parse_id3v2(bytes(d[c.data:c.data + c.size]), 0, m, log)
            meta['id3'] = m
    if not fmt or fmt.size < 14:
        print("ERROR! WAV: missing or short fmt chunk")
        return 10
    tag, ch, rate, avg, align = unpack_from('<HHLLH', d, fmt.data)
    bits = unpack_from('<H', d, fmt.data + 14)[0] if fmt.size >= 16 else 0
    real = tag
    if tag == 0xFFFE and fmt.size >= 40: real, = unpack_from('<H', d, fmt.data + 24)    # extensible: a SubFormat GUID eleje
    name = WAV_FORMATS.get(real, "format 0x%X" % real)
    meta['fmt'] = "%s %s%dHz %dch" % (name, "%dbit " % bits if bits else "", rate, ch)
    log("WAV: %s, block %d, %d bytes/s" % (meta['fmt'], align, avg))
    if not ch or not rate or not align:
        print("ERROR! WAV: bad fmt chunk (channels %d, rate %d, block align %d)" % (ch, rate, align))
        return 10
    if real in (1, 3, 6, 7):
        if align != ch * ((bits + 7) // 8) or avg != rate * align:
            log("WARNING: fmt: block align %d, %d bytes/s (expected %d, %d)" % (align, avg, ch * ((bits + 7) // 8), rate * ch * ((bits + 7) // 8)))
    if not data:
        print("ERROR! WAV: no data chunk")
        return 10
    if ids.index(b'data') < ids.index(b'fmt '): log("WARNING: data chunk before fmt")
    # felbeszakadt felvetel: a fejlec nem lett frissitve, a hangadat a megadott meretnel (gyakran 0) tovabb tart
    after = segs[0].data + segs[0].size - (data.data + data.size)
    tail = n - (segs[0].data + segs[0].size)
    if tail > max(4096, data.size // 10) and d[segs[0].data + segs[0].size:segs[0].data + segs[0].size + 4] != b'RIFF':
        print("ERROR! WAV: header says %d bytes of audio, %d more bytes after the RIFF (recording not finalized?)" % (data.size, tail))
        return 10
    if data.size % align: log("WARNING: data size %d is not a multiple of the block size %d" % (data.size, align))
    # ADPCM blokkfejlecek
    q, end = data.data, data.data + data.size
    bad = blocks = 0
    first = None
    if real == 0x11:                                       # IMA: csatornankent int16 minta, lepes index (0..88), 0 byte
        while q + 4 * ch <= end:
            for c in range(ch):
                if d[q + 4 * c + 2] > 88 or d[q + 4 * c + 3]:
                    bad += 1
                    if first is None: first = q
                    break
            blocks += 1
            q += align
    elif real == 2 and fmt.size >= 22:                     # MS ADPCM: csatornankent a predictor index < az egyutthatok szama
        ncoef, = unpack_from('<H', d, fmt.data + 20)
        while q + ch <= end:
            if any(d[q + c] >= ncoef for c in range(ch)):
                bad += 1
                if first is None: first = q
            blocks += 1
            q += align
    if bad:
        print("ERROR! WAV: %d of %d ADPCM blocks with bad header, first at %d" % (bad, blocks, first))
        return 10
    if blocks: log("WAV: %d ADPCM blocks checked" % blocks)
    if real == 0x55:                                       # MP3 a WAV-ban: a keretlanc ellenorzese
        from testmp3 import parse_mp3
        e = parse_mp3(bytes(d[data.data:data.data + data.size]), debug, {})
        if e: return 10
    return 0


###############################################################################################################################
# CorelDRAW (CDR) RIFF: a 3..X3 verziok maga a file, az X4+ verziok ZIP-jeben a content/root.dat (riffData.cdr) - ezt a
# testzip ellenorzi ugyanezzel. A chunk szerkezet, a 8+ verziok tomoritett LIST cmpr blokkjainak teljes zlib kitomoritese
# (Adler-32), es a kitomoritett chunkok bejarasa: ott a meret mezo index a blokk merettablajaba (mint a libcdr-ben).
###############################################################################################################################

def cdr_kind(d):
    return len(d) >= 16 and d[:4] == b'RIFF' and d[8:11] in (b'CDR', b'cdr')


def _cdr_indexed(u, p, end, table):
    """ a kitomoritett cmpr chunkjai: a meret mezo index a merettablaba. visszaad: hibauzenet vagy None """
    while p + 8 <= end:
        cid = u[p:p + 4]
        idx, = unpack_from('<L', u, p + 4)
        if idx >= len(table): return "chunk %r at %d: size index %d, table has %d entries" % (cid, p, idx, len(table))
        size = table[idx]
        if p + 8 + size > end: return "chunk %r at %d: size %d exceeds its list" % (cid, p, size)
        if cid == b'LIST' and u[p + 8:p + 12] not in OPAQUE_LISTS:
            e = _cdr_indexed(u, p + 12, p + 8 + size, table)
            if e: return e
        p += 8 + size + (size & 1)
    if p < end and u[p:end].strip(b'\x00'): return "%d bytes of garbage at the end of a list" % (end - p)
    return None


def check_cmpr(d, c):
    """ LIST cmpr: tomoritett meret, kitomoritett meret, merettabla meretek, utana ket "CPng" + zlib folyam """
    q, end = c.data + 4, c.data + c.size
    if q + 16 > end: return "cmpr block at %d too short" % c.start
    cs, us, bcs, bus = unpack_from('<4L', d, q)
    if q + 16 + cs + bcs != end: return "cmpr block at %d: sizes %d+%d do not match the list (%d)" % (c.start, cs, bcs, end - q - 16)
    out = []
    for a, n, un in ((q + 16, cs, us), (q + 16 + cs, bcs, bus)):
        if d[a:a + 4] != b'CPng': return "cmpr block at %d: no CPng header" % c.start
        try:
            z = zlib.decompressobj()
            u = z.decompress(d[a + 8:a + n])
        except zlib.error as e:
            return "cmpr block at %d: zlib: %s" % (c.start, e)
        if not z.eof or len(u) != un: return "cmpr block at %d: %d of %d bytes decompressed" % (c.start, len(u), un)
        out.append(u)
    table = unpack_from('<%dL' % (len(out[1]) // 4), out[1])
    return _cdr_indexed(out[0], 0, len(out[0]), table)


def testcdr(data, debug=False, fname=None):
    """
    visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    fname megadasa eseten kiir egy sort (grep -a -val CSV-be gyujtheto, lasd fileinfo.py). A regi (RIFF) CDR-ben nincs
    datum; az X4+ (ZIP) CDR-ek sora a testzip ZIP_INFO sora (tipus: cdr), benne a datumokkal.
      CDR_INFO;filenev;CorelDRAW verzio;cdr;;;;;;cim;;;OK|BAD
    """
    meta = {}
    try:
        res = parse_cdr(data, debug, meta)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        res = 100
    if fname is not None:
        info = meta.get('info', {})
        print_info("CDR", (fname, meta.get('ver', ""), "cdr", None, None, "", "", "", info.get(b'INAM', ""), "", "", result(res)))
    return res


def parse_cdr(d, debug, meta, label="CDR"):

    def log(*args):
        if debug: print(*args)

    form = bytes(d[8:12])
    segs, err = parse_riff(d, form, None, label, log)
    if err:
        print("ERROR! %s: %s" % (label, err))
        return 10
    seg = segs[0]
    # a verzio a form utolso karakterebol: CDR3..CDR9, CDRA = 10 ... CDRK = 20, az L kimaradt: CDRM = 21 (2019) ... (a vrsn
    # chunk az X6-tol 0xFFFF; a mintakon a ZIP-es CDR-ek XMP-jeben levo CoreVersion / ProductName alapjan ellenorizve)
    ch = form[3:4].upper()
    vn = int(ch) if ch.isdigit() else ord(ch) - 55 - (1 if ch >= b'M' else 0) if b'A' <= ch <= b'Z' else 0
    names = {13: "X3", 14: "X4", 15: "X5", 16: "X6", 17: "X7", 18: "X8"}
    meta['ver'] = "CorelDRAW %s" % (names.get(vn) or (str(1998 + vn) if vn >= 19 else str(vn))) if vn else form.decode('latin1')
    stack, cmprs = [seg], []
    while stack:
        c = stack.pop()
        stack += c.kids
        if c.form == b'cmpr': cmprs.append(c)
        elif c.form == b'INFO':
            meta['info'] = {k.id: bytes(d[k.data:k.data + k.size]).split(b'\x00')[0].decode('latin1').strip() for k in c.kids}
    log("%s: %s (%s), %d chunks, %d compressed blocks" % (label, meta['ver'], form.decode('latin1'), len(seg.kids), len(cmprs)))
    for c in sorted(cmprs, key=lambda c: c.start):
        e = check_cmpr(d, c)
        if e:
            print("ERROR! %s: %s" % (label, e))
            return 10
    return 0

if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "_AVI/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: d = f.read()
    res = (testwebp if webp_kind(d) else testwav if wav_kind(d) else testcdr if cdr_kind(d) else testavi)(d, debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res)
