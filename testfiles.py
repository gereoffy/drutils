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
##############################################  WMF  ##########################################################################
###############################################################################################################################

def testwmf(data,debug=False):
    def getint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=False)
    def getsint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=True)
    # SpecialHeader:
    magic=data[0:4]
    if debug: print(magic,data[4:6])  # b'\xd7\xcd\xc6\x9a' b'\x00\x00'
    x1=getsint(6,2)
    y1=getsint(8,2)
    x2=getsint(10,2)
    y2=getsint(12,2)
    dpi=getint(14,2)
    rvd=getint(16,4)
    crc=getint(20,2)
    if debug: print(x1,y1,x2,y2,dpi,rvd,crc) # 0 0 1359 1360 96 0 22382
    # Header:
    p=22
    ftyp=getint(p,2) # MetafileType
    hsize=getint(p+2,2)
    vers=getint(p+4,2)
    size=getint(p+6,4)
    objs=getint(p+10,2)
    maxr=getint(p+12,4)
    memb=getint(p+16,2)
    if debug: print(ftyp,vers,hsize,size,objs,maxr,memb) # 1 verison=768 hsize=9 size=985 objs=7 maxr=658 memb=0
    if debug: print((len(data)-p)/2) # ==size
    p+=2*hsize
    # Records:
    num=0
    while p+6<=len(data):
        size=getint(p,4)
        func=getint(p+4,2)
        if debug: print(func,size)
        if size>maxr:
            print("Invalid record size: %d > %d"%(size,maxr))
            return 2
        p+=size*2
        if func==0:
            if p==len(data): return 0  # pont a vegere ertunk!
            break
        num+=1
    print("WMF: total %d records read, %d bytes left"%(num,len(data)-p))
    return 1


###############################################################################################################################
#############################################  detect  ########################################################################
###############################################################################################################################

# kiterjesztes -> a felismert tartalom tipusa(i); ha nem egyezik, csak figyelmeztetunk (lehet, hogy csak rossz a neve)
ooxml_ok=("ole",)   # a jelszoval vedett docx/xlsx/pptx valojaban OLE file
ext_types={"jpg":("jpg",),"jpeg":("jpg",),"png":("png",),"gif":("gif",),"tif":("tif",),"tiff":("tif",),"psd":("psd",),"psb":("psd",),
  "pdf":("pdf",),"sav":("sav",),"zsav":("sav",),"wmf":("wmf",),"doc":("doc",),"dot":("doc",),"xls":("xls",),"xlt":("xls",),"ppt":("ppt",),"pps":("ppt",),
  "docx":("docx",)+ooxml_ok,"docm":("docx",)+ooxml_ok,"xlsx":("xlsx",)+ooxml_ok,"xlsm":("xlsx",)+ooxml_ok,"pptx":("pptx",)+ooxml_ok,
  "odt":("odt",),"dxf":("dxf",),"dwg":("dwg",),"ods":("ods",),"odp":("odp",),"spv":("spv",),"epub":("epub",),"jar":("jar",),
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
    if len(d)<256: return -1,"small"

    if d[0:6]==b'\xd7\xcd\xc6\x9a\x00\x00': return testwmf(d+f.read()),"wmf" # may be very small...
    if d[0:6] in [b'GIF87a', b'GIF89a']: f.seek(0); return testgif(f),"gif"
    if d[0]==0x89 and d[1:4]==b'PNG' and d[4]==0x0D and d[5]==0x0A and d[6]==0x1A: return testpng(d+f.read()),"png"
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

