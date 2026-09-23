#! /usr/bin/python3

# SPSS system file (.sav, $FL2) es zlib tomoritett valtozata (.zsav, $FL3) ellenorzese, kulso konyvtar nelkul.
# Formatum leiras: GNU PSPP, "System File Format" (https://www.gnu.org/software/pspp/pspp-dev/html_node/System-File-Format.html)

from struct import unpack_from
import zlib


class Bytecode:
    """
    a "bytecode" tomoritett adatfolyam vegigjarasa darabonkent (a zsav blokkjai a bytecode stream tetszoleges pontjan
    vegzodhetnek): 8 parancs byte, utana a 253-as kodokhoz tartozo 8 byte-os nyers adatok.
    0: kitoltes, 1..251: szam, 252: file vege, 253: nyers 8 byte, 254: 8 szokoz, 255: sysmis
    """
    def __init__(self):
        self.elements = 0    # a dekodolt 8 byte-os elemek szama
        self.cmds = b''      # a meg nem teljes parancs blokk
        self.skip = 0        # az aktualis blokkbol hatralevo nyers adat byte-ok
        self.ended = False   # volt 252-es (file vege) kod
        self.extra = 0       # a file vege utani byte-ok

    def feed(self, d):
        p = 0
        n = len(d)
        # gyors ut: teljes parancs blokkok a darab belsejeben (a darabhatarokat lent a lassu ut kezeli)
        if not self.cmds and not self.skip and not self.ended:
            elements = self.elements
            while p + 8 <= n:
                cmd = d[p:p + 8]
                if 252 in cmd: break
                p += 8 + cmd.count(253) * 8
                elements += 8 - cmd.count(0)
            self.elements = elements
            if p > n:    # az utolso blokk nyers adata tulnyulik a darabon
                self.skip = p - n
                return
        while p < n:
            if self.skip:
                t = min(self.skip, n - p)
                p += t
                self.skip -= t
                continue
            if self.ended:
                self.extra += n - p
                return
            need = 8 - len(self.cmds)
            self.cmds += d[p:p + need]
            p += need
            if len(self.cmds) < 8: return
            cmd = self.cmds
            self.cmds = b''
            if 252 in cmd:
                cmd = cmd[:cmd.index(252)]
                self.ended = True
            self.elements += len(cmd) - cmd.count(0)
            self.skip = cmd.count(253) * 8

    def truncated(self):
        return bool(self.cmds) or self.skip > 0


def testsav(data, debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """
    try:
        return parse_sav(data, debug)
    except Exception as e:
        print("ERROR! exception:", repr(e))
        return 100


def parse_sav(d, debug):

    def log(*args):
        if debug: print(*args)

    magic = d[0:4]
    if magic not in [b'$FL2', b'$FL3'] or len(d) < 176:
        print("ERROR! not an SPSS system file")
        return 100
    # a layout_code (2 vagy 3) alapjan derul ki a byte sorrend
    E = "<" if unpack_from('<l', d, 64)[0] in (2, 3) else ">"
    def i32(p): return unpack_from(E + 'l', d, p)[0]
    layout, case_size, compression, weight, ncases = unpack_from(E + 'lllll', d, 64)
    bias, = unpack_from(E + 'd', d, 84)
    log("SAV: %s %s  layout=%d case_size=%d compression=%d weight=%d cases=%d bias=%g" % (magic.decode(), d[4:64].decode('latin1').strip(), layout, case_size, compression, weight, ncases, bias))
    log("SAV: created %s %s, label: %s" % (d[92:101].decode('latin1'), d[101:109].decode('latin1'), d[109:173].decode('latin1').strip()))
    if layout not in (2, 3) or compression not in (0, 1, 2) or (compression == 2) != (magic == b'$FL3'):
        print("ERROR! bad SAV header: layout=%d compression=%d" % (layout, compression))
        return 10

    # ---------------- dictionary ----------------
    p = 176
    nvars = 0          # valtozo rekordok (8 byte-os elemek) szama
    cont = 0           # a meg hatralevo string folytatas rekordok szama
    segments = set()   # a nem folytatas valtozo rekordok indexei (1-tol)
    while True:
        if p + 4 > len(d):
            print("ERROR! EOF in dictionary")
            return 10
        rt = i32(p)
        if rt == 2:        # variable
            typ, has_label, nmiss = unpack_from(E + 'lll', d, p + 4)
            name = d[p + 24:p + 32].decode('latin1').rstrip()
            p += 32
            nvars += 1
            if typ == -1:
                if cont <= 0:
                    print("ERROR! unexpected string continuation record #%d" % nvars)
                    return 10
                cont -= 1
            else:
                if cont:
                    print("ERROR! missing %d string continuation records before variable #%d (%s)" % (cont, nvars, name))
                    return 10
                if typ < 0 or typ > 255 or has_label not in (0, 1) or nmiss not in (0, 1, 2, 3, -2, -3) or (typ > 0 and nmiss < 0):
                    print("ERROR! bad variable record #%d (%s): type=%d label=%d missing=%d" % (nvars, name, typ, has_label, nmiss))
                    return 10
                segments.add(nvars)
                cont = (typ + 7) // 8 - 1 if typ > 0 else 0
            if has_label:
                l = i32(p)
                p += 4 + ((l + 3) & ~3)
            p += 8 * abs(nmiss)
        elif rt == 3:      # value labels, utana kotelezoen egy 4-es rekord
            cnt = i32(p + 4)
            p += 8
            if cnt < 0 or cnt > len(d):
                print("ERROR! bad value label record (%d labels)" % cnt)
                return 10
            for i in range(cnt):
                if p + 9 > len(d): break
                p += (8 + 1 + d[p + 8] + 7) & ~7
            if p + 8 > len(d) or i32(p) != 4:
                print("ERROR! value label record not followed by a variable index record")
                return 10
            vc = i32(p + 4)
            if vc < 1 or p + 8 + vc * 4 > len(d):
                print("ERROR! bad value label variable count %d" % vc)
                return 10
            for v in unpack_from(E + '%dl' % vc, d, p + 8):
                if v not in segments:
                    print("ERROR! value labels refer to variable index %d" % v)
                    return 10
            p += 8 + vc * 4
        elif rt == 6:      # document
            n = i32(p + 4)
            if n < 0:
                print("ERROR! bad document record")
                return 10
            p += 8 + n * 80
        elif rt == 7:      # extension: subtype, size, count, adat
            sub, size, count = unpack_from(E + 'lll', d, p + 4)
            if size < 0 or count < 0 or p + 16 + size * count > len(d) or (sub == 3 and (size, count) != (4, 8)) or (sub == 4 and (size, count) != (8, 3)):
                print("ERROR! bad extension record subtype %d (size %d, count %d)" % (sub, size, count))
                return 10
            log("  extension subtype %d: %d x %d bytes" % (sub, count, size))
            p += 16 + size * count
        elif rt == 999:    # dictionary vege
            p += 8
            break
        else:
            print("ERROR! bad dictionary record type %d at %d" % (rt, p))
            return 10
        if p > len(d):
            print("ERROR! dictionary record overruns file")
            return 10
    if cont:
        print("ERROR! missing %d string continuation records" % cont)
        return 10
    log("SAV: %d variable records (%d variable segments), data at %d" % (nvars, len(segments), p))
    if nvars == 0:
        print("ERROR! no variables")
        return 10
    if case_size == 0: log("WARNING: case size 0 in header (ReadStat), treated as unknown")
    elif case_size not in (-1, nvars):
        print("ERROR! case size %d in header != %d variable records" % (case_size, nvars))
        return 10
    if weight and weight not in segments:
        print("ERROR! bad weight variable index %d" % weight)
        return 10

    # ---------------- data ----------------
    if compression == 0:
        n = len(d) - p
        if n % (nvars * 8) or (ncases >= 0 and n != ncases * nvars * 8):
            print("ERROR! uncompressed data: %d bytes, expected %s x %d" % (n, ncases if ncases >= 0 else "N", nvars * 8))
            return 10
        log("SAV: %d cases" % (n // (nvars * 8)))
        return 0

    bc = Bytecode()
    if compression == 1:
        bc.feed(d[p:])
    else:                  # zsav: zheader, zlib blokkok, ztrailer
        zheader, ztrailer, ztrailer_len = unpack_from(E + 'qqq', d, p)
        if zheader != p or ztrailer + ztrailer_len != len(d) or ztrailer < p + 24:
            print("ERROR! bad ZSAV header: zheader=%d ztrailer=%d+%d file=%d" % (zheader, ztrailer, ztrailer_len, len(d)))
            return 10
        int_bias, zero, block_size, nblocks = unpack_from(E + 'qqll', d, ztrailer)
        if ztrailer_len != 24 + 24 * nblocks or nblocks < 0:
            print("ERROR! bad ZSAV trailer (%d blocks, %d bytes)" % (nblocks, ztrailer_len))
            return 10
        uofs, cofs = zheader, zheader + 24
        for i in range(nblocks):
            bu, bcomp, usize, csize = unpack_from(E + 'qqll', d, ztrailer + 24 + i * 24)
            if bu != uofs or bcomp != cofs or cofs + csize > ztrailer or usize > block_size:
                print("ERROR! ZSAV block #%d: bad offsets/sizes" % i)
                return 10
            try:
                u = zlib.decompress(d[cofs:cofs + csize])
            except zlib.error as e:
                print("ERROR! ZSAV block #%d: zlib: %s" % (i, e))
                return 10
            if len(u) != usize:
                print("ERROR! ZSAV block #%d: %d of %d bytes" % (i, len(u), usize))
                return 10
            bc.feed(u)
            uofs += usize
            cofs += csize
        if cofs != ztrailer:
            print("ERROR! %d bytes between last ZSAV block and trailer" % (ztrailer - cofs))
            return 10
        log("SAV: %d zlib blocks" % nblocks)

    cases, rest = divmod(bc.elements, nvars)
    log("SAV: %d cases%s" % (cases, ", end code" if bc.ended else ""))
    if bc.truncated() or rest:
        print("ERROR! compressed data truncated: %d cases + %d of %d values" % (cases, rest, nvars))
        return 10
    if ncases >= 0 and cases != ncases:
        print("ERROR! %d cases in data, %d in header" % (cases, ncases))
        return 10
    if bc.extra: log("WARNING: %d bytes after end of data" % bc.extra)
    return 0


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "sav/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res = testsav(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res)
