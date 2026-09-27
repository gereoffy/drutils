#! /usr/bin/python3

import io
import datetime
import re
import struct
import zlib
import zipfile
import xml.parsers.expat

# OpenDocument / epub: a 'mimetype' tag tartalma alapjan
mimetypes = {
    b'application/vnd.oasis.opendocument.text': "odt",
    b'application/vnd.oasis.opendocument.spreadsheet': "ods",
    b'application/vnd.oasis.opendocument.presentation': "odp",
    b'application/vnd.oasis.opendocument.graphics': "odg",
    b'application/vnd.oasis.opendocument.formula': "odf",
    b'application/epub+zip': "epub",
}

# Office Open XML: jellemzo fo tag -> kiterjesztes
ooxml = [("word/document.xml", "docx"), ("xl/workbook.xml", "xlsx"), ("ppt/presentation.xml", "pptx"), ("visio/document.xml", "vsdx")]


def detect(zf, names):
    """ a zip tipusa (kiterjesztes) es hogy az xml tagjait ellenorizni kell-e """
    if "mimetype" in names:
        mt = zf.read("mimetype").strip()
        if mt in mimetypes: return mimetypes[mt], True
    if "[Content_Types].xml" in names:
        for n, ext in ooxml:
            if n in names: return ext, True
        return "ooxml", True
    if any(n.startswith("outputViewer000") for n in names): return "spv", True # contains the output generated from data analytics functions run within SPSS
    if "META-INF/MANIFEST.MF" in names: return ("apk" if "AndroidManifest.xml" in names else "jar"), False
    return "zip", False


def check_member(zf, z, parse_xml):
    """
    egy tag vegigolvasasa (a zipfile a vegen ellenorzi a CRC-t), xml eseten kozben jolformaltsag-ellenorzes expat-tal
    (nem epit fat, igy a nagy xml-ek sem fogyasztanak memoriat). Hiba eseten kivetelt dob.
    """
    parser = None
    if parse_xml:
        parser = xml.parsers.expat.ParserCreate()
    with zf.open(z, mode='r') as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk: break
            if parser: parser.Parse(chunk, False)
    if parser: parser.Parse(b'', True)


spv_ref_re = re.compile(rb'<vtb:(?:dataPath|path)>([^<]*)</')

def check_spv(zf, infos, readok, log):
    """
    SPSS Viewer (.spv): az outputViewer*.xml-ek <vtb:dataPath>/<vtb:path> hivatkozasai letezo tagokra mutatnak
    (a visszaallitott zip-ekbol tagok veszhetnek el, ezt a CRC nem jelzi). visszaad: hibauzenet vagy None
    """
    names = set(z.filename for z in infos)
    refs = set()
    for z in infos:
        if z.filename.startswith("outputViewer") and z.filename.endswith(".xml") and z.filename in readok:
            refs.update(r.decode('utf-8', 'replace') for r in spv_ref_re.findall(zf.read(z)))
    for n in sorted(names - refs):
        if n.endswith(".bin") or re.search(r'_(table|chart|notes|warning|model)\.xml$', n): log("WARNING: %s: not referenced" % n)
    missing = sorted(refs - names)
    if missing: return "%d referenced members missing, first: %s" % (len(missing), missing[0])
    return None


# ZIP_INFO: letrehozas / utolso mentes datuma, szerzo, utoljara mentette, cim, program (a visszaallitott fileok azonositasahoz)
# Forras: OOXML docProps/core.xml + app.xml, ODF meta.xml, EPUB .opf, JAR MANIFEST.MF; ha ezekben nincs datum,
# akkor a zip tagok datuma (a legregebbi = letrehozas, a legujabb = modositas). Minden datum helyi idoben.

date_re = re.compile(r'\s*(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d)(?::(\d\d))?(?:[.,]\d*)?)?\s*(Z|[+-]\d\d:?\d\d)?\s*$')

def _isodate(s):
    """ ISO 8601 datum -> helyi ido datetime (UTC/zonas eseten atszamolva), ertelmetlen erteknel None """
    m = date_re.match(s or "")
    if not m: return None
    try:
        y, mo, d, h, mi, sec = (int(x or 0) for x in m.groups()[:6])
        t = datetime.datetime(y, mo, d, h, mi, sec)
        tz = m.group(7)
        if tz:
            off = 0 if tz == "Z" else (1 if tz[0] == "+" else -1) * (int(tz[1:3]) * 60 + int(tz[-2:]))
            t = (t - datetime.timedelta(minutes=off)).replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        return t
    except Exception:
        return None

def _plausible(t):
    # a DOS datum legkorabbi erteke 1980-01-01 00:00 (az MS Office minden tagnak ezt irja); a jovobeli datum is hibas
    return t is not None and datetime.datetime(1980, 1, 1, 0, 0, 2) <= t <= datetime.datetime.now() + datetime.timedelta(days=2)

def _xml_fields(data):
    """ xml -> [(helyi tagnev, attributumok, szoveg)], namespace nelkul; hibas xml-bol amennyi kiolvashato """
    out = []
    stack = []
    p = xml.parsers.expat.ParserCreate()
    def start(name, attrs): stack.append([name.rsplit(":", 1)[-1].rsplit("}", 1)[-1], attrs, ""])
    def end(name):
        e = stack.pop()
        out.append((e[0], e[1], e[2].strip()))
    def text(s):
        if stack: stack[-1][2] += s
    p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = start, end, text
    try: p.Parse(data, True)
    except Exception: pass
    return out

def _read(zf, name):
    """ egy tag tartalma; CRC hibanal / serult tomoritesnel amennyi kiolvashato """
    try:
        return zf.read(name)
    except Exception:
        try:
            buf = b""
            with zf.open(name) as f:
                while True:
                    b = f.read(4096)
                    if not b: break
                    buf += b
        except Exception:
            pass
        return buf

def _ntfs_time(x):
    return datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=x // 10)

def _member_times(z):
    """ egy zip tag modositasi datuma(i): az extra mezok (NTFS, Unix extended timestamp) pontosabbak a DOS datumnal """
    times = []
    e = z.extra
    p = 0
    while p + 4 <= len(e):
        tag, size = int.from_bytes(e[p:p + 2], 'little'), int.from_bytes(e[p + 2:p + 4], 'little')
        v = e[p + 4:p + 4 + size]
        try:
            if tag == 0x000A and size >= 32 and v[4:8] == b'\x01\x00\x18\x00':   # NTFS: mtime, atime, ctime (UTC)
                for off in (8, 24):
                    times.append(_ntfs_time(int.from_bytes(v[off:off + 8], 'little')).replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None))
            elif tag == 0x5455 and size >= 5 and v[0] & 1:   # extended timestamp: mtime (Unix, UTC)
                times.append(datetime.datetime.fromtimestamp(int.from_bytes(v[1:5], 'little')))
        except Exception:
            pass
        p += 4 + size
    try:
        times.append(datetime.datetime(*z.date_time))
    except Exception:
        pass
    return [t for t in times if _plausible(t)]

def zip_info(zf, infos, names, ext):
    """ visszaad: (letrehozas, modositas, datum forrasa, utoljara mentette, szerzo, cim, program) """
    created = modified = None
    saved = author = title = app = ""
    try:
        if ext in ("docx", "xlsx", "pptx", "vsdx", "ooxml"):
            for tag, attrs, s in _xml_fields(_read(zf, "docProps/core.xml")) if "docProps/core.xml" in names else []:
                if tag == "created": created = _isodate(s)
                elif tag == "modified": modified = _isodate(s)
                elif tag == "creator": author = s
                elif tag == "lastModifiedBy": saved = s
                elif tag == "title": title = s
            if "docProps/app.xml" in names:
                f = dict((tag, s) for tag, attrs, s in _xml_fields(_read(zf, "docProps/app.xml")))
                app = (f.get("Application", "") + " " + f.get("AppVersion", "")).strip()
        elif ext in ("odt", "ods", "odp", "odg", "odf") and "meta.xml" in names:
            for tag, attrs, s in _xml_fields(_read(zf, "meta.xml")):
                if tag == "creation-date": created = _isodate(s)
                elif tag == "date": modified = _isodate(s)
                elif tag == "initial-creator": author = s
                elif tag == "creator": saved = s
                elif tag == "title": title = s
                elif tag == "generator": app = s
        elif ext == "epub" and "META-INF/container.xml" in names:
            opf = [a.get("full-path") for tag, a, s in _xml_fields(_read(zf, "META-INF/container.xml")) if tag == "rootfile"]
            if opf and opf[0] in names:
                for tag, attrs, s in _xml_fields(_read(zf, opf[0])):
                    if tag == "date" and not created: created = _isodate(s)
                    elif tag == "meta" and attrs.get("property") == "dcterms:modified": modified = _isodate(s)
                    elif tag == "creator" and not author: author = s
                    elif tag == "title" and not title: title = s
                    elif tag == "meta" and attrs.get("name") == "generator": app = attrs.get("content", "")
        elif ext in ("jar", "apk") and "META-INF/MANIFEST.MF" in names:
            m = re.search(rb'^Created-By:\s*(.*?)\r?$', _read(zf, "META-INF/MANIFEST.MF"), re.M)
            if m: app = m.group(1).decode('utf-8', 'replace')
    except Exception:
        pass
    src_c, src_m = "meta", "meta"
    if not _plausible(created): created = None
    if not _plausible(modified): modified = None
    if not created or not modified:
        times = [t for z in infos for t in _member_times(z)]
        if times:
            if not created: created, src_c = min(times), "zip"
            if not modified: modified, src_m = max(times), "zip"
    fmt = lambda t: t.strftime('%Y-%m-%d %H:%M:%S') if t else ""
    src = "" if not created and not modified else src_c if src_c == src_m else src_c + "/" + src_m
    return fmt(created), fmt(modified), src, saved, author, title, app


def testzip(data, debug=False, fname=""):
    """
    visszaad: (hibapont, kiterjesztes). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent.
    Minden filerol kiir egy sort (grep-pel CSV-be gyujtheto):
      ZIP_INFO;filenev;zip verzio;tipus;letrehozas;utolso mentes;datum forrasa (meta|zip);utoljara mentette;szerzo;cim;program;OK|BAD
    """
    errcnt, ext, info = _testzip(data, debug)
    def clean(x): return re.sub(r'[\x00-\x1f\x7f\ufeff]+', ' ', str(x).replace(";", ",")).strip()
    print("ZIP_INFO;" + ";".join(clean(x) for x in (fname,) + info[:1] + (ext,) + info[1:] + ("OK" if errcnt == 0 else "BAD",)))
    return errcnt, ext


def _locate(data, log):
    """
    a zip vegenek (EOCD) keresese, visszaallitott fileokhoz: a file vegen szemet lehet (akar egy masik zip vege is, sajat EOCD-vel),
    vagy hianyozhat a kozponti konyvtar. visszaad: (a vizsgalando adat, hibauzenet vagy None)
    """
    eocds = []
    e = len(data)
    while len(eocds) < 16:
        e = data.rfind(b'PK\x05\x06', 0, e)
        if e < 0: break
        if e + 22 <= len(data): eocds.append(e)
    for e in eocds:
        cds, cdo, clen = struct.unpack('<IIH', data[e + 12:e + 22])
        if cdo == 0xFFFFFFFF: return data, None   # zip64: a zipfile kezeli
        if cdo + cds == e and (cds == 0 or data[cdo:cdo + 4] == b'PK\x01\x02'):
            end = e + 22 + clen
            if e != eocds[0]:   # a vegen egy masik (pl. korabbi mentes) zip darabja: a Word/LibreOffice sem tudja rendesen megnyitni
                return data[:end], "%d bytes after the end of zip, containing another zip end record (mixed with another file?)" % (len(data) - end)
            if end < len(data):
                log("WARNING: %d bytes of garbage after the end of zip" % (len(data) - end))
                if len(data) - end > 65000: return data[:end], None   # a zipfile csak a file vegenek 64k-jaban keresi az EOCD-t
            return data, None
    if eocds:
        e = eocds[0]
        cds, cdo = struct.unpack('<II', data[e + 12:e + 20])
        return data, "central directory not at its recorded offset (%+d bytes): part of the file is missing or replaced" % (e - cdo - cds)
    return _rebuild(data, log)

def _rebuild(data, log):
    """ nincs EOCD (csonka file): kozponti konyvtar epitese a helyi fejlecekbol, hogy a tagok ellenorizhetok legyenek """
    p = 0
    cd = []
    while p + 30 <= len(data) and data[p:p + 4] == b'PK\x03\x04':
        ver, flag, meth, mt, md, crc, cs, us, nl, el = struct.unpack('<HHHHHIIIHH', data[p + 4:p + 30])
        name, extra = data[p + 30:p + 30 + nl], data[p + 30 + nl:p + 30 + nl + el]
        q = p + 30 + nl + el
        r = q + cs
        if flag & 8:   # data descriptor: a meret csak a tag utan van, a deflate folyam vegeig ki kell csomagolni
            if meth != 8: break
            o = zlib.decompressobj(-15)
            r = q
            while not o.eof and r < len(data):
                o.decompress(data[r:r + (1 << 20)])
                r = min(r + (1 << 20), len(data))
            if o.eof:
                r -= len(o.unused_data)
                cs = r - q
                if data[r:r + 4] == b'PK\x07\x08': r += 4
                if r + 12 <= len(data): crc, cs, us = struct.unpack('<III', data[r:r + 12])
                r += 12
            else:
                cs = len(data) - q
        cd.append(struct.pack('<4sHHHHHHIIIHHHHHII', b'PK\x01\x02', ver, ver, flag & ~8, meth, mt, md, crc, cs, us, nl, len(extra), 0, 0, 0, 0, p) + name + extra)
        p = r
    if not cd: return data, None   # nem is zip
    end = min(p, len(data))
    cdd = b''.join(cd)
    msg = "end of central directory not found (truncated file?), %d members found by local headers" % len(cd)
    return data[:end] + cdd + struct.pack('<4sHHHHIIH', b'PK\x05\x06', 0, 0, len(cd), len(cd), len(cdd), end, 0), msg


def _testzip(data, debug):

    def log(*args):
        if debug: print(*args)

    errcnt = 0
    ext = "zip"
    data, err = _locate(data, log)
    if err:
        print("ERROR! ZIP: " + err)
        errcnt += 10
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), mode='r')
    except Exception as e:
        print("ERROR! ZIP open failed: %r" % e)
        return errcnt + 10, ext, ("",) * 8
    with zf:
        infos = zf.infolist()
        names = set(z.filename for z in infos)
        try:
            ext, office = detect(zf, names)
        except Exception as e:
            print("ERROR! ZIP: cannot read mimetype: %r" % e)
            errcnt += 10
            office = False
        log("ZIP: %d members, type: %s" % (len(infos), ext))
        bad = 0
        readok = set()   # a hibatlanul beolvasott tagok
        for z in infos:
            if z.is_dir(): continue
            if z.flag_bits & 1:
                log("ZIP.encrypted: " + str(z.filename)) # ezzel ugyse tudunk semmit kezdeni...
                continue
            n = z.filename.lower()
            # az ures xml-t nem nezzuk: a LibreOffice pl. a Configurations2/accelerator/current.xml-t mindig uresen irja
            parse_xml = office and z.file_size > 0 and (n.endswith(".xml") or n.endswith(".rels") or (ext == "spv" and z.filename.startswith("outputViewer000")))
            log(z.filename, z.compress_size, z.file_size, "xml" if parse_xml else "")
            try:
                check_member(zf, z, parse_xml)
                readok.add(z.filename)
            except NotImplementedError as e:   # pl. Deflate64: nem tudjuk ellenorizni, de nem is hibas
                log("WARNING: %s: %s" % (z.filename, e))
            except xml.parsers.expat.ExpatError as e:
                bad += 1
                if bad <= 10: print("ERROR! %s: XML error: %s" % (z.filename, e))
            except Exception as e:
                bad += 1
                if bad <= 10: print("ERROR! %s: %r" % (z.filename, e))
        if bad:
            if bad > 10: print("ERROR! ... %d bad members total" % bad)
            errcnt += 10
        if ext == "spv":
            err = check_spv(zf, infos, readok, log)
            if err:
                print("ERROR! SPV: %s" % err)
                errcnt += 10
        v = max((z.extract_version for z in infos), default=0)
        info = ("%d.%d" % (v // 10, v % 10) if v else "",) + zip_info(zf, infos, names, ext)
    return errcnt, ext, info


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "zip/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res, ext = testzip(f.read(), debug=True, fname=n)
    if res > 0: print("!!!HIBAS!!!", res, ext)
