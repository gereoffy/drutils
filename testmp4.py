#! /usr/bin/python3

# ISO Base Media File Format (ISOBMFF) ellenorzes: mp4, mov (QuickTime), m4v, m4a, 3gp, heic/heif, avif...
# Formatum leiras: ISO/IEC 14496-12, 14496-15 (AVC/HEVC a konteinerben), Apple QuickTime File Format.
#
# CRC nincs a formatumban, ezert a szerkezetet nezzuk: a boxok egymasba agyazasa, a kotelezo elemek, a mintatablak
# osszhangja es minden minta (videokocka, hangcsomag) helye a fileban. H.264/H.265 videonal a mintak NAL egysegekre
# bontasa is ellenorizve van (a hosszaknak pontosan ki kell adniuk a minta meretet).

import re
from struct import unpack_from

# boxok, amelyeknek gyerek boxai vannak (a tobbi level, annak csak a hatarait nezzuk)
CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'dinf', b'edts', b'udta', b'mvex', b'moof', b'traf',
              b'mfra', b'tref', b'meta', b'iprp', b'ipco', b'sinf', b'schi', b'gmhd', b'ilst', b'tapt', b'clip',
              b'matt', b'imap', b'rmra', b'rmda', b'wave', b'strk', b'strd', b'meco', b'mere', b'grpl', b'trgr'}
# NAL egysegen belul tilos (emulation prevention: a kodolo 00 00 03-mal escape-eli ezeket), kiveve a vegi nulla kitoltest
nal_forbidden_re = re.compile(b'\x00\x00[\x00-\x02]')
# tomoritetlen PCM hang kodekek (QuickTime): a mintameret a hang leirobol szamolhato
PCM_CODECS = {b'sowt', b'twos', b'raw ', b'lpcm', b'in24', b'in32', b'fl32', b'fl64', b'NONE'}
NAL_CODECS = {b'avc1': 'avc', b'avc3': 'avc', b'hvc1': 'hevc', b'hev1': 'hevc'}


class Box:
    __slots__ = ('type', 'start', 'data', 'end', 'children')
    def __init__(self, typ, start, data, end):
        self.type = typ
        self.start = start      # a box eleje (fejlec)
        self.data = data        # a box tartalmanak eleje
        self.end = end
        self.children = []
    def find(self, typ):
        for c in self.children:
            if c.type == typ: return c
        return None
    def findall(self, typ):
        return [c for c in self.children if c.type == typ]


def valid_type(t):
    return all(0x20 <= c <= 0x7E or c == 0xA9 for c in t)   # 0xA9: (c) a QuickTime metaadat boxokban


def parse_boxes(d, start, end, parent, log, depth=0):
    """ a [start, end) tartomanyt boxokra bontja. visszaad: hibauzenet vagy None """
    p = start
    while p < end:
        if end - p < 8:
            # QuickTime: a udta vegen lehet 4 byte-os 0 lezaro, ill. nulla kitoltes
            if not d[p:end].strip(b'\x00'): return None
            return "%d bytes of garbage at %d (in %s)" % (end - p, p, parent.type.decode('latin1'))
        size, typ = unpack_from('>L4s', d, p)
        hdr = 8
        if size == 1:
            if end - p < 16: return "truncated 64-bit box header at %d" % p
            size, = unpack_from('>Q', d, p + 8)
            hdr = 16
        elif size == 0:
            if depth == 0: size = end - p          # a file vegeig tart
            elif typ == b'\x00\x00\x00\x00' or not d[p:end].strip(b'\x00'): return None   # QuickTime lezaro
            else: return "zero size box %r at %d" % (typ, p)
        # az ilst gyerekeinek tipusa QuickTime-ban a keys tabla indexe (1, 2, ...), nem 4 betus kod
        if parent.type != b'ilst' and not valid_type(typ): return "bad box type %r at %d" % (typ, p)
        if size < hdr: return "box %s at %d: bad size %d" % (typ.decode('latin1'), p, size)
        if p + size > end:
            where = "file" if depth == 0 else parent.type.decode('latin1')
            return "box %s at %d: %d bytes, only %d left in %s (truncated?)" % (typ.decode('latin1'), p, size, end - p, where)
        box = Box(typ, p, p + hdr, p + size)
        parent.children.append(box)
        if typ in CONTAINERS:
            q = box.data
            # az ISO meta FullBox (4 byte version/flags a gyerekek elott), a QuickTime meta nem: ott rogton box jon
            if typ == b'meta' and box.end - q >= 12 and not valid_type(d[q + 4:q + 8]): q += 4
            err = parse_boxes(d, q, box.end, box, log, depth + 1)
            if err: return err
        p += size
    return None


###############################################################################################################################
# mintatablak
###############################################################################################################################

def full(d, box):
    """ FullBox: (version, flags, a tartalom eleje) """
    v = d[box.data]
    return v, int.from_bytes(d[box.data + 1:box.data + 4], 'big'), box.data + 4

def table(d, box, fmt, esize, n, q):
    if q + n * esize > box.end: raise ValueError("%s: %d entries do not fit in box" % (box.type.decode(), n))
    return unpack_from('>%d%s' % (n, fmt), d, q)


def nal_tail_ok(tail, codec):
    """
    a NAL vegen megengedett: csupa nulla kitoltes (trailing zero bytes / cabac_zero_words), ill. egyes kodolok egy
    Annex B inditokodot + rovid lezaro NAL egyseget (AUD, end of sequence/stream, filler) fuznek a szelet vegere
    """
    t = tail.lstrip(b'\x00')
    if not t: return True
    if t[0] != 1 or len(tail) - len(t) < 2 or len(t) > 4: return False
    if codec == 'avc': return len(t) >= 2 and t[1] & 0x1F in (9, 10, 11, 12)
    return len(t) >= 3 and (t[1] >> 1) & 0x3F in (35, 36, 37, 38)


def check_nal(d, a, size, nlen, codec):
    """ egy minta NAL egysegei: hossz + adat, a hosszaknak pontosan ki kell adniuk a mintat. visszaad: hibauzenet vagy None """
    p = a
    end = a + size
    while p < end:
        if p + nlen > end: return "NAL length field truncated"
        l = int.from_bytes(d[p:p + nlen], 'big')
        p += nlen
        if l == 0 or p + l > end: return "bad NAL length %d (%d bytes left)" % (l, end - p)
        h = d[p]
        if h & 0x80: return "forbidden_zero_bit set in NAL header"
        if codec == 'avc':
            if h & 0x1F == 0: return "NAL unit type 0"
        else:
            if l < 2 or d[p + 1] & 7 == 0: return "bad HEVC NAL header (TemporalId)"
        m = nal_forbidden_re.search(d, p, p + l)
        if m and not nal_tail_ok(d[m.start():p + l], codec):
            return "forbidden byte sequence %s inside NAL unit at %d" % (d[m.start():m.start() + 3].hex(), m.start())
        p += l
    return None


def check_track(d, trak, mdats, n, log, nal_check):
    """ egy track mintatablai es a mintak helye. visszaad: hibauzenet vagy None """
    tkhd = trak.find(b'tkhd')
    mdia = trak.find(b'mdia')
    if not tkhd: return "missing tkhd"
    if not mdia or not mdia.find(b'mdhd') or not mdia.find(b'hdlr'): return "missing mdia/mdhd/hdlr"
    hdlr = mdia.find(b'hdlr')
    handler = d[hdlr.data + 8:hdlr.data + 12].decode('latin1')
    minf = mdia.find(b'minf')
    stbl = minf.find(b'stbl') if minf else None
    if not stbl:
        # a QuickTime referencia/timecode trackeknek lehet, hogy nincs mintatablaja
        log("  track %s: no sample table" % handler)
        return None
    for t in (b'stsd', b'stts', b'stsc'):
        if not stbl.find(t): return "missing %s" % t.decode()
    stsz = stbl.find(b'stsz') or stbl.find(b'stz2')
    stco = stbl.find(b'stco') or stbl.find(b'co64')
    if not stsz or not stco: return "missing stsz/stco"
    # stsd: az elso minta leiras (kodek), avcC/hvcC-bol a NAL hossz mezo merete
    stsd = stbl.find(b'stsd')
    v, fl, q = full(d, stsd)
    nent, = unpack_from('>L', d, q)
    codec = d[q + 8:q + 12] if nent else b''
    nalcodec = NAL_CODECS.get(codec)
    nlen = None
    if nalcodec and nent:
        esize, = unpack_from('>L', d, q + 4)
        e = q + 4
        # VisualSampleEntry: 8 (box) + 78 byte, utana a gyerek boxok (avcC, hvcC, pasp, ...)
        c = e + 86
        while c + 8 <= e + esize:
            cs, ct = unpack_from('>L4s', d, c)
            if cs < 8: break
            if ct == b'avcC' and nalcodec == 'avc': nlen = (d[c + 12] & 3) + 1
            if ct == b'hvcC' and nalcodec == 'hevc': nlen = (d[c + 8 + 21] & 3) + 1
            c += cs
    # QuickTime PCM hang: az stsz 1 csatorna 1 mintajanak meretet adja, a valodi meret a hang leirobol jon
    pcm_size = None
    if codec in PCM_CODECS and nent:
        e = q + 4
        sver, = unpack_from('>H', d, e + 16)
        ch, bits = unpack_from('>HH', d, e + 24)
        if sver == 1:
            spp, bpp, bpf, bps = unpack_from('>4L', d, e + 36)
            if spp and bpf: pcm_size = bpf // spp if bpf % spp == 0 else None
        elif sver == 0 and ch and bits % 8 == 0:
            pcm_size = ch * bits // 8
    # kulso adat (data reference): a mintak nem ebben a fileban vannak
    external = False
    dref = minf.find(b'dinf').find(b'dref') if minf.find(b'dinf') else None
    if dref:
        v, fl, q = full(d, dref)
        cnt, = unpack_from('>L', d, q)
        if cnt:
            # az elso bejegyzes (url /alis box): meret, tipus, version, flags; flags&1: az adat ebben a fileban van
            ef = int.from_bytes(d[q + 13:q + 16], 'big')
            external = not (ef & 1)
    # stts: (darab, delta)
    v, fl, q = full(d, stbl.find(b'stts'))
    cnt, = unpack_from('>L', d, q)
    stts = table(d, stbl.find(b'stts'), 'L', 4, cnt * 2, q + 4)
    nsamples = sum(stts[0::2])
    # stsz / stz2
    v, fl, q = full(d, stsz)
    if stsz.type == b'stsz':
        ssize, scount = unpack_from('>LL', d, q)
        sizes = table(d, stsz, 'L', 4, scount, q + 8) if ssize == 0 else None
    else:
        fs = d[q + 3]
        scount, = unpack_from('>L', d, q + 4)
        if fs == 16: sizes = table(d, stsz, 'H', 2, scount, q + 8)
        elif fs == 8: sizes = table(d, stsz, 'B', 1, scount, q + 8)
        elif fs == 4:
            raw = d[q + 8:q + 8 + (scount + 1) // 2]
            sizes = [x for b in raw for x in (b >> 4, b & 15)][:scount]
        else: return "bad stz2 field size %d" % fs
        ssize = 0
    # stco / co64
    v, fl, q = full(d, stco)
    ccount, = unpack_from('>L', d, q)
    chunks = table(d, stco, 'L' if stco.type == b'stco' else 'Q', 4 if stco.type == b'stco' else 8, ccount, q + 4)
    # stsc: (elso chunk, minta/chunk, leiras index)
    stscb = stbl.find(b'stsc')
    v, fl, q = full(d, stscb)
    cnt, = unpack_from('>L', d, q)
    stsc = table(d, stscb, 'L', 4, cnt * 3, q + 4)
    log("  track %s %s: %d samples, %d chunks%s" % (handler, codec.decode('latin1'), scount, ccount, " (external data)" if external else ""))
    if nsamples != scount:
        # fix mintameretu (PCM) hangnal a QuickTime idotablaja elterhet, az stsc/stsz a mervado
        if not ssize: return "track %s: %d samples in stts, %d in stsz" % (handler, nsamples, scount)
        log("WARNING: track %s: %d samples in stts, %d in stsz" % (handler, nsamples, scount))
    if pcm_size and ssize: ssize = max(ssize, pcm_size)
    if scount and not stsc: return "track %s: empty stsc" % handler
    # chunkonkent a mintak szama
    per_chunk = []
    for i in range(0, len(stsc), 3):
        first, spc = stsc[i], stsc[i + 1]
        nxt = stsc[i + 3] if i + 3 < len(stsc) else ccount + 1
        if first < 1 or nxt <= first and i + 3 < len(stsc): return "track %s: bad stsc entry" % handler
        per_chunk.extend([spc] * (min(nxt, ccount + 1) - first))
    if sum(per_chunk) != scount: return "track %s: stsc maps %d samples, stsz has %d" % (handler, sum(per_chunk), scount)
    if external: return None
    # minden minta a fileban es egy mdat boxon belul
    s = 0
    mi = 0
    nalbad = 0
    first_nalerr = None
    for ci, off in enumerate(chunks):
        k = per_chunk[ci]
        csize = ssize * k if ssize else sum(sizes[s:s + k])
        if off + csize > n: return "track %s: chunk #%d (%d+%d) outside of file (%d): truncated?" % (handler, ci, off, csize, n)
        if not any(a <= off and off + csize <= b for a, b in mdats):
            return "track %s: chunk #%d (%d+%d) not inside an mdat box" % (handler, ci, off, csize)
        if nal_check and nlen and not ssize:
            a = off
            for j in range(s, s + k):
                err = check_nal(d, a, sizes[j], nlen, nalcodec)
                if err:
                    nalbad += 1
                    if first_nalerr is None: first_nalerr = "sample #%d at %d: %s" % (j, a, err)
                a += sizes[j]
        s += k
    if nalbad: return "track %s: %d of %d video samples bad, first: %s" % (handler, nalbad, scount, first_nalerr)
    return None


def check_fragments(d, root, n, log):
    """ toredezett MP4: moof/traf/trun mintai a fileban legyenek. visszaad: hibauzenet vagy None """
    trex = {}
    moov = root.find(b'moov')
    if moov and moov.find(b'mvex'):
        for t in moov.find(b'mvex').findall(b'trex'):
            v, fl, q = full(d, t)
            tid, sdi, dur, size, flags = unpack_from('>5L', d, q)
            trex[tid] = size
    nfrag = 0
    for moof in root.findall(b'moof'):
        nfrag += 1
        for traf in moof.findall(b'traf'):
            tfhd = traf.find(b'tfhd')
            if not tfhd: return "fragment at %d: missing tfhd" % moof.start
            v, fl, q = full(d, tfhd)
            tid, = unpack_from('>L', d, q)
            q += 4
            base = moof.start
            if fl & 0x1:
                base, = unpack_from('>Q', d, q)
                q += 8
            if fl & 0x2: q += 4
            if fl & 0x8: q += 4
            dsize = trex.get(tid, 0)
            if fl & 0x10: dsize, = unpack_from('>L', d, q)
            for trun in traf.findall(b'trun'):
                v, tfl, q = full(d, trun)
                cnt, = unpack_from('>L', d, q)
                q += 4
                off = base
                if tfl & 0x1:
                    off = base + unpack_from('>l', d, q)[0]
                    q += 4
                if tfl & 0x4: q += 4
                fields = [(0x100, 'dur'), (0x200, 'size'), (0x400, 'flags'), (0x800, 'cto')]
                esize = 4 * sum(1 for f, _ in fields if tfl & f)
                if q + cnt * esize > trun.end: return "fragment at %d: trun entries do not fit" % moof.start
                total = 0
                if tfl & 0x200:
                    si = sum(1 for f, _ in fields[:1] if tfl & f)
                    for i in range(cnt): total += unpack_from('>L', d, q + i * esize + si * 4)[0]
                else:
                    total = cnt * dsize
                if off + total > n: return "fragment at %d: sample data (%d+%d) outside of file (%d): truncated?" % (moof.start, off, total, n)
    log("MP4: %d fragments" % nfrag)
    return None


def check_items(d, meta, n, log, nal_check=True):
    """
    HEIF/AVIF: az iloc elemek adata a fileban legyen, a pitm elem letezzen, a HEVC/AVC kepelemek (pl. az iPhone
    kepek csempei) NAL egysegekre bonthatok legyenek. visszaad: hibauzenet vagy None
    """
    iloc = meta.find(b'iloc')
    if not iloc: return "meta without iloc"
    v, fl, q = full(d, iloc)
    osz, lsz = d[q] >> 4, d[q] & 15
    bsz, isz = d[q + 1] >> 4, (d[q + 1] & 15) if v in (1, 2) else 0
    q += 2
    if v < 2:
        cnt, = unpack_from('>H', d, q)
        q += 2
    else:
        cnt, = unpack_from('>L', d, q)
        q += 4
    def rd(size):
        nonlocal q
        x = int.from_bytes(d[q:q + size], 'big')
        q += size
        return x
    extents = {}
    for i in range(cnt):
        iid = rd(2 if v < 2 else 4)
        method = rd(2) & 15 if v in (1, 2) else 0
        rd(2)                       # data reference index
        base = rd(bsz)
        ne = rd(2)
        ext = []
        for e in range(ne):
            if isz: rd(isz)
            eo = rd(osz)
            el = rd(lsz)
            if method == 0 and base + eo + el > n: return "item %d: extent (%d+%d) outside of file (%d): truncated?" % (iid, base + eo, el, n)
            ext.append((base + eo, el))
        extents[iid] = ext if method == 0 else None
        if q > iloc.end: return "iloc entries do not fit in box"
    pitm = meta.find(b'pitm')
    if pitm:
        v, fl, q = full(d, pitm)
        pid = unpack_from('>H' if v == 0 else '>L', d, q)[0]
        if pid not in extents: return "primary item %d has no location" % pid
    # elem tipusok (iinf/infe) es a NAL hossz mezo merete (ipco: hvcC/avcC)
    types = {}
    iinf = meta.find(b'iinf')
    if iinf:
        v, fl, q = full(d, iinf)
        parse_boxes(d, q + (2 if v == 0 else 4), iinf.end, iinf, log, 2)
        for infe in iinf.findall(b'infe'):
            v, fl, q = full(d, infe)
            if v >= 2:
                iid = unpack_from('>H' if v == 2 else '>L', d, q)[0]
                q += 2 if v == 2 else 4
                types[iid] = d[q + 2:q + 6]
    nlen = {}
    iprp = meta.find(b'iprp')
    ipco = iprp.find(b'ipco') if iprp else None
    if ipco:
        for c in ipco.children:
            if c.type == b'hvcC' and 'hevc' not in nlen: nlen['hevc'] = (d[c.data + 21] & 3) + 1
            if c.type == b'avcC' and 'avc' not in nlen: nlen['avc'] = (d[c.data + 4] & 3) + 1
    nitems = 0
    if nal_check:
        for iid, ext in extents.items():
            codec = NAL_CODECS.get(types.get(iid))
            if not ext or codec not in nlen: continue
            data = b''.join(d[a:a + l] for a, l in ext)
            err = check_nal(data, 0, len(data), nlen[codec], codec)
            if err: return "item %d (%s): %s" % (iid, types[iid].decode('latin1'), err)
            nitems += 1
    log("MP4: %d items, %d image items NAL-checked" % (cnt, nitems))
    return None


###############################################################################################################################


HEIF_BRANDS = {b'heic', b'heix', b'hevc', b'hevx', b'heim', b'heis', b'mif1', b'msf1', b'avif', b'avis'}
TOP_LEVEL = {b'ftyp', b'moov', b'mdat', b'wide', b'free', b'skip', b'pnot', b'moof', b'styp', b'sidx'}

def mp4_kind(d):
    """ felismeres: None, ha nem ISOBMFF, kulonben 'heic' (kep), 'mov' (QuickTime) vagy 'mp4' """
    size = int.from_bytes(d[0:4], 'big')
    if len(d) < 12 or d[4:8] not in TOP_LEVEL or (size not in (0, 1) and size < 8): return None
    if d[4:8] == b'ftyp':
        brand = d[8:12]
        if brand in HEIF_BRANDS: return 'heic'
        return 'mov' if brand == b'qt  ' else 'mp4'
    return 'mov' if d[4:8] in (b'moov', b'mdat', b'wide', b'pnot') else 'mp4'


def testmp4(data, debug=False, nal_check=True):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_mp4(data, debug, nal_check)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_mp4(d, debug, nal_check):

    def log(*args):
        if debug: print(*args)

    n = len(d)
    root = Box(b'root', 0, 0, n)
    # a file vegi nulla kitoltest (visszaallitas utan gyakori) levagjuk, figyelmeztetunk
    end = n
    err = parse_boxes(d, 0, end, root, log)
    if err:
        body = d.rstrip(b'\x00')
        if len(body) < n and not parse_boxes(d, 0, len(body), Box(b'root', 0, 0, len(body)), log):
            log("WARNING: %d zero bytes at end of file" % (n - len(body)))
            root = Box(b'root', 0, 0, len(body))
            parse_boxes(d, 0, len(body), root, log)
        else:
            print("ERROR! MP4: %s" % err)
            return 10
    types = [b.type for b in root.children]
    log("MP4: top level boxes: %s" % " ".join(t.decode('latin1') for t in types))
    ftyp = root.find(b'ftyp')
    if ftyp: log("MP4: brand %s" % d[ftyp.data:ftyp.data + 4].decode('latin1'))
    mdats = [(b.data, b.end) for b in root.children if b.type == b'mdat']
    moov = root.find(b'moov')
    meta = root.find(b'meta')
    fragmented = b'moof' in types
    if meta and meta.find(b'iloc'):     # HEIF/AVIF kep
        err = check_items(d, meta, n, log, nal_check)
        if err:
            print("ERROR! MP4: %s" % err)
            return 10
        return 0
    if not moov and not fragmented:
        print("ERROR! MP4: missing moov box")
        return 10
    if moov:
        if not moov.find(b'mvhd'):
            print("ERROR! MP4: missing mvhd")
            return 10
        traks = moov.findall(b'trak')
        log("MP4: %d tracks" % len(traks))
        for trak in traks:
            try:
                err = check_track(d, trak, mdats, n, log, nal_check)
            except (ValueError, IndexError) as e:
                err = str(e)
            if err:
                print("ERROR! MP4: %s" % err)
                return 10
    if fragmented:
        err = check_fragments(d, root, n, log)
        if err:
            print("ERROR! MP4: %s" % err)
            return 10
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "mov/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testmp4(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
