#! /usr/bin/python3

# DXF (AutoCAD Drawing Exchange Format) szintaxis ellenorzes, kulso konyvtar nelkul: ASCII es binaris DXF.
# A file (csoportkod, ertek) parokbol all, a kod tartomanya adja az ertek tipusat (DXF Reference: "Group Code Value Types").

import re
from struct import unpack_from

BINARY_SENTINEL = b'AutoCAD Binary DXF\r\n\x1a\x00'

# csoportkod -> ertek tipus: s=szoveg, f=lebegopontos, i=egesz, h=hexa (handle, binaris adat), None=ervenytelen kod
def _types():
    t = [None] * 1072
    def rng(a, b, k):
        for c in range(a, b + 1): t[c] = k
    rng(0, 9, 's'); rng(10, 59, 'f'); rng(60, 79, 'i'); rng(90, 99, 'i'); t[100] = 's'; t[102] = 's'; t[105] = 'h'
    rng(110, 149, 'f'); rng(160, 169, 'i'); rng(170, 179, 'i'); rng(210, 239, 'f'); rng(270, 289, 'i'); rng(290, 299, 'i')
    rng(300, 309, 's'); rng(310, 319, 'h'); rng(320, 369, 'h'); rng(370, 389, 'i'); rng(390, 399, 'h'); rng(400, 409, 'i')
    rng(410, 419, 's'); rng(420, 429, 'i'); rng(430, 439, 's'); rng(440, 459, 'i'); rng(460, 469, 'f'); rng(470, 479, 's')
    rng(480, 481, 'h'); t[999] = 's'; rng(1000, 1009, 's'); rng(1010, 1059, 'f'); rng(1060, 1071, 'i')
    return t

code_types = _types()

# ervenytelen byte-ok egy szoveges DXF-ben (a TAB, CR, LF megengedett)
ctrl_re = re.compile(rb'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
name_re = re.compile(rb'[A-Za-z0-9_$\-]+$')


def ascii_pairs(d, log):
    """ szoveges DXF: (kod, ertek, sorszam) parok. Hiba eseten ValueError. """
    lines = d.split(b'\n')
    if lines and lines[-1].strip() == b'': lines.pop()
    if len(lines) % 2: raise ValueError("last group code (line %d) has no value: truncated?" % len(lines))
    for i in range(0, len(lines), 2):
        c = lines[i].strip()
        try:
            code = int(c)
        except ValueError:
            raise ValueError("line %d: bad group code %r" % (i + 1, c[:20]))
        yield code, lines[i + 1].rstrip(b'\r'), i + 1


def binary_pairs(d, log):
    """ binaris DXF: 1 byte-os (R12, 255 utan 2 byte) vagy 2 byte-os (R13+) kodok, tipusos ertekek """
    p = len(BINARY_SENTINEL)
    two = d[p + 1] == 0      # R13+: 2 byte-os kod, az elso "0" kod 00 00-kent jelenik meg, utana 'S'
    log("DXF: binary, %d byte group codes" % (2 if two else 1))
    n = len(d)
    while p < n:
        start = p
        if two:
            code, = unpack_from('<H', d, p)
            p += 2
        else:
            code = d[p]
            p += 1
            if code == 255:
                code, = unpack_from('<H', d, p)
                p += 2
        k = code_types[code] if code < len(code_types) else None
        if k is None: raise ValueError("offset %d: bad group code %d" % (start, code))
        if k == 's' or (k == 'h' and not 310 <= code <= 319):
            e = d.find(b'\x00', p)
            if e < 0: raise ValueError("offset %d: unterminated string (code %d)" % (p, code))
            v = d[p:e]
            p = e + 1
        elif k == 'h':        # binaris adat: 1 byte hossz + adat
            l = d[p]
            v = d[p + 1:p + 1 + l]
            p += 1 + l
        elif k == 'f':
            v = unpack_from('<d', d, p)[0]
            p += 8
        else:
            size = 8 if 160 <= code <= 169 else 4 if (90 <= code <= 99 or 420 <= code <= 429 or 440 <= code <= 459 or code == 1071) else 1 if 290 <= code <= 299 else 2
            v = int.from_bytes(d[p:p + size], 'little', signed=True)
            p += size
        if p > n: raise ValueError("offset %d: value of code %d truncated" % (start, code))
        yield code, v, start


def testdxf(data, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_dxf(data, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_dxf(d, debug):

    def log(*args):
        if debug: print(*args)

    binary = d.startswith(BINARY_SENTINEL)
    if not binary:
        body = d.rstrip(b'\x1a\r\n\t ')   # a DOS-os fileok vegen ^Z lehet
        m = ctrl_re.search(body)
        if m:
            eof = body.rfind(b'\nEOF')
            if eof >= 0 and m.start() > eof:
                log("WARNING: %d bytes of garbage after EOF" % (len(body) - eof))
                body = body[:eof + 4]
            else:
                print("ERROR! control/binary byte 0x%02X at offset %d (line %d)" % (body[m.start()], m.start(), body.count(b'\n', 0, m.start()) + 1))
                return 10
        pairs = ascii_pairs(body, log)
    else:
        pairs = binary_pairs(d, log)

    section = None       # az aktualis szekcio neve
    sections = []
    table = None         # TABLES-ben az aktualis tabla
    block = False        # BLOCKS-ben BLOCK..ENDBLK kozott
    seq = None           # POLYLINE/INSERT(attribok) utan SEQEND-ig: (nev, hol)
    entity = None        # az aktualis entitas neve es a 66-os (attributes follow) flag
    attribs_follow = False
    expect_name = False  # SECTION utan 2-es kod kell
    eof = False
    comma = 0            # tizedesvesszos szamok (magyar/nemet locale-lal futo exportalok)
    npairs = 0
    version = None
    prev_var = None
    try:
        for code, v, where in pairs:
            npairs += 1
            if eof:
                raise ValueError("data after EOF at %s" % where)
            k = code_types[code] if 0 <= code < len(code_types) else None
            if k is None: raise ValueError("%s: bad group code %d" % (where, code))
            if not binary:
                # az ertek tipusanak ellenorzese a kod szerint
                try:
                    if k == 'f':
                        try: float(v)
                        except ValueError:
                            float(v.replace(b',', b'.'))
                            comma += 1
                    elif k == 'i': int(v)
                    elif k == 'h' and v.strip(): int(v, 16)
                except ValueError:
                    raise ValueError("%s: bad value %r for group code %d" % (where, v[:30], code))
            if expect_name:
                if code != 2: raise ValueError("%s: section name (code 2) expected after SECTION" % where)
                section = v
                sections.append(v.decode('latin1') if isinstance(v, bytes) else str(v))
                expect_name = False
                continue
            if code == 9 and section == b'HEADER': prev_var = v
            elif code == 1 and prev_var == b'$ACADVER' and version is None:
                version = v.decode('latin1') if isinstance(v, bytes) else str(v)
            if code == 66 and entity in (b'INSERT',): attribs_follow = int(v) == 1
            if code != 0: continue

            # ---------------- 0-s kod: uj entitas / szerkezeti elem ----------------
            if not v or not name_re.match(v): raise ValueError("%s: bad entity name %r" % (where, v[:30]))
            # az elozo entitas lezarasa: POLYLINE ill. attributumos INSERT utan VERTEX/ATTRIB..SEQEND jon
            if entity == b'POLYLINE': seq = (b'POLYLINE', b'VERTEX')
            elif entity == b'INSERT' and attribs_follow: seq = (b'INSERT', b'ATTRIB')
            attribs_follow = False
            entity = v
            if seq:
                if v == b'SEQEND':
                    seq = None
                    continue
                if v != seq[1]: raise ValueError("%s: %s without SEQEND (found %s)" % (where, seq[0].decode(), v.decode('latin1')))
                continue
            if v == b'SECTION':
                if section is not None: raise ValueError("%s: SECTION inside section %s" % (where, section.decode('latin1')))
                expect_name = True
            elif v == b'ENDSEC':
                if section is None: raise ValueError("%s: ENDSEC without SECTION" % where)
                if table: raise ValueError("%s: TABLE %s without ENDTAB" % (where, table.decode('latin1')))
                if block: raise ValueError("%s: BLOCK without ENDBLK" % where)
                section = None
            elif v == b'EOF':
                if section is not None: raise ValueError("%s: EOF inside section %s" % (where, section.decode('latin1')))
                eof = True
            elif section is None:
                raise ValueError("%s: %s outside of sections" % (where, v.decode('latin1')))
            elif section == b'TABLES':
                if v == b'TABLE':
                    if table: raise ValueError("%s: TABLE inside TABLE" % where)
                    table = b'?'
                elif v == b'ENDTAB':
                    if not table: raise ValueError("%s: ENDTAB without TABLE" % where)
                    table = None
            elif section == b'BLOCKS':
                if v == b'BLOCK':
                    if block: raise ValueError("%s: BLOCK inside BLOCK" % where)
                    block = True
                elif v == b'ENDBLK':
                    if not block: raise ValueError("%s: ENDBLK without BLOCK" % where)
                    block = False
    except ValueError as e:
        print("ERROR! DXF: %s" % e)
        return 10
    log("DXF: %s, version %s, %d pairs, sections: %s" % ("binary" if binary else "ASCII", version, npairs, " ".join(sections)))
    if comma: log("WARNING: %d numbers with decimal comma (exporter locale bug)" % comma)
    if not eof:
        print("ERROR! DXF: missing EOF (truncated?)")
        return 10
    if "ENTITIES" not in sections:
        print("ERROR! DXF: no ENTITIES section")
        return 10
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "dxf/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testdxf(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
