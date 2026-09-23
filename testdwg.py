#! /usr/bin/python3

# AutoCAD DWG integritas ellenorzes kulso konyvtar nelkul. Az objektumokat nem ertelmezzuk, csak a file szerkezetet
# es a formatum sajat ellenorzo osszegeit (CRC16, CRC32, Adler-32, Reed-Solomon paritas) nezzuk.
# Formatum leiras: Open Design Alliance "Open Design Specification for .dwg files", ill. libredwg.
#
#   R10, R11/R12  (AC1006, AC1009): tablak, entitasok hosszmezoi, R11/R12-ben sentinelek es entitasonkenti CRC16
#   R13 - R2000   (AC1012, AC1014, AC1015): file header CRC, szakaszok CRC-je es sentinelei, objektumonkenti CRC16
#   R2004+        (AC1018, AC1024, AC1027, AC1032): titkositott file header CRC32, page map/section map (LZ77),
#                 minden adat oldal fejlec- es adat ellenorzo osszege (Adler-32)
#   R2007         (AC1021): Reed-Solomon kodolt file header, page map/section map, adat oldalak RS paritasa

from struct import unpack_from, pack
import zlib


###############################################################################################################################
# CRC16 (0xA001 polinom, a DWG a 0xC0C1 kezdoerteket hasznalja)
###############################################################################################################################

_crc16_table = []
for _i in range(256):
    _c = _i
    for _ in range(8): _c = (_c >> 1) ^ 0xA001 if _c & 1 else _c >> 1
    _crc16_table.append(_c)

def crc16(data, crc):
    t = _crc16_table
    for b in data: crc = (crc >> 8) ^ t[(crc ^ b) & 0xFF]
    return crc


###############################################################################################################################
# R10 - R12
###############################################################################################################################

# R11/R12 sentinelek (a tablak, az entitas- es block szakasz elott/utan)
r11_sentinels = {
    "BLOCK": ("dbefb3f0c73e6da6c9b6245c4c6f32cb", "24104c0f38c192593649dba3b390cd34"),
    "LAYER": ("0ec4646fbb1dd38b0049c2ef18ea6ffb", "f13b9b9044e22c74ffb63d10e7159004"),
    "STYLE": ("e23ec182439f617750abc76696000618", "1dc13e7dbc609e88af54389969fff9e7"),
    "LTYPE": ("ac901aca1cbd951516164c14ce1888af", "536fe535e3426aeae9e9b3eb31e77750"),
    "VIEW":  ("c13caa5668f4b41e4b74f408424dbfa5", "3ec355a9970b4be1b48b0bf7bdb2405a"),
    "entities": ("c46e6854f86e3330633ec1852adc9401", "3b9197ab0791cccf9cc13e7ad5236bfe"),
    "blocks":   ("722b7dec3e8c886c7a720afdc86c8426", "8dd48213c1737793858df50237937bd9"),
}

def check_r12(d, ver, log):
    """ visszaad: hibauzenet vagy None """
    r11 = ver == "AC1009"   # az R10-ben meg nincs CRC es sentinel
    n = len(d)
    es, ee, bs, bsz, xs, xsz = unpack_from('<llllll', d, 0x14)
    be = bs + (bsz & 0x3FFFFFFF)
    for name, a, b in (("entities", es, ee), ("blocks", bs, be)):
        if a == b and a >= n:   # ures szakasz a file vege utani cimmel (pl. egy 1992-es R10 file): tartalom nem veszett el
            log("WARNING: empty %s section at %d, after end of file (%d)" % (name, a, n))
            continue
        if a < 0x2C or b < a or b > n: return "%s section %d..%d outside of file (%d)" % (name, a, b, n)
    def sentinels(name, a, b):
        if not r11: return None
        s1, s2 = r11_sentinels[name]
        if d[a - 16:a] != bytes.fromhex(s1): return "%s: bad start sentinel" % name
        if d[b:b + 16] != bytes.fromhex(s2): return "%s: bad end sentinel" % name
        return None
    # tablak: bejegyzes meret, darabszam, flag, cim
    for i, name in enumerate(["BLOCK", "LAYER", "STYLE", "LTYPE", "VIEW"]):
        size, num, flags, addr = unpack_from('<hhhl', d, 0x2C + 10 * i)
        end = addr + size * num
        if num == 0 and addr >= n:
            log("WARNING: empty %s table at %d, after end of file (%d)" % (name, addr, n))
            continue
        if size < 0 or num < 0 or addr < 0 or end > n: return "%s table (%d x %d at %d) outside of file" % (name, num, size, addr)
        err = sentinels(name, addr, end)
        if err: return err
        if r11:
            for k in range(num):
                e = d[addr + k * size:addr + (k + 1) * size]
                if crc16(e[:-2], 0xC0C1) != unpack_from('<H', e, size - 2)[0]: return "%s table entry #%d: bad CRC" % (name, k)
        log("DWG: %s table: %d entries" % (name, num))
    # entitasok: tipus, flag, hossz (R11+: a vegen CRC16)
    for name, a, b in (("entities", es, ee), ("blocks", bs, be)):
        if a == b and a >= n: continue
        err = sentinels(name, a, b)
        if err: return err
        p = a
        cnt = 0
        while p < b:
            ln, = unpack_from('<h', d, p + 2)
            if ln < 4 or p + ln > b: return "%s: bad entity length %d at %d" % (name, ln, p)
            if r11 and crc16(d[p:p + ln - 2], 0xC0C1) != unpack_from('<H', d, p + ln - 2)[0]: return "%s: bad CRC of entity at %d" % (name, p)
            p += ln
            cnt += 1
        log("DWG: %s: %d entities" % (name, cnt))
    return None


###############################################################################################################################
# R13 - R2000
###############################################################################################################################

S_FILEHDR = bytes.fromhex('95A04E2899821AE55E41E05F9D3A4D00')
S_HEADER = (bytes.fromhex('CF7B1F23FDDE38A95F7C68B84E6D335F'), bytes.fromhex('3084E0DC0221C756A0839747B192CCA0'))
S_CLASSES = (bytes.fromhex('8DA1C4B8C4A9F8C5C0DCF45FE7CFB68A'), bytes.fromhex('725E3B473B56073A3F230BA018304975'))
# a file header CRC-jet a szakasz lokator rekordok szamatol fuggo ertekkel kell XOR-olni
filehdr_xor = {3: 0xA598, 4: 0x8101, 5: 0x3CC4, 6: 0x8461}

def _mc(d, p):
    """ modular char (elojeles) """
    v = 0
    sh = 0
    while True:
        b = d[p]
        p += 1
        if b & 0x80:
            v |= (b & 0x7F) << sh
            sh += 7
        else:
            v |= (b & 0x3F) << sh
            return (-v if b & 0x40 else v), p

def _ms(d, p):
    """ modular short (elojel nelkuli) """
    v = 0
    sh = 0
    while True:
        w, = unpack_from('<H', d, p)
        p += 2
        if w & 0x8000:
            v |= (w & 0x7FFF) << sh
            sh += 15
        else:
            return v | (w << sh), p

def check_r2000(d, ver, log):
    n = len(d)
    nrec, = unpack_from('<l', d, 0x15)
    if nrec < 3 or nrec > 6: return "bad number of section locators %d" % nrec
    end = 0x19 + 9 * nrec
    recs = {}
    for i in range(nrec):
        no, seek, size = unpack_from('<Bll', d, 0x19 + 9 * i)
        if seek < 0 or size < 0 or seek + size > n: return "section locator #%d (%d+%d) outside of file (%d)" % (no, seek, size, n)
        recs[no] = (seek, size)
    if (crc16(d[:end], 0) ^ filehdr_xor[nrec]) != unpack_from('<H', d, end)[0]: return "bad file header CRC"
    if d[end + 2:end + 18] != S_FILEHDR: return "bad file header sentinel"
    # header valtozok es classes: sentinel, meret, adat, CRC, sentinel
    for no, name, (s1, s2) in ((0, "header", S_HEADER), (1, "classes", S_CLASSES)):
        if no not in recs: return "missing %s section" % name
        seek, size = recs[no]
        if d[seek:seek + 16] != s1: return "%s: bad start sentinel" % name
        sz, = unpack_from('<l', d, seek + 16)
        if sz < 0 or seek + 22 + sz + 16 > n: return "%s: bad size %d" % (name, sz)
        if crc16(d[seek + 16:seek + 20 + sz], 0xC0C1) != unpack_from('<H', d, seek + 20 + sz)[0]: return "%s: bad CRC" % name
        if d[seek + 22 + sz:seek + 38 + sz] != s2: return "%s: bad end sentinel" % name
    # object map: max. 2032 byte-os darabok (big endian meret + adat + CRC), benne handle/offset parok,
    # minden objektum: modular short meret + adat + CRC16
    if 2 not in recs: return "missing object map"
    p, size = recs[2]
    omap_end = p + size
    objs = 0
    while True:
        s, = unpack_from('>H', d, p)
        if s < 2 or p + s + 2 > omap_end: return "object map: bad section size %d at %d" % (s, p)
        if crc16(d[p:p + s], 0xC0C1) != unpack_from('>H', d, p + s)[0]: return "object map: bad CRC at %d" % p
        if s == 2: break
        q = p + 2
        off = 0
        while q < p + s:
            dh, q = _mc(d, q)
            do, q = _mc(d, q)
            off += do
            if off < 0 or off >= n: return "object map: object offset %d outside of file" % off
            osz, op = _ms(d, off)
            if op + osz + 2 > n: return "object at %d: size %d outside of file" % (off, osz)
            if crc16(d[off:op + osz], 0xC0C1) != unpack_from('<H', d, op + osz)[0]: return "object at %d: bad CRC" % off
            objs += 1
        p += s + 2
    log("DWG: %d objects" % objs)
    return None


###############################################################################################################################
# R2004+ (AC1018, AC1024, AC1027, AC1032)
###############################################################################################################################

def _xorkey(n):
    r = 1
    out = bytearray()
    for i in range(n):
        r = (r * 0x343fd + 0x269ec3) & 0xFFFFFFFF
        out.append((r >> 16) & 0xFF)
    return bytes(out)

R2004_HDR_KEY = _xorkey(0x6C)

def decompress_r2004(src, dsize):
    """ DWG R2004 LZ77 kitomorites (a rendszer oldalakhoz) """
    p = 0
    out = bytearray()
    def byte():
        nonlocal p
        b = src[p]
        p += 1
        return b
    def literal_length():
        b = byte()
        if 1 <= b <= 0x0F: return b + 3, 0
        if b == 0:
            t = 0x0F
            while True:
                b = byte()
                if b: return t + b + 3, 0
                t += 0xFF
        return 0, b            # nem literal, hanem a kovetkezo opcode
    def long_offset():
        b = byte()
        if b: return b
        t = 0xFF
        while True:
            b = byte()
            if b: return t + b
            t += 0xFF
    def two_byte():
        a = byte()
        b = byte()
        return (a >> 2) | (b << 6), a & 3
    lit, op = literal_length()
    out += src[p:p + lit]
    p += lit
    op = 0
    while p < len(src):
        if op == 0: op = byte()
        if op >= 0x40:
            cb = ((op & 0xF0) >> 4) - 1
            o2 = byte()
            co = (o2 << 2) | ((op & 0x0C) >> 2)
            if op & 3: lit, op = op & 3, 0
            else: lit, op = literal_length()
        elif op >= 0x20:
            cb = op - 0x1E if op > 0x20 else long_offset() + 0x21
            co, lit = two_byte()
            if lit: op = 0
            else: lit, op = literal_length()
        elif op == 0x11:
            break
        elif op >= 0x10:
            cb = (op & 7) + 2
            if cb == 2: cb = long_offset() + 9
            co, lit = two_byte()
            co += ((op & 8) << 11) + 0x3FFF
            if lit: op = 0
            else: lit, op = literal_length()
        else:
            raise ValueError("bad opcode 0x%X" % op)
        s = len(out) - co - 1
        if s < 0: raise ValueError("bad back reference")
        for i in range(cb): out.append(out[s + i])
        out += src[p:p + lit]
        p += lit
        if len(out) > dsize: raise ValueError("decompressed data too long")
    return bytes(out)

def _r2004_system_page(d, a, typ):
    if a + 20 > len(d): raise ValueError("system page at %d outside of file" % a)
    t, ds, cs, ct, ck = unpack_from('<5L', d, a)
    if t != typ: raise ValueError("bad system page type 0x%08X at %d" % (t, a))
    data = d[a + 20:a + 20 + cs]
    if len(data) != cs: raise ValueError("system page at %d truncated" % a)
    if zlib.adler32(data, zlib.adler32(pack('<5L', t, ds, cs, ct, 0), 0)) != ck: raise ValueError("system page at %d: bad checksum" % a)
    u = decompress_r2004(data, ds) if ct == 2 else data
    if len(u) != ds: raise ValueError("system page at %d: decompressed %d of %d bytes" % (a, len(u), ds))
    return u

def check_r2004(d, ver, log):
    n = len(d)
    h = bytes(x ^ y for x, y in zip(d[0x80:0x80 + 0x6C], R2004_HDR_KEY))
    if len(h) < 0x6C or h[:12] != b'AcFssFcAJMB\x00': return "bad encrypted file header"
    if zlib.crc32(h[:0x68] + b'\0\0\0\0') != unpack_from('<L', h, 0x68)[0]: return "bad file header CRC32"
    lastid, = unpack_from('<L', h, 0x28)
    lastend, = unpack_from('<Q', h, 0x2C)
    pmaddr, = unpack_from('<Q', h, 0x54)
    smid, = unpack_from('<L', h, 0x5C)
    try:
        pm = _r2004_system_page(d, pmaddr + 0x100, 0x41630E3B)
        # page map: (oldal szam, meret) parok, a negativ szam hezag (+4 int32)
        pages = {}
        addr = 0x100
        q = 0
        last = None
        while q + 8 <= len(pm):
            num, size = unpack_from('<lL', pm, q)
            q += 8
            if num < 0: q += 16
            else: pages[num] = (addr, size)
            last = num
            addr += size
        if addr != lastend + 0x100 or last != lastid: return "page map does not match file header"
        if smid not in pages: return "section map page %d missing from page map" % smid
        sm = _r2004_system_page(d, pages[smid][0], 0x4163003B)
    except (ValueError, IndexError) as e:
        return str(e)
    # section map: szakasz leirasok, szakaszonkent az oldalak listaja
    nsec, = unpack_from('<L', sm, 0)
    q = 20
    npages = 0
    for i in range(nsec):
        size, pc, maxd, unk, comp, sid, enc = unpack_from('<QLLLLLL', sm, q)
        name = sm[q + 32:q + 96].split(b'\0')[0].decode('latin1')
        q += 96
        for j in range(pc):
            pn, dsz, so = unpack_from('<LLQ', sm, q)
            q += 16
            if pn not in pages: return "section %s: page %d missing from page map" % (name, pn)
            a = pages[pn][0]
            if a + 32 > n: return "section %s: page %d at %d outside of file" % (name, pn, a)
            m = 0x4164536B ^ a
            ph = [v ^ m for v in unpack_from('<8L', d, a)]
            if ph[0] != 0x4163043B or ph[1] != sid: return "section %s: bad page header at %d" % (name, a)
            if a + 32 + ph[2] > n: return "section %s: page at %d truncated" % (name, a)
            if zlib.adler32(d[a + 32:a + 32 + ph[2]], 0) != ph[7]: return "section %s: bad data checksum of page at %d" % (name, a)
            if zlib.adler32(pack('<8L', *(ph[:6] + [0, ph[7]])), ph[7]) != ph[6]: return "section %s: bad header checksum of page at %d" % (name, a)
            npages += 1
        log("DWG: section %s: %d pages" % (name, pc))
    log("DWG: %d sections, %d data pages" % (nsec, npages))
    return None


###############################################################################################################################
# R2007 (AC1021): Reed-Solomon kodolt oldalak, sajat LZ77 valtozat
###############################################################################################################################

def _gf_tables(prim):
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100: x ^= prim
    for i in range(255, 512): exp[i] = exp[i - 255]
    return exp, log

def _rs_parity_func(prim, nsym):
    """ RS(255, 255-nsym) paritas szamito, az elso gyok alfa^1. A kodszo "forditott" byte sorrendu. """
    exp, log = _gf_tables(prim)
    g = [1]
    for i in range(nsym):
        r = exp[i + 1]
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            if c: ng[j + 1] ^= exp[log[c] + log[r]]
        g = ng
    table = []
    for f in range(256):
        v = 0
        for j in range(nsym):
            c = g[j + 1]
            v = (v << 8) | (exp[log[f] + log[c]] if f and c else 0)
        table.append(v)
    mask = (1 << (8 * nsym)) - 1
    shift = 8 * nsym - 8
    def parity(msg):
        r = 0
        for m in msg: r = ((r << 8) & mask) ^ table[(r >> shift) ^ m]
        return r.to_bytes(nsym, 'big')
    return parity

_rs_system = None   # RS(255,239), 0x169: file header es rendszer oldalak
_rs_data = None     # RS(255,251), 0x11D: adat oldalak

def rs_check(buf, nblocks, k, parity):
    """ nblocks db osszefesult 255 byte-os kodszo. visszaad: (adat, hibas blokkok szama) """
    data = bytearray()
    bad = 0
    for j in range(nblocks):
        cw = buf[j:nblocks * 255:nblocks]
        if len(cw) != 255 or parity(cw[:k][::-1]) != cw[k:255][::-1]: bad += 1
        data += cw[:k]
    return bytes(data), bad

def _copy_literal(src, s, n):
    """ az R2007 kitomorites literaljai sajatos byte sorrendben vannak (libredwg copy_bytes) """
    out = bytearray()
    while n >= 32:
        out += src[s + 24:s + 32] + src[s + 16:s + 24] + src[s + 8:s + 16] + src[s:s + 8]
        s += 32
        n -= 32
    b = src[s:s + n]
    def c2(i): return bytes([b[i + 1], b[i]])
    def c3(i): return bytes([b[i + 2], b[i + 1], b[i]])
    def c16(i): return b[i + 8:i + 16] + b[i:i + 8]
    tail = {0: lambda: b'', 1: lambda: b[0:1], 2: lambda: c2(0), 3: lambda: c3(0), 4: lambda: b[0:4], 5: lambda: b[4:5] + b[0:4],
        6: lambda: b[5:6] + b[1:5] + b[0:1], 7: lambda: c2(5) + b[1:5] + b[0:1], 8: lambda: b[0:8], 9: lambda: b[8:9] + b[0:8],
        10: lambda: b[9:10] + b[1:9] + b[0:1], 11: lambda: c2(9) + b[1:9] + b[0:1], 12: lambda: b[8:12] + b[0:8],
        13: lambda: b[12:13] + b[8:12] + b[0:8], 14: lambda: b[13:14] + b[9:13] + b[1:9] + b[0:1],
        15: lambda: c2(13) + b[9:13] + b[1:9] + b[0:1], 16: lambda: c16(0), 17: lambda: b[9:17] + b[8:9] + b[0:8],
        18: lambda: b[17:18] + c16(1) + b[0:1], 19: lambda: c3(16) + c16(0), 20: lambda: b[16:20] + c16(0),
        21: lambda: b[20:21] + b[16:20] + c16(0), 22: lambda: c2(20) + b[16:20] + c16(0), 23: lambda: c3(20) + b[16:20] + c16(0),
        24: lambda: b[16:24] + c16(0), 25: lambda: b[17:25] + b[16:17] + c16(0), 26: lambda: b[25:26] + b[17:25] + b[16:17] + c16(0),
        27: lambda: c2(25) + b[17:25] + b[16:17] + c16(0), 28: lambda: b[24:28] + b[16:24] + b[8:16] + b[0:8],
        29: lambda: b[28:29] + b[24:28] + b[16:24] + b[8:16] + b[0:8], 30: lambda: c2(28) + b[24:28] + b[16:24] + b[8:16] + b[0:8],
        31: lambda: b[30:31] + b[26:30] + b[18:26] + b[10:18] + b[2:10] + c2(0)}
    out += tail[n]()
    return bytes(out)

def decompress_r2007(src, dsize):
    p = 0
    out = bytearray()
    n = len(src)
    def lit_len(op):
        nonlocal p
        l = op + 8
        if l == 0x17:
            x = src[p]
            p += 1
            l += x
            if x == 0xff:
                while True:
                    x = src[p] | (src[p + 1] << 8)
                    p += 2
                    l += x
                    if x != 0xffff: break
        return l
    def instr(op):
        nonlocal p
        h = op >> 4
        if h == 0:
            l = (op & 0xf) + 0x13
            o = src[p]
            op = src[p + 1]
            p += 2
            l += (op >> 3) & 0x10
            o += ((op & 0x78) << 5) + 1
        elif h == 1:
            l = (op & 0xf) + 3
            o = src[p]
            op = src[p + 1]
            p += 2
            o += ((op & 0xf8) << 5) + 1
        elif h == 2:
            o = src[p] | (src[p + 1] << 8)
            p += 2
            l = op & 7
            if op & 8 == 0:
                op = src[p]
                p += 1
                l += op & 0xf8
            else:
                o += 1
                l += src[p] << 3
                op = src[p + 1]
                p += 2
                l += ((op & 0xf8) << 8) + 0x100
        else:
            l = h
            o = op & 15
            op = src[p]
            p += 1
            o += ((op & 0xf8) << 1) + 1
        return op, o, l
    op = src[p]
    p += 1
    length = 0
    if op & 0xf0 == 0x20:
        p += 2
        length = src[p] & 7
        p += 1
    while p < n:
        if length == 0: length = lit_len(op)
        if p + length > n or len(out) + length > dsize: raise ValueError("literal overflow")
        out += _copy_literal(src, p, length)
        p += length
        length = 0
        if p >= n: break
        op = src[p]
        p += 1
        op, off, length = instr(op)
        while True:
            s = len(out) - off
            if s < 0: raise ValueError("bad back reference")
            for i in range(length): out.append(out[s + i])
            length = op & 7
            if length or p >= n: break
            op = src[p]
            p += 1
            if op >> 4 == 0: break
            if op >> 4 == 0x0f: op &= 0xf
            op, off, length = instr(op)
    return bytes(out)

def _r2007_system_page(d, off, comp, uncomp, rep):
    pesize = ((comp + 7) & ~7) * rep
    nb = (pesize + 238) // 239
    if off + nb * 255 > len(d): raise ValueError("system page at %d outside of file" % off)
    data, bad = rs_check(d[off:off + nb * 255], nb, 239, _rs_system)
    if bad: raise ValueError("system page at %d: Reed-Solomon parity errors in %d of %d blocks" % (off, bad, nb))
    u = decompress_r2007(data[:comp], uncomp) if comp < uncomp else data[:uncomp]
    if len(u) != uncomp: raise ValueError("system page at %d: decompressed %d of %d bytes" % (off, len(u), uncomp))
    return u

def check_r2007(d, ver, log):
    global _rs_system, _rs_data
    if _rs_system is None:
        _rs_system = _rs_parity_func(0x169, 16)
        _rs_data = _rs_parity_func(0x11D, 4)
    n = len(d)
    data, bad = rs_check(d[0x80:0x80 + 765], 3, 239, _rs_system)
    if bad: return "file header: Reed-Solomon parity errors"
    clen, = unpack_from('<l', data, 24)
    try:
        H = unpack_from('<34Q', decompress_r2007(data[32:32 + clen], 0x110) if clen > 0 else data[32:32 + 0x110], 0)
        if H[0] != 0x70 or H[1] != n: return "file header: size %d in header, file is %d bytes" % (H[1], n)
        pm = _r2007_system_page(d, 0x480 + H[7], H[10], H[11], H[3])
        pages = {}
        off = 0
        for i in range(0, len(pm) - 15, 16):
            size, pid = unpack_from('<qq', pm, i)
            pages[abs(pid)] = (off, size)
            off += size
        if H[24] not in pages: return "section map page missing from page map"
        sm = _r2007_system_page(d, 0x480 + pages[H[24]][0], H[22], H[25], H[27])
    except (ValueError, IndexError) as e:
        return str(e)
    # section map: szakaszonkent a lapok listaja; az "encoded==4" adat oldalak RS(255,251) kodoltak
    q = 0
    npages = 0
    nsec = 0
    while q + 64 <= len(sm):
        dsz, maxs, enc, hsh, nlen, unk, encoded, pc = unpack_from('<8Q', sm, q)
        q += 64
        name = sm[q:q + nlen].decode('utf-16le', 'replace').rstrip('\0')
        q += nlen
        for k in range(pc):
            poff, psz, pid, usz, csz, cks, crc = unpack_from('<7Q', sm, q)
            q += 56
            if pid not in pages: return "section %s: page %d missing from page map" % (name, pid)
            a, size = pages[pid]
            a += 0x480
            if a + size > n: return "section %s: page at %d outside of file" % (name, a)
            if encoded == 4:
                nb = size // 255
                _, bad = rs_check(d[a:a + nb * 255], nb, 251, _rs_data)
                if bad: return "section %s: page at %d: Reed-Solomon parity errors in %d of %d blocks" % (name, a, bad, nb)
            npages += 1
        nsec += 1
        log("DWG: section %s: %d pages" % (name, pc))
    log("DWG: %d sections, %d data pages" % (nsec, npages))
    return None


###############################################################################################################################

checkers = {"AC1006": check_r12, "AC1009": check_r12, "AC1012": check_r2000, "AC1014": check_r2000, "AC1015": check_r2000,
            "AC1018": check_r2004, "AC1024": check_r2004, "AC1027": check_r2004, "AC1032": check_r2004, "AC1021": check_r2007}

def testdwg(data, debug=False):
    """ visszaad: hibapont (0 = jo, -1 = nem tamogatott verzio). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """

    def log(*args):
        if debug: print(*args)

    ver = data[:6].decode('latin1')
    log("DWG: version %s, %d bytes" % (ver, len(data)))
    if ver not in checkers:
        log("WARNING: DWG version %s not supported" % ver)
        return -1
    try:
        err = checkers[ver](data, ver, log)
    except Exception as e:
        err = "exception: %r" % e
    if err:
        print("ERROR! DWG %s: %s" % (ver, err))
        return 10
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "dwg/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testdwg(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
