#! /usr/bin/python3.11

import sys
sys.stdout.reconfigure(line_buffering=True)

import os
import re
import stat
import traceback

from testpdf import parse_pdf
from testjpeg import testjpeg
from testgif import testgif
from testtif import testtif
from testpsd import testpsd
from testpng import testpng
from testzip import testzip
from testole import testole,support_ole
from testsav import testsav
from testdxf import testdxf
from testdwg import testdwg
from testwmf import testwmf,testemf
from testmp4 import testmp4,mp4_kind


###############################################################################################################################
##############################################  PDF  ##########################################################################
###############################################################################################################################

def testpdf(d):
  try:
    c,errcnt=parse_pdf(d)
#    if c==None: return 10 # not pdf file
    return errcnt
  except:
    print("PDF.open-Exception!!! %s" % (traceback.format_exc()))
    return 10


###############################################################################################################################
#############################################  detect  ########################################################################
###############################################################################################################################

# kiterjesztes -> a felismert tartalom tipusa(i); ha nem egyezik, csak figyelmeztetunk (lehet, hogy csak rossz a neve)
ooxml_ok=("ole",)   # a jelszoval vedett docx/xlsx/pptx valojaban OLE file
ext_types={"jpg":("jpg",),"jpeg":("jpg",),"png":("png",),"gif":("gif",),"tif":("tif",),"tiff":("tif",),"psd":("psd",),"psb":("psd",),
  "pdf":("pdf",),"sav":("sav",),"zsav":("sav",),"wmf":("wmf",),"emf":("emf",),"doc":("doc",),"dot":("doc",),"xls":("xls",),"xlt":("xls",),"ppt":("ppt",),"pps":("ppt",),
  "docx":("docx",)+ooxml_ok,"docm":("docx",)+ooxml_ok,"xlsx":("xlsx",)+ooxml_ok,"xlsm":("xlsx",)+ooxml_ok,"pptx":("pptx",)+ooxml_ok,
  "odt":("odt",),"dxf":("dxf",),"dwg":("dwg",),"heic":("heic",),"heif":("heic",),"avif":("heic",),
  "mp4":("mp4","mov"),"m4v":("mp4","mov"),"m4a":("mp4","mov"),"m4b":("mp4","mov"),"3gp":("mp4","mov"),"3g2":("mp4","mov"),"mov":("mov","mp4"),"qt":("mov","mp4"),"ods":("ods",),"odp":("odp",),"spv":("spv",),"epub":("epub",),"jar":("jar",),
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
    if len(d)<256: return -1,"small"
    if d[0:4] in [b'MM\x00\x2A',b'II\x2A\x00']: return testtif(d+f.read()),"tif"

#    if len(d)<4096: return -1,"small"

    if d[0]==0x50 and d[1]==0x4b and d[2]==3 and d[3]==4: return testzip(d+f.read())#,"zip"
    if d[0:4]==b'8BPS' and d[4]==0 and d[5] in [1,2]: return testpsd(d+f.read()),"psd"  # 2: PSB

    if d[0:4] in [b'$FL2',b'$FL3']: return testsav(d+f.read()),"sav"
    if support_ole and d[0]==0xD0 and d[1]==0xCF and d[2]==0x11 and d[3]==0xE0 and d[4]==0xA1 and d[5]==0xB1: return testole(d+f.read())#,"ole"
    if d[0]==0xff and d[1]==0xd8 and d[2]==0xff and d[3]>=0xC0: return testjpeg(d+f.read()),"jpg"
    if d.find(b'%PDF-',0,32)>=0: return testpdf(d+f.read()),"pdf"

#    if d[0:4]==b'{\\rt': return testrtf(d),"rtf"

    if d[0:4]==b'AC10' and d[4:6].isdigit(): return testdwg(d+f.read()),"dwg"   # -1: nem tamogatott DWG verzio
    kind=mp4_kind(d)   # ISO Base Media: mp4, mov, m4a, 3gp, heic...
    if kind: return testmp4(d+f.read()),kind
    # DXF: binaris, vagy szoveges "0 / SECTION" kezdettel (elotte lehet 999-es megjegyzes)
    if d.startswith(b'AutoCAD Binary DXF\r\n\x1a\x00') or re.match(rb'[ \t]*(999[ \t]*\r?\n[^\n]*\n[ \t]*)?0[ \t]*\r?\nSECTION', d): return testdxf(d+f.read()),"dxf"

    return -1,"???"


###############################################################################################################################
##############################################  main  #########################################################################
###############################################################################################################################

def testdir(path):
    cnt=0
    for n in os.listdir(path):
        nn=os.path.join(path,n)
        print("\n\n==================== %s ======================\n"%(nn))
        try:
          s=os.stat(nn)
          if stat.S_ISDIR(s.st_mode):
            cnt+=testdir(nn)
          else:
            with open(nn,"rb") as f: res,ext=testfile(f,s.st_size,nn)
            if res>0:
                print("__result=BAD:",ext,nn)
                cnt+=1
            if res==0:
                print("__result=OK:",ext,nn)
                cnt+=1
            if res<0:
                print("__result=DUNNO:",ext,nn)
                cnt+=1
        except Exception as e:
          print("Cannot open file:",repr(e))
    return cnt

#testdir("/2/")
testdir("png/")
exit()

f=open("/dev/sda","rb")
for line in open("files.list","r"):
# file 0x8264A000 1225172 935/982 JPG 'DSC_0018 R-2.jpg'
    ll=line.split(" ",5)
    print("\n\n==================== %s ======================\n"%(ll[5].strip()))
    print(ll)
    fpos=int(ll[1],16)
    size=int(ll[2])
    if size>2048*1024*1024: continue #######
#    if size>2048*1024: continue #######
    f.seek(fpos)
    res,ext=testfile(f,size)
    print((res,ext))
    if res>0:
        f.seek(fpos)
        open("save/"+ll[1]+"."+ext,"wb").write(f.read(size))

