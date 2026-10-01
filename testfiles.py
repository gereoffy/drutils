#! /usr/bin/python3

import sys
sys.stdout.reconfigure(line_buffering=True)

import os
import re
import stat
import traceback

# New PDF parser: https://github.com/gereoffy/pdfparse3
try:    from pdfparse3 import parse_pdf
except: from testpdf import parse_pdf

from testjpeg import testjpeg
from testgif import testgif
from testtif import testtif
from testpsd import testpsd
from testpng import testpng
from testzip import testzip
from testole import testole
from testsav import testsav
from testdxf import testdxf
from testdwg import testdwg
from testwmf import testwmf,testemf
from testmp4 import testmp4,mp4_kind
from testavi import testavi
from testmp3 import testmp3,frame_header
from testswf import testswf,swf_kind
from testasf import testasf,asf_kind
from testmkv import testmkv,mkv_kind


###############################################################################################################################
#############################################  detect  ########################################################################
###############################################################################################################################

# kiterjesztes -> a felismert tartalom tipusa(i); ha nem egyezik, csak figyelmeztetunk (lehet, hogy csak rossz a neve)
ooxml_ok=("ole",)   # a jelszoval vedett docx/xlsx/pptx valojaban OLE file
ext_types={"jpg":("jpg",),"jpeg":("jpg",),"png":("png",),"gif":("gif",),"tif":("tif",),"tiff":("tif",),"psd":("psd",),"psb":("psd",),
  "pdf":("pdf",),"sav":("sav",),"zsav":("sav",),"wmf":("wmf",),"emf":("emf",),"doc":("doc",),"dot":("doc",),"xls":("xls",),"xlt":("xls",),"ppt":("ppt",),"pps":("ppt",),
  "docx":("docx",)+ooxml_ok,"docm":("docx",)+ooxml_ok,"xlsx":("xlsx",)+ooxml_ok,"xlsm":("xlsx",)+ooxml_ok,"pptx":("pptx",)+ooxml_ok,
  "odt":("odt",),"dxf":("dxf",),"dwg":("dwg",),"heic":("heic",),"heif":("heic",),"avif":("heic",),
  "mp4":("mp4","mov"),"m4v":("mp4","mov"),"m4a":("mp4","mov"),"m4b":("mp4","mov"),"3gp":("mp4","mov"),"3g2":("mp4","mov"),"mov":("mov","mp4"),"avi":("avi",),"mp3":("mp3",),"swf":("swf",),"wmv":("asf",),"wma":("asf",),"asf":("asf",),"mkv":("mkv","webm"),"mka":("mkv","webm"),"mk3d":("mkv",),"webm":("webm","mkv"),"qt":("mov","mp4"),"ods":("ods",),"odp":("odp",),"spv":("spv",),"epub":("epub",),"jar":("jar",),
  "zip":("zip","jar","apk","docx","xlsx","pptx","vsdx","ooxml","odt","ods","odp","odg","epub","spv")}

def testfile(f,size,fnev):
    res,ext=detect_and_test(f,size,fnev)
    fext=os.path.splitext(fnev)[1].lower().lstrip(".")
    if fext in ext_types and ext not in ext_types[fext] and ext not in ("small","zero"):
        if ext=="???": print("WARNING! content not recognized as .%s"%(fext))
        else: print("WARNING! .%s file, but content is %s"%(fext,ext))
    return res,ext

def detect_and_test(f,size,fnev):
    d=f.read(4096)
    # csupa nulla file: a tartalom elveszett (pl. lefoglalt, de soha ki nem irt terulet visszaallitas utan)
    if d and not d.strip(b'\x00'):
        n=len(d)
        while True:
            b=f.read(1<<20)
            if not b:
                print("ERROR! file contains only zero bytes (%d bytes)"%(n))
                return 10,"zero"
            if b.strip(b'\x00'): break
            n+=len(b)
        f.seek(len(d))
    # WMF: placeable (Aldus) vagy sima METAHEADER (tipus 1/2, 9 word-os header, verzio 0x100/0x300). Lehet nagyon kicsi is.
    if d[0:4]==b'\xd7\xcd\xc6\x9a' or (d[0:4] in [b'\x01\x00\x09\x00',b'\x02\x00\x09\x00'] and d[4:6] in [b'\x00\x01',b'\x00\x03']): return testwmf(d+f.read()),"wmf"
    if d[0:4]==b'\x01\x00\x00\x00' and d[40:44]==b' EMF': return testemf(d+f.read()),"emf"
    # a GIF es a PNG is lehet nagyon kicsi (ikonok, 1 pixeles kepek)
    if d[0:6] in [b'GIF87a', b'GIF89a']: f.seek(0); return testgif(f),"gif"
    if d[0:8]==b'\x89PNG\r\n\x1a\n': return testpng(d+f.read()),"png"
    if d[0:3]==b'ID3' and d[3] in (2,3,4): return testmp3(d+f.read(),fname=fnev),"mp3"   # a csak ID3 tagbol allo csonka file is kicsi lehet
    if len(d)<256: return -1,"small"
    if d[0:4] in [b'MM\x00\x2A',b'II\x2A\x00']: return testtif(d+f.read(),fname=fnev),"tif"

#    if len(d)<4096: return -1,"small"

    if d[0]==0x50 and d[1]==0x4b and d[2]==3 and d[3]==4: return testzip(d+f.read(),fname=fnev)#,"zip"
    if d[0:4]==b'8BPS' and d[4]==0 and d[5] in [1,2]: return testpsd(d+f.read()),"psd"  # 2: PSB

    if d[0:4] in [b'$FL2',b'$FL3']: return testsav(d+f.read(),fname=fnev),"sav"
    if d[0]==0xD0 and d[1]==0xCF and d[2]==0x11 and d[3]==0xE0 and d[4]==0xA1 and d[5]==0xB1: return testole(d+f.read(),fname=fnev)#,"ole"
    if d[0]==0xff and d[1]==0xd8 and d[2]==0xff and d[3]>=0xC0: return testjpeg(d+f.read(),fname=fnev),"jpg"
    if d.find(b'%PDF-',0,32)>=0: return parse_pdf(d+f.read())[1],"pdf"

#    if d[0:4]==b'{\\rt': return testrtf(d),"rtf"

    if d[0:4]==b'AC10' and d[4:6].isdigit(): return testdwg(d+f.read(),fname=fnev),"dwg"   # -1: nem tamogatott DWG verzio
    if d[0:4]==b'RIFF' and d[8:12]==b'AVI ':
        # memoriaba kepezve: a tobb GB-os filmeket sem kell beolvasni (a vizsgalat csak a chunk fejleceket es a kockak elejet nezi)
        import mmap
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m: return testavi(m,fname=fnev),"avi"
    if swf_kind(d): return testswf(d+f.read(),fname=fnev),"swf"
    mk=mkv_kind(d)
    if mk:
        import mmap
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m: return testmkv(m,fname=fnev),mk
    if asf_kind(d):
        import mmap
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m: return testasf(m,fname=fnev),"asf"
    kind=mp4_kind(d)   # ISO Base Media: mp4, mov, m4a, 3gp, heic...
    if kind: return testmp4(d+f.read(),fname=fnev),kind
    # MP3 ID3 tag nelkul: ket egymast koveto ervenyes MPEG audio keret az elejen
    h=frame_header(d,0) if d[0]==0xFF else None
    if h and h[3]+4<=len(d) and frame_header(d,h[3]): return testmp3(d+f.read(),fname=fnev),"mp3"
    # DXF: binaris, vagy szoveges "0 / SECTION" kezdettel (elotte lehet 999-es megjegyzes)
    if d.startswith(b'AutoCAD Binary DXF\r\n\x1a\x00') or re.match(rb'[ \t]*(999[ \t]*\r?\n[^\n]*\n[ \t]*)?0[ \t]*\r?\nSECTION', d): return testdxf(d+f.read(),fname=fnev),"dxf"

    return -1,"???"


###############################################################################################################################
##############################################  main  #########################################################################
###############################################################################################################################

def testone(nn,size=None):
    """ egy file vizsgalata: kiirja a fejlecet, a hibakat es a __result sort. visszaad: 1 (vizsgalt file) """
    print("\n\n==================== %s ======================\n"%(nn))
    try:
        if size is None: size=os.stat(nn).st_size
        with open(nn,"rb") as f: res,ext=testfile(f,size,nn)
        print("__result=%s:"%("BAD" if res>0 else "OK" if res==0 else "DUNNO"),ext,nn)
    except Exception as e:
        print("Cannot open file:",repr(e))
    return 1

def testdir(path):
    cnt=0
    for n in os.listdir(path):
        nn=os.path.join(path,n)
        try:
          s=os.stat(nn)
          if stat.S_ISDIR(s.st_mode):
            print("\n\n==================== %s ======================\n"%(nn))
            cnt+=testdir(nn)
            continue
        except Exception as e:
          print("\n\n==================== %s ======================\n"%(nn))
          print("Cannot open file:",repr(e))
          continue
        cnt+=testone(nn,s.st_size)
    return cnt


###############################################################################################################################
# parhuzamos vizsgalat: a fileokat N folyamat vizsgalja (a GIL miatt a szalak nem futnanak parhuzamosan), a kimenetet
# fileonkent osszegyujtik, es a fo folyamat az eredeti (soros futassal azonos) sorrendben irja ki, a sorok nem keverednek.

def _walk(path):
    """ a testdir sorrendjeben: ("dir", utvonal) / ("file", utvonal, meret) / ("error", utvonal, hiba) """
    for n in os.listdir(path):
        nn=os.path.join(path,n)
        try:
            s=os.stat(nn)
        except Exception as e:
            yield ("error",nn,e)
            continue
        if stat.S_ISDIR(s.st_mode):
            yield ("dir",nn)
            yield from _walk(nn)
        else:
            yield ("file",nn,s.st_size)

def _worker(item):
    import io, contextlib
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        try: testone(item[1],item[2])
        except Exception as e: print("Cannot open file:",repr(e))
    return buf.getvalue()

def testdir_parallel(path,jobs):
    """ mint a testdir, de jobs darab folyamattal. visszaad: a vizsgalt fileok szama """
    import multiprocessing
    items=list(_walk(path))
    files=[it for it in items if it[0]=="file"]
    # fork: a gyerek folyamatok orokoljak a betoltott modulokat (nem futtatjak ujra a foprogramot)
    ctx=multiprocessing.get_context("fork")
    with ctx.Pool(jobs,maxtasksperchild=2000) as pool:
        results=pool.imap(_worker,files,chunksize=4)   # imap: az eredmenyek a bemenet sorrendjeben jonnek
        for it in items:
            if it[0]=="file":
                sys.stdout.write(next(results))
            else:
                print("\n\n==================== %s ======================\n"%(it[1]))
                if it[0]=="error": print("Cannot open file:",repr(it[2]))
    return len(files)


if __name__ == "__main__":
    import argparse
    ap=argparse.ArgumentParser(description="file integrity checker (see FORMATS.md)")
    ap.add_argument("-j","--jobs",type=int,default=1,help="number of parallel worker processes (default: 1)")
    ap.add_argument("paths",nargs="+",help="files or directories to check")
    args=ap.parse_args()
    for p in args.paths:
        if not os.path.isdir(p): testone(p)
        elif args.jobs>1: testdir_parallel(p,args.jobs)
        else: testdir(p)
