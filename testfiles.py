#! /usr/bin/python3.11

import sys
sys.stdout.reconfigure(line_buffering=True)

import os
import stat
import io
import traceback

# jpg/psd/png
from struct import unpack,calcsize
import zlib
import math

# docx/xlsx-hez:
import xml.etree.ElementTree as ET
import zipfile

# pip3 install olefile
try:
  import olefile
  support_ole=True
except:
  support_ole=False

# pip3 install pyreadstat
try:
  import pyreadstat
  support_spss=True
except:
  support_spss=False

# pdf
from testpdf import parse_pdf
from testjpeg import testjpeg


###############################################################################################################################
##############################################  PSD  ##########################################################################
###############################################################################################################################

def decode_rle(data):  # https://raw.githubusercontent.com/psd-tools/packbits/master/src/packbits.py
    """
    Decodes a PackBit encoded data.
    """
    data = bytearray(data) # <- python 2/3 compatibility fix
    result = bytearray()
    pos = 0
    try:
      while pos < len(data):
        header_byte = data[pos]
        if header_byte > 127:
            header_byte -= 256
        pos += 1

        if 0 <= header_byte <= 127:
            result.extend(data[pos:pos+header_byte+1])
            pos += header_byte+1
        elif header_byte == -128:
            pass
        else:
            result.extend([data[pos]] * (1 - header_byte))
            pos += 1

    except:
      pass
    return bytes(result)

def testpsd(data):
    errcnt=0
    
    magic,version,resvd1,resvd2=unpack(">LHHL",data[0:12])
    channels,height,width,depth,color=unpack(">HLLHH",data[12:12+14])
    pos=12+14

    print(magic,version,resvd1,resvd2)
    if magic!=943870035 or version!=1 or resvd1!=0 or resvd2!=0: return 100 # bad header
    
    print(channels,height,width,depth,color)
    print("dimenstion: %d x %d x %d (%d bits)  colorspace=%d"%(width,height,channels,depth,color))

    # Color Mode Data Section 
    l,=unpack(">L",data[pos:pos+4])
    print("Color Mode Data Section",l)
    pos+=4+l

    
    # Image Resources Section
    l,=unpack(">L",data[pos:pos+4])
    print("Image Resources Section",l)
    pos+=4
    p=pos
    pos+=l
    while p<pos:
        # b'8BIM  \x03\xed  \x00\x00  \x00\x00\x00\x10  \x01,\x00\x00'
#        print(p,data[p:p+32])
        magic,ui,nl=unpack(">LHB",data[p:p+7])
#        print(magic,ui,nl,data[p+7:p+7+nl])
        if magic!=943868237: break   #  "8BIM"
        nev=data[p+7:p+7+nl]
        nl+=7
        if nl&1: nl+=1
        p+=nl
        rl,=unpack(">L",data[p:p+4])
        p+=4
        print("\t",ui,nev,rl)
        if rl&1: rl+=1
        p+=rl
    print("image resources: %d bytes left"%(pos-p))
    if pos!=p: errcnt+=1


    # Layer and Mask Information 
    l,l2,lc=unpack(">LLh",data[pos:pos+10])
# Layer and Mask Information 8394 8390 4 2
    print("Layer and Mask Information",l,l2,l-l2,lc)
    p=pos+8+l2
    pos+=l+4
    if l>0:
      # Global layer mask info:
  #    print(p,data[p:p+32])
      l3,ocs=unpack(">LH",data[p:p+6])
      print(l3)
      p+=4+l3
      #  Additional Layer Information:
      while p<pos:
#        print(data[p:p+32])
        magic,key,l1=unpack(">LLL",data[p:p+12])
        print("\t",data[p:p+4], data[p+4:p+8], l1)
        if magic!=943868237: break
#        print(magic,key,l1)
        if l1&1: l1+=1
        if l1&2: l1+=2
        p+=12+l1
      print("layer information: %d bytes left"%(pos-p))
      if pos!=p: errcnt+=1

    # Image Data 
    c,=unpack(">H",data[pos:pos+2])
    pos+=2
#    print(c,data[pos+2:pos+32])
    if c==0: # uncompressed
        pos+=width*(depth//8)*height*channels
    elif c==1: # RLE
        total=0
        lens=[]
        for i in range(height*channels):
            l,=unpack(">H",data[pos:pos+2])
            pos+=2
            total+=l
            lens.append(l)
#            print(l)
        print("%d bytes image data (%d slices) - decoding RLE..."%(total,height*channels))
#        pos+=total
        # decode RLE strips:
        rlecnt=0
        for l in lens:
            d=decode_rle(data[pos:pos+l])
            if len(d)!=width*(depth//8):
                print("RLE slice #%d error filepos: 0x%X"%(rlecnt,pos),len(d),width*(depth//8))
                errcnt+=1
                if errcnt>=10: break
            rlecnt+=1
            pos+=l
    else:
        print("Unsupported compression: ",c)


#    l=unpack(">L",data[pos:pos+4])
#    print(l)
#    pos+=4+l

    print("%d of %d decoded     ===>  %d left"%(pos,len(data),len(data)-pos))
    if pos!=len(data): errcnt+=10

#    print("ERROR! EOF reached before EOI marker!")
#    errcnt+=10
    return errcnt



###############################################################################################################################
##############################################  ZIP  ##########################################################################
###############################################################################################################################


def testxml(data):
    try:
        root = ET.fromstring(data)
        print(root.tag, root.attrib)
#    for child in root:  print(child.tag, child.attrib)
        return 0
    except:
        return 1

def testzip(data):
  errcnt=0
  ext="zip"
  try:
    with zipfile.ZipFile(io.BytesIO(data), mode='r') as zf:
      for z in zf.infolist():
        if z.is_dir() or z.file_size<1024: continue
        if z.flag_bits&1:
          print("ZIP.encrypted: "+str(z.filename))
          continue # return -1 # ezzel ugyse tudunk semmit kezdeni...
        try:
          d=zf.open(z,mode='r').read()
          print(z.filename,z.file_size,len(d))
#          if z.filename.lower().endswith(".xml"): errcnt+=testxml(d)

          if z.filename in ["word/document.xml","word/fontTable.xml","word/settings.xml","word/styles.xml","word/theme/theme1.xml"]: ext="docx"
          if z.filename in ["xl/worksheets/sheet1.xml","xl/styles.xml","xl/theme/theme1.xml","xl/sharedStrings.xml"]: ext="xlsx"
          if z.filename in ["ppt/presentation.xml","ppt/theme/theme1.xml","ppt/slides/slide1.xml","ppt/slideMasters/slideMaster1.xml"]: ext="pptx"
          if z.filename.startswith("outputViewer000"): ext="spv" # contains the output generated from data analytics functions run within SPSS

          if z.filename in ["[Content_Types].xml",
            "word/document.xml","word/fontTable.xml","word/settings.xml","word/styles.xml","word/theme/theme1.xml",
            "xl/worksheets/sheet1.xml","xl/styles.xml","xl/theme/theme1.xml","xl/sharedStrings.xml",
            "ppt/presentation.xml","ppt/theme/theme1.xml","ppt/slides/slide1.xml","ppt/slideMasters/slideMaster1.xml"] or z.filename.startswith("outputViewer000"):
              errcnt+=testxml(d)
        except:
          print("ZIP.read-Exception!!! %s" % (traceback.format_exc()))
          errcnt+=1
  except:
    print("ZIP.open-Exception!!! %s" % (traceback.format_exc()))
    errcnt+=10
  return errcnt,ext


###############################################################################################################################
##############################################  OLE  ##########################################################################
###############################################################################################################################

def P23Decode(value):
    try:
        return value.decode('utf-8',errors="ignore")
    except UnicodeDecodeError as u:
        return value.decode('windows-1252')

def ShortXLUnicodeString(data, isBIFF8):
    cch = data[0]
    if isBIFF8:
        highbyte = data[1]
        if highbyte == 0:
            return P23Decode(data[2:2 + cch])
        else:
            return data[2:2 + cch * 2].decode('utf-16le', errors='ignore')
#            return repr(data[2:2 + cch * 2])
    else:
        return P23Decode(data[1:1 + cch])

def parse_xls(d,debug=False):
  p=0
  macros4Found=0
  isBIFF8=True
  while p+4<=len(d):
    op=d[p]+(d[p+1]<<8)
    l=d[p+2]+(d[p+3]<<8)
    p+=4
#    try:
#      n=xlsOpcodes[op]
#    except:
#      n=""
#    if debug: print("[xls] %04X: %5d  %s"%(op,l,n))

    # BOF record
    if op==0x0809 and l>=8:
        formatcodes = '<HHHH'
        formatsize = calcsize(formatcodes)
        vers, dt, rupBuild, rupYear = unpack(formatcodes, d[p:p+formatsize])
        dBIFFVersion = {0x0500: 'BIFF5/BIFF7', 0x0600: 'BIFF8'}
        isBIFF8 = vers == 0x0600
        dStreamType = {5: 'workbook', 6: 'Visual Basic Module', 0x10: 'dialog sheet/worksheet', 0x20: 'chart sheet', 0x40: 'Excel 4.0 macro sheet', 0x100: 'Workspace file'}
        if dt==0x40: macros4Found+=1
        print('XLS.BOF - %s %s 0x%04x %d' % (dBIFFVersion.get(vers, '0x%04x' % vers), dStreamType.get(dt, '0x%04x' % dt), rupBuild, rupYear) )
#                        if positionBIFFRecord in dSheetNames:
#                            line += ' - %s' % (dSheetNames[positionBIFFRecord])
#                            currentSheetname = dSheetNames[positionBIFFRecord]

    # BOUNDSHEET record
    if op==0x85 and l>=6:
        formatcodes = '<IBB'
        formatsize = calcsize(formatcodes)
        positionBOF, sheetState, sheetType = unpack(formatcodes, d[p:p+formatsize])
        dSheetType = {0: 'worksheet or dialog sheet', 1: 'Excel 4.0 macro sheet', 2: 'chart', 6: 'Visual Basic module'}
        dSheetState = {0: 'visible', 1: 'hidden', 2: 'very hidden', 3: 'visibility=3'}
        if sheetType==1: macros4Found+=1
        sheetName = ShortXLUnicodeString(d[p+6:p+l], isBIFF8)

#                        visibility = ''
#                        if sheetState > 3:
#                            visibility = 'reserved bits not zero: 0x%02x ' % (sheetState & 0xFC)
        visibility = dSheetState.get(sheetState & 3, '0x%02x' % (sheetState & 3))
        print('XLS.Sheet %s, %s : %s' % (dSheetType.get(sheetType, '%02x' % sheetType), visibility, sheetName) )

    p+=l

  return macros4Found



def testole(d):
  errcnt=0
  ext="ole"
  try:
    with olefile.OleFileIO(d) as ole:
        for exctype, msg in ole.parsing_issues:
            print('- %s: %s' % (exctype.__name__, msg))
            errcnt+=1
        meta = ole.get_metadata()
        for i in ole.listdir():
            t=ole.get_type(i[0])
            print(str(ole.get_size(i))+"\t"+str(t)+"\t"+"/".join(i))
            try:
              if t==2: od=ole.openstream(i[0]).read()
            except:
              print("OLE.read-Exception!!! %s" % (traceback.format_exc()))
              errcnt+=1
        if ole.exists('Workbook'):
            ext="xls"
            try:
              macros=parse_xls(ole.openstream('Workbook').read())
            except:
              print("XLS.parse-Exception!!! %s" % (traceback.format_exc()))
              errcnt+=1
        if ole.exists('Catalog'): ext="db"
        if ole.exists('WordDocument'): ext="doc"
        if ole.exists('PowerPoint Document'): ext="ppt"
  except:
    print("OLE.open-Exception!!! %s" % (traceback.format_exc()))
    errcnt+=10
  return errcnt,ext
  
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
##############################################  SPSS  #########################################################################
###############################################################################################################################

def testspss(fnev):
  try:
    df, meta = pyreadstat.read_sav(fnev,disable_datetime_conversion=True)
    return 0
  except:
    print("SPSS.open-Exception!!! %s" % (traceback.format_exc()))
    return 10


###############################################################################################################################
##############################################  PNG  ##########################################################################
###############################################################################################################################

def testpng(data):
  magic=data[0:8] #    137 80 78 71 13 10 26 10
#    print(magic)

  errcnt=0
  try:

    chunks=[]
#    zdata=b''
    clen=0
    ulen=0
    zl=zlib.decompressobj()
    p=8
    while p<len(data):
        l,=unpack(">L",data[p:p+4])
        c=data[p+4:p+8] # chunk name
        print(p,c,l)
        chunks.append(c)
        crc = zlib.crc32(data[p+4:p+8+l])
        ocrc,=unpack(">L",data[p+8+l:p+12+l])
        if crc!=ocrc:
            print("chunk CRC failed")
            errcnt+=1
        if c==b'IDAT':
            zdata=zl.decompress(data[p+8:p+8+l])
#            print(l,len(zdata))
            clen+=l
            ulen+=len(zdata)
        if c==b'IHDR':
            w,h,depth,color,compr,filt,ilace=unpack(">LLBBBBB",data[p+8:p+8+8+5])
            print(w,h,depth,color,compr,filt,ilace)
        #print (crc^ocrc) # print(crc,ocrc)
        p+=12+l

    zdata=zl.flush()
    ulen+=len(zdata)

    if p!=len(data):
        print(len(data)-p,"bytes left")
        errcnt+=1

    if chunks[0]!=b'IHDR' or chunks[-1]!=b'IEND':
        print("missing IDHR/IEND")
        errcnt+=1

    dmap={0:1,2:3,3:1,4:2,6:4}
    bits=depth*dmap.get(color,0) # bits/pixel
    #bits=depth*(1+(color&2)+(color>>2))
    scanlines=(((h+7)//8)*15) if ilace else h             # https://www.w3.org/TR/2003/REC-PNG-20031110/#8Interlace
    rawsize=((w*bits+7)//8)*h + scanlines

    print("Uncompressed data size:",clen,ulen,rawsize,ilace,scanlines)
    if ulen!=rawsize: errcnt+=1

#    if errcnt==0:
#    print("Compressed data size:",clen)
#        udata=zlib.decompress(zdata)

  except Exception as e:
    errcnt+=10
    print(repr(e))

  return errcnt

###############################################################################################################################
#############################################  detect  ########################################################################
###############################################################################################################################

def testfile(f,size,fnev):
    d=f.read(4096)
    if len(d)<4096: return -1,"small"

    if d[0]==0x50 and d[1]==0x4b and d[2]==3 and d[3]==4: return testzip(d+f.read())#,"zip"
    if d[0]==0x89 and d[1:4]==b'PNG' and d[4]==0x0D and d[5]==0x0A and d[6]==0x1A: return testpng(d+f.read()),"png"
    if d[0:4]==b'8BPS' and d[4]==0 and d[5]==1: return testpsd(d+f.read()),"psd"

#    if support_spss and d[0:4]==b'$FL2': return testspss(fnev),"sav"
    if support_ole and d[0]==0xD0 and d[1]==0xCF and d[2]==0x11 and d[3]==0xE0 and d[4]==0xA1 and d[5]==0xB1: return testole(d+f.read())#,"ole"

    if d[0]==0xff and d[1]==0xd8 and d[2]==0xff and d[3]>=0xC0: return testjpeg(d+f.read()),"jpg"
    if d.find(b'%PDF-',0,32)>=0: return testpdf(d+f.read()),"pdf"

#    if d[0:4]==b'{\\rt': return testrtf(d),"rtf"

    return -1,"???"


###############################################################################################################################
##############################################  main  #########################################################################
###############################################################################################################################

def testdir(path):
    cnt=0
    for n in os.listdir(path):
        nn=os.path.join(path,n)
        print("\n\n==================== %s ======================\n"%(nn))
        s=os.stat(nn)
        if stat.S_ISDIR(s.st_mode):
            cnt+=testdir(nn)
        else:
            f=open(nn,"rb")
            res,ext=testfile(f,s.st_size,nn)
            f.close()
            if res>0:
                print("__result=HIBAS:",ext,nn)
                cnt+=1
            if res==0:
                print("__result=OK:",ext,nn)
                cnt+=1
            if res<0:
                print("__result=DUNNO:",ext,nn)
                cnt+=1
    return cnt

testdir("/home/mentes-ikovach/MENTES")
#testdir("/mnt/Kovach2023")
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

