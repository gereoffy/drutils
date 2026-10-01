#! /usr/bin/python3

# AVI (RIFF) ellenorzes: a chunk szerkezet, az index (idx1, OpenDML indx/ix##) minden bejegyzese egy ervenyes chunkra
# mutat-e, es a felvetel datuma (IDIT, LIST INFO, Fuji strd EXIF). A kodekeket nem dekodoljuk (lassu es a nagy fileoknal
# ertelmetlen), csak a videokockak elejet (MJPEG: FFD8, MPEG-4/H.264: 00 00 01), es hogy nincs-e bennuk nulla blokk.
# Formatum leiras: Microsoft AVI RIFF File Reference, OpenDML AVI File Format Extensions 1.02.

import datetime
import re
from struct import unpack_from

from fileinfo import print_info, result, iso_local, tiff_meta, device, plausible, date_source

fourcc_re = re.compile(rb'[\x20-\x7e]{4}$')
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


def parse_chunks(d, start, end, parent, where):
    """ a [start, end) tartomany chunkjai (a LIST-ek rekurzivan). visszaad: hibauzenet vagy None """
    p = start
    while p < end:
        if end - p < 8:
            if not d[p:end].strip(b'\x00'): return None   # nulla kitoltes a lista vegen
            return "%d bytes of garbage at %d (in %s)" % (end - p, p, where)
        cid = d[p:p + 4]
        size, = unpack_from('<L', d, p + 4)
        if not fourcc_re.match(cid):
            if not d[p:end].strip(b'\x00'): return None
            return "bad chunk id %r at %d (in %s)" % (cid, p, where)
        if p + 8 + size > end: return "chunk %s at %d: size %d, only %d bytes left in %s (truncated?)" % (cid.decode('latin1'), p, size, end - p - 8, where)
        if cid in (b'LIST', b'RIFF'):
            form = d[p + 8:p + 12]
            if size < 4 or not fourcc_re.match(form): return "bad %s at %d (form %r)" % (cid.decode(), p, form)
            c = Chunk(cid, p, size, form)
            parent.kids.append(c)
            err = parse_chunks(d, p + 12, p + 8 + size, c, form.decode('latin1').strip())
            if err: return err
        else:
            parent.kids.append(Chunk(cid, p, size))
        p += 8 + size + (size & 1)
    return None


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
            elif c.id[:1] == b'I':
                info.setdefault(c.id, body.split(b'\x00')[0].decode('latin1', 'replace').strip())
    if not created and info.get(b'ICRD'): created, src_c = _avi_date(info[b'ICRD'].encode('latin1')), "info"
    return (created, modified, date_source(created, modified, src_c, src_m), info.get(b'IART', ""), info.get(b'INAM', ""),
            info.get(b'ISFT', ""), device(make, model))


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
    root = Chunk(b'file', 0, n)
    segs = meta['segs'] = []
    p = 0
    while p + 12 <= n and d[p:p + 4] == b'RIFF':
        size, = unpack_from('<L', d, p + 4)
        form = d[p + 8:p + 12]
        if form not in ((b'AVI ',) if p == 0 else (b'AVIX',)): break
        if p + 8 + size > n:
            print("ERROR! AVI: RIFF %s at %d: size %d, only %d bytes in file (truncated)" % (form.decode(), p, size, n - p - 8))
            return 10
        seg = Chunk(b'RIFF', p, size, form)
        segs.append(seg)
        err = parse_chunks(d, p + 12, p + 8 + size, seg, form.decode().strip())
        if err:
            print("ERROR! AVI: %s" % err)
            return 10
        p += 8 + size + (size & 1)
    if not segs:
        print("ERROR! AVI: not a RIFF AVI file")
        return 10
    if p < n:
        rest = d[p:]
        if not rest.strip(b'\x00'): log("WARNING: %d zero bytes after the end of AVI" % (n - p))
        else: log("WARNING: %d bytes of garbage after the end of AVI (recovered file?)" % (n - p))

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


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "_AVI/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testavi(f.read(), debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res)
