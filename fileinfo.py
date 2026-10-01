#! /usr/bin/python3

# a *_INFO sorok kozos reszei (a visszaallitott fileok azonositasahoz: datumok, szerzo, program, eszkoz)
#   XXX_INFO;filenev;verzio;tipus;letrehozas;utolso mentes;datum forrasa;utoljara mentette;szerzo;cim;program;[eszkoz;]OK|BAD|DUNNO
# Minden datum helyi idoben 'YYYY-MM-DD HH:MM:SS' formaban, az UTC forrasok atszamolva. Ures mezo: nincs (ertelmes) adat.

import datetime
import os
import re
import time
from struct import unpack_from

# True: a vizsgalt file modositasi idejet (mtime, atime) a belole kiolvasott utolso mentes datumara allitja (ha az nincs, a
# letrehozasera), mint a "touch -d". Visszaallitott fileoknal hasznos, ahol a file datuma a visszaallitas ideje lett.
fix_filedatetime = False


def clean(x):
    """ a mezobol a ';' es a vezerlo karakterek (a grep binarisnak nezne a sort) eltavolitasa """
    return re.sub(r'[\x00-\x1f\x7f﻿]+', ' ', str(x if x is not None else "").replace(";", ",")).strip()

def fmt(t):
    return t.strftime('%Y-%m-%d %H:%M:%S') if t else ""

def result(res):
    return "OK" if res == 0 else "BAD" if res > 0 else "DUNNO"

def print_info(prefix, fields, set_time=True):
    """
    fields: (filenev, verzio, tipus, letrehozas, utolso mentes, ...). set_time: fix_filedatetime eseten a file datuma a
    4./5. mezobol (False: ha a sor nem a filerol szol, pl. THUMB_INFO)
    """
    print(prefix + "_INFO;" + ";".join(clean(fmt(x) if isinstance(x, datetime.datetime) else x) for x in fields))
    if set_time: set_file_time(fields[0], fields[3], fields[4])

def set_file_time(fname, created, modified):
    """ fix_filedatetime eseten a file mtime/atime-ja := utolso mentes (ha nincs: letrehozas). datetime vagy 'YYYY-MM-DD HH:MM:SS' """
    if not fix_filedatetime or not fname: return
    t = modified or created
    if not t: return
    try:
        if not isinstance(t, datetime.datetime): t = datetime.datetime.strptime(t, '%Y-%m-%d %H:%M:%S')
        if not plausible(t): return
        ts = time.mktime(t.timetuple())
        os.utime(fname, (ts, ts))
    except Exception as e:
        print("WARNING: cannot set file time of %s: %r" % (fname, e))

def plausible(t):
    return t if t is not None and datetime.datetime(1980, 1, 1, 0, 0, 2) <= t <= datetime.datetime.now() + datetime.timedelta(days=2) else None

def utc_to_local(t):
    try:
        return t.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    except Exception:
        return None

def date_source(created, modified, src_c, src_m):
    if not created and not modified: return ""
    if not created: return src_m
    if not modified or src_c == src_m: return src_c
    return src_c + "/" + src_m


iso_re = re.compile(r'\s*(\d{4})[-:](\d\d)[-:](\d\d)(?:[T ](\d\d):(\d\d)(?::(\d\d))?(?:[.,]\d*)?)?\s*(Z|[+-]\d\d:?\d\d)?')

def iso_local(s):
    """ ISO 8601 / EXIF ('YYYY:MM:DD HH:MM:SS') datum -> helyi ido; idozona nelkul helyi idonek vesszuk. Hibas: None """
    m = iso_re.match(s or "")
    if not m: return None
    try:
        y, mo, d, h, mi, sec = (int(x or 0) for x in m.groups()[:6])
        t = datetime.datetime(y, mo, d, h, mi, sec)
        tz = m.group(7)
        if tz:
            off = 0 if tz == "Z" else (1 if tz[0] == "+" else -1) * (int(tz[1:3]) * 60 + int(tz[-2:]))
            t = utc_to_local(t - datetime.timedelta(minutes=off))
        return plausible(t)
    except Exception:
        return None


###############################################################################################################################
# EXIF / TIFF IFD (jpeg APP1, tif, heic Exif elem)

def tiff_meta(b, ifd0=None, little=True):
    """
    TIFF szerkezetu adat (II/MM fejlec) IFD0 + Exif IFD tagjei. Serult adatnal amennyi kiolvashato.
    ifd0: fejlec nelkuli IFD (pl. a Fuji AVI strd chunkja): az IFD0 helye b-ben, az eltolasok b elejehez kepest.
    visszaad: dict: created (DateTimeOriginal/Digitized), modified (DateTime), make, model, software, artist, title
    """
    out = {}
    try:
        if ifd0 is None and b[:2] not in (b'II', b'MM'): return out
        E = ('<' if b[:2] == b'II' else '>') if ifd0 is None else ('<' if little else '>')
        def ifd(off):
            tags = {}
            if off < (8 if ifd0 is None else 0) or off + 2 > len(b): return tags
            n, = unpack_from(E + 'H', b, off)
            for i in range(min(n, 500)):
                p = off + 2 + i * 12
                if p + 12 > len(b): break
                tag, typ, cnt = unpack_from(E + 'HHL', b, p)
                size = {1: 1, 2: 1, 3: 2, 4: 4, 7: 1}.get(typ)
                if tag == 700 and typ in (1, 7): typ = 7   # XMP: BYTE tomb
                if not size: continue
                q = p + 8 if size * cnt <= 4 else unpack_from(E + 'L', b, p + 8)[0]
                if q + size * cnt > len(b): continue
                if typ == 2 or typ == 7 or typ == 1: tags[tag] = b[q:q + cnt]
                elif typ == 3: tags[tag] = unpack_from(E + 'H', b, q)[0]
                else: tags[tag] = unpack_from(E + 'L', b, q)[0]
            return tags
        t0 = ifd(unpack_from(E + 'L', b, 4)[0] if ifd0 is None else ifd0)
        ex = ifd(t0[0x8769]) if isinstance(t0.get(0x8769), int) else {}
        def s(tags, tag):
            v = tags.get(tag)
            if not isinstance(v, bytes): return ""
            v = v.split(b'\x00')[0]
            try: return v.decode('utf-8').strip()
            except UnicodeDecodeError: return v.decode('latin1').strip()
        def xp(tag):   # Windows XP* tag: UTF-16LE
            v = t0.get(tag)
            return v.decode('utf-16le', 'replace').split('\x00')[0].strip() if isinstance(v, bytes) else ""
        out['created'] = iso_local(s(ex, 0x9003)) or iso_local(s(ex, 0x9004))
        out['modified'] = iso_local(s(t0, 0x0132))
        out['make'], out['model'], out['software'] = s(t0, 0x010F), s(t0, 0x0110), s(t0, 0x0131)
        out['artist'] = s(t0, 0x013B) or xp(0x9C9D)
        out['title'] = xp(0x9C9B) or s(t0, 0x010E)
        if isinstance(t0.get(256), int) and isinstance(t0.get(257), int): out['dims'] = "%dx%d" % (t0[256], t0[257])
        if isinstance(t0.get(700), bytes): out['xmp'] = t0[700]
    except Exception:
        pass
    return out

def device(make, model):
    """ 'Canon Canon EOS 5D' -> 'Canon EOS 5D' """
    make, model = (make or "").strip(), (model or "").strip()
    if make and model.lower().startswith(make.split()[0].lower()): return model
    return (make + " " + model).strip()


###############################################################################################################################
# XMP (jpeg APP1, tif 700-as tag, psd)

def xmp_meta(b):
    """ XMP csomag -> dict: created, modified, software, artist, title """
    out = {}
    try:
        x = b.decode('utf-8', 'replace') if isinstance(b, bytes) else b
        def get(name):
            m = re.search(r'%s\s*=\s*"([^"]*)"' % name, x) or re.search(r'<%s>\s*([^<]*?)\s*</%s>' % (name, name), x)
            if m: return m.group(1).strip()
            # dc:creator, dc:title: rdf:Seq/Alt listaelem - csak az elemen belul (az ures <rdf:Alt/> utan ne a kovetkezo elemet)
            m = re.search(r'<%s>(.*?)</%s>' % (name, name), x, re.S)
            m = m and re.search(r'<rdf:li[^>]*>([^<]*)</rdf:li>', m.group(1))
            return m.group(1).strip() if m else ""
        out['created'] = iso_local(get('xmp:CreateDate')) or iso_local(get('photoshop:DateCreated')) or iso_local(get('exif:DateTimeOriginal'))
        out['modified'] = iso_local(get('xmp:ModifyDate'))
        out['software'] = get('xmp:CreatorTool')
        out['artist'] = get('dc:creator')
        out['title'] = get('dc:title')
    except Exception:
        pass
    return out


def image_info(exif, xmp):
    """ EXIF + XMP -> (letrehozas, modositas, forras, szerzo, cim, program, eszkoz); az EXIF az elsodleges """
    exif, xmp = exif or {}, xmp or {}
    created, src_c = exif.get('created'), "exif"
    if not created: created, src_c = xmp.get('created'), "xmp"
    modified, src_m = exif.get('modified'), "exif"
    if not modified: modified, src_m = xmp.get('modified'), "xmp"
    return (created, modified, date_source(created, modified, src_c, src_m), exif.get('artist') or xmp.get('artist', ""),
            exif.get('title') or xmp.get('title', ""), exif.get('software') or xmp.get('software', ""), device(exif.get('make'), exif.get('model')))
