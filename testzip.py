#! /usr/bin/python3

import io
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


def testzip(data, debug=False):
    """ visszaad: (hibapont, kiterjesztes). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """

    def log(*args):
        if debug: print(*args)

    errcnt = 0
    ext = "zip"
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), mode='r')
    except Exception as e:
        print("ERROR! ZIP open failed: %r" % e)
        return 10, ext
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
    return errcnt, ext


if __name__ == "__main__":
  import os, sys
  path = sys.argv[1] if len(sys.argv) > 1 else "zip/"
  if os.path.isdir(path):
    files = [os.path.join(path, n) for n in sorted(os.listdir(path))]
  else:
    files = sys.argv[1:]
  for n in files:
    print("\n\n==================== %s ======================\n" % (os.path.basename(n)))
    with open(n, "rb") as f: res, ext = testzip(f.read(), debug=True)
    if res > 0: print("!!!HIBAS!!!", res, ext)
