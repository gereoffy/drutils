#! /usr/bin/python3

# https://resources.infosecinstitute.com/topic/pdf-file-format-basic-structure/#gref

import os
import sys
import traceback
import zlib

import base64

def hexdigit(a):
    if a>=0x30 and a<=0x39: return a-0x30
    if a>=0x41 and a<=0x46: return a+10-0x41
    if a>=0x61 and a<=0x66: return a+10-0x61
    return None

# based on https://github.com/py-pdf/pypdf/blob/main/pypdf/filters.py
class LZWDecode:
        def __init__(self, data: bytes) -> None:
            self.STOP = 257
            self.CLEARDICT = 256
            self.data = data
            self.bytepos = 0
            self.bitpos = 0
            self.dict = [b''] * 4096
            for i in range(256):
                self.dict[i] = bytes([i])
            self.reset_dict()

        def reset_dict(self) -> None:
            self.dictlen = 258
            self.bitspercode = 9

        def next_code(self) -> int:
            fillbits = self.bitspercode
            value = 0
            while fillbits > 0:
                if self.bytepos >= len(self.data):
                    return -1
                nextbits = self.data[self.bytepos]
                bitsfromhere = 8 - self.bitpos
                bitsfromhere = min(bitsfromhere, fillbits)
                value |= (
                    (nextbits >> (8 - self.bitpos - bitsfromhere))
                    & (0xFF >> (8 - bitsfromhere))
                ) << (fillbits - bitsfromhere)
                fillbits -= bitsfromhere
                self.bitpos += bitsfromhere
                if self.bitpos >= 8:
                    self.bitpos = 0
                    self.bytepos = self.bytepos + 1
            return value

        def decode(self) -> bytes:
            cW = self.CLEARDICT
            baos = []
            while True:
                pW = cW
                cW = self.next_code()
                if cW == -1:
                    raise BufferError("End of buffer reached without LZW stop code")
                if cW == self.STOP:
                    break
                elif cW == self.CLEARDICT:
                    self.reset_dict()
                elif pW == self.CLEARDICT:
                    baos.append(self.dict[cW])
                else:
                    if cW < self.dictlen:
                        baos.append(self.dict[cW])
                        p = self.dict[pW] + self.dict[cW][:1]
                        self.dict[self.dictlen] = p
                        self.dictlen += 1
                    else:
                        p = self.dict[pW] + self.dict[pW][:1]
                        baos.append(p)
                        self.dict[self.dictlen] = p
                        self.dictlen += 1
                    if (
                        self.dictlen >= (1 << self.bitspercode) - 1
                        and self.bitspercode < 12
                    ):
                        self.bitspercode += 1
            bleft=len(self.data)-self.bytepos
            print("LZW bytesleft=%d  decoded %d -> %d bytes, %d runs"%(bleft, len(self.data),len(b''.join(baos)),len(baos)))
            if bleft>3: raise BufferError("%d bytes left in LZW buffer"%(bleft))
            return b''.join(baos)


def ASCIIHexDecode(d):
    p=0
    pend=len(d)
    data=bytearray()
    while p<pend:
        if d[p]==0x3D: break # EOF
        if d[p]<=32:  # skip whitespace
            p+=1
            continue
        x=hexdigit(d[p])
        p+=1
        if x!=None:
            if p<pend:
                y=hexdigit(d[p])
                if y==None: y=0
                p+=1
            else:
                y=0
            data.append((x<<4)+y)
#        else: break # invalid char
    return data

# special string object
class PDFString():
    def __init__(self,d):
        self.data=d
    def get(self):
        return bytes(self.data)
    # print formatuma:
    def __repr__(self):
        return str(self.data[0:16])

def inflate(d):
    zo=zlib.decompressobj()
    dd=zo.decompress(d)
    dd+=zo.flush()
    if not zo.eof: print("ZLIB: truncated stream? decoded %d/%d bytes"%(len(dd),len(d)))
    return dd

class PDFStream():
    def __init__(self,d,f=None):
        self.data=d
        self.fmt=f
    def decode(self):
        d=self.data
        if self.fmt:
#          try:
            for f in self.fmt:
                if f in [b'/ASCII85Decode',b'/A85']: d=base64.a85decode(d.split(b'~>')[0])  #ValueError: Ascii85 encoded byte sequences must end with b'~>'
                elif f==b'/ASCIIHexDecode': d=ASCIIHexDecode(d)
                elif f==b'/FlateDecode': d=inflate(d)  # d=zlib.decompress(d)
                elif f==b'/LZWDecode': d=LZWDecode(d).decode()
                elif f not in [b'/CCITTFaxDecode',b'/JBIG2Decode',b'/JPXDecode',b'/DCTDecode']:  # picture formats
                    print("STREAM: unsupported format "+str(f))
#          except:
#            print("STREAM: exception while decoding:"+traceback.format_exc())
        return d
    # print formatuma:
    def __repr__(self):
#        return str(self.data[0:16])
        unc=0 #len(self.decode())
        try:
            return "Stream(%d/%d):%s"%(len(self.data),unc,str(b''.join(self.fmt)) )
        except:
            return "Stream(%d/%d)"%(len(self.data),unc)

def parse_pdf_param(d,p,pend):

    while p<pend:

        # 'endobj' utan nem mindig van whitespace... :(
        if p+6<=pend and d[p:p+6]==b'endobj':
            p+=6
            return p,b'endobj'

        c=d[p]
        p+=1
        if c<=32: continue # ignore whitespace

        t=chr(c)

        if c in [0x3C,0x3E] and p<pend and d[p]==c: # <<DICT>>
            p+=1
            return p,t #objs.append(t)

        if c in [41, 62, 91,93, 123,125]:  #  ) > [] {}
            return p,t

        data=bytearray()

        if c==0x25:  # %COMMENT
            if p+4<=pend and d[p:p+4]==b'%EOF':
                p+=4
#                print("EOF!!")
#                return p,None
                return p,b'%%EOF'
            data.append(c) # % jel az elejere!
            while p<pend:
                c=d[p]
                p+=1
                if c==10 or c==13:
                    break
                data.append(c)
            #print(data)
            continue # ignore comment

        if c==0x3C:          # <HEXSTRING>
            while p+1<pend:
                c=d[p]
                p+=1
                if c<=0x20: continue # skip ws/newline
                if c==0x3E: break # > = end of string
                x=hexdigit(c)
                if x==None:
                    print("Invalid HEX")
                    p-=1 # fixme?
                    break
                x2=hexdigit(d[p])
                if x2!=None:
                    p+=1
                else:
                    x2=0  # az utolso nibble hianyozhat is...
                data.append((x<<4)+x2)
            return p,PDFString(data)

        if c==0x28:   # (string)
            in_str=1
            while p+1<pend:
                c=d[p]
                p+=1
                if c==0x28:   # (
                    in_str+=1
                if c==0x29:   # )
                    in_str-=1
                    if in_str<=0: break
                if c!=0x5C:
                    data.append(c)
                    continue
                # backshash!
                x=d[p]
                p+=1
                if   x==0x6E: x=10 # n
                elif x==0x72: x=13 # r
                elif x==0x74: x=9  # t
                elif x==0x62: x=8  # b
                elif x==0x66: x=12 # f
#                elif x in [0x28,0x29,0x5C]: x=x # ( ) backshash
#                elif x==10 or x==13: # multiple lines
                elif x>=0x30 and x<=0x39: # ddd code
                    try:
                        x=int(d[p-1:p+2],8)
                        p+=2
                    except:
                        pass
            return p,PDFString(data)

        if c==0x2F:  # /name
            data.append(c) # / jel az elejere!
            while p+3<pend:
                c=d[p]
#                if c<0x21 or c>0x7E: break
                if c<=0x20 or c in [40,41, 60,62, 91,93, 123,125, 47, 37]: break  #  () <> [] {} / %
                if c==0x23:          #    #xx (hex)
                    x=hexdigit(d[p])
                    x2=hexdigit(d[p+1])
                    if x!=None and x2!=None:
                        c=(x<<4)|x2
                        p+=2
                p+=1
                data.append(c)
            return p,bytes(data)

        else:
            # read BODY
            while p<pend:
                data.append(c)
                c=d[p] # next char
                if c<=0x20 or c in [40,41, 60,62, 91,93, 123,125, 47, 37]:  #  () <> [] {} / %  = whitespace/separator
                    break
                p+=1
            try:
                return p,int(data)
            except:
                return p,bytes(data)

    return p,None # EOF


# b'/Filter', '[', b'/ASCII85Decode', b'/FlateDecode', ']
def objs_value(objs,name):
  try:
    i=objs.index(name)
    i+=1
    d=objs[i]
    if d=='[':
        d=[]
        i+=1
        while objs[i]!=']':
            d.append(objs[i])
            i+=1
        return d
    else:
        return [d]
  except:
    return None


def parse_pdf_obj(d,p,pend,stop=None):
    objs=[]
    stream=None
    while p<pend:
        p,data=parse_pdf_param(d,p,pend)
        if data==None: break  # EOF
        objs.append(data)
        if data==b'%%EOF': break  # %%EOF
        if data==stop: break      # endobj

        if data==b'startxref':
#            print("Xref: %d bytes left"%(pend-p))
            q,data=parse_pdf_param(d,p,pend)
            try:
                xo=int(data)
#                print("Xref: offset=%d !"%(xo))
                objs.append(data)
                return q,objs,stream
            except:
                print("Xref: INVALID offset format")

        # handle embedded image:
        if data in [b'ID',b'BI',b'EI']: print("STREAM: embedded image !!! "+str(objs))
#        if data==b'ID' and b'BI' in objs:

        # handle embedded stream:
        if data==b'stream':
            try:
                fi=objs.index(b'/Length')
                stream_len=int(objs[fi+1])
                if objs[fi+3]==b'R': stream_len=-stream_len # referenced object
            except:
                stream_len=0
            filt=objs_value(objs,b'/Filter')
#            if filt: filt=b''.join(filt)
            # 0D 0A 65 │ 6E 64 73 74 │ 72 65 61 6D │ 0D 0A
            if d[p] in [9,32]: p+=1 # skip whitepace after 'stream'
            if d[p] in [13,10]: # skip CR/LF
                if d[p]==13 and d[p+1]==10: p+=1
                p+=1
            # 'p' points to stream data!
            q=d.find(b'endstream',p)
            if q<0:
                print("STREAM: missing endstream!")
            else:
                # ez nem annyira jo otlet, van olyan file ahol a 0D 0A a vege a streamnek de csak a 0A a newline, a 0D meg adat!
#                if d[q-1] in [13,10]:  # skip CR/LF
#                    q-=1
#                    if d[q]==10 and d[q-1]==13: q-=1
                # 'q' points to end of stream data!
#                print("STREAM DATA  %s  0x%X - 0x%X  %d/%d%s"%(str(b'---' if not filt else b''.join(filt)), p,q,q-p,stream_len,"  !!!" if (q-p)<stream_len else ""))
                if q>p:
                    if stream_len>(q-p): print("STREAM: invalid length / endstream inside stream? %d/%d 0x%X-0x%X"%(stream_len,q-p,p,q))
                    if stream_len<(q-p)-3:
                        if stream_len>0: print("STREAM: invalid length / too long! %d/%d 0x%X-0x%X"%(stream_len,q-p,p,q))
                        stream_len=q-p  # ha a stream_len nem jo, akkor az endstream poziciojat vesszuk figyelembe!
                    stream=PDFStream(d[p:p+stream_len],filt)
                    objs.append(stream)
                else:
                    print("STREAM: missing data (%d) 0x%X"%(stream_len,p))
                p=q

    return p,objs,stream


def parse_pdf(d,debug=False):
  errcnt=0
  content=[]
  try:
    pend=len(d)

    p=d.find(b'%PDF-',0,1024)
    if p<0: p=d.find(b'%FDF-',0,1024)
    if p<0: return None,99 # "not pdf"
    while p<pend and d[p]!=10 and d[p]!=13 and p<1024: p+=1
    q=p
    while p<pend and (d[p]==10 or d[p]==13) and p<1024: p+=1
    if p>=pend or d[p]!=37: # EOF vagy % jel
        print("bad pdf header! p=%d"%(p))
#        errcnt+=1
#        p=q
#    else:
    newline=d[q:p]
    if debug: print("newline:",newline,len(newline))
    # skip comment:
    q=p
    if d[p]==37:
        while p<pend and d[p]!=10 and d[p]!=13 and p<1024: p+=1
        while p<pend and (d[p]==10 or d[p]==13) and p<1024: p+=1
    if debug and p>q: print("comment:",d[q:p],p-q)


#  38990 b'\n' 1
#      4 b'\n\n' 2
#   7363 b'\r' 1
#  12341 b'\r\n' 2

    encrypt=0

    # xref ?  de igazabol ez nekunk nem is kell, ugyse hasznaljuk... :)
    q=d.rfind(b'startxref',p) # len(d)-4096)
    if q>0:
        oend=q
        q+=9
        while q<pend and d[q]<=32: q+=1 # skip whitespace
        o=q
        while q<pend and not d[q] in [10,13]: q+=1
        if debug: print('XREF: offset='+str(d[o:q]))
        try:
            o=int(d[o:q])
            while q<pend and d[q]<=32: q+=1 # skip whitespace
            if d[q:q+5]==b'%%EOF':
                if pend>q+7:
                    print('XREF: %d bytes left after EOF'%(pend-(q+5)))
                    if pend>=q+4096: errcnt+=1
                pend=q+5 # update pend... (shit after EOF, should not be parsed)
            else:
                print('XREF: missing EOF!')
                errcnt+=5
            # parse it!
            if o<p or o>=oend:
                # invalid offset, find xref...
                o=d.rfind(b'xref',p,oend) # a header vege es a startxref kezdte kozott keresunk visszafele...
                print('XREF: offset2='+str(o))
                errcnt+=1 # ???
            q,objs,stream=parse_pdf_obj(d,o,oend,stop=b'endobj')
            if debug: print("XREF: "+str(objs))
            if b'/Encrypt' in objs:
                try:
                    encrypt=int(objs_value(objs,b'/Encrypt')[0])
                except:
                    encrypt=-1
                if debug: print("CRYPT: "+str(encrypt))
            if objs[0]!=b'xref' and b'/XRef' in objs:
                dd=stream.decode()
                if debug: print("XREF binary:",dd.hex(' '))
                # dd = binary xref table
        except:
            print('XREF: exception!!! '+traceback.format_exc())
            errcnt+=10
    else:
        print('XREF: NOT FOUND!!!')
        errcnt+=10


    # ignore garbage before first obj
    q=p
    nl=True # elvileg a sor elejen vagyunk most, a komment utan.
    while p<pend-5 and p<1024:
        if nl and 0x30<=d[p]<=0x39: break  # number after newline
        nl=d[p] in [10,13]
        p+=1
    if p>q: print("Ignoring initial garbage:",d[q:p])


    pagecnt=0
    objsnum=0
    pagenum=None
    dom={}
    uriobjid=-1
    oid=0
    streamname="pdfstream.dat"

    while p<pend-5:

        while p<pend and d[p]<=0x20: p+=1  # ignore whitespace before obj
        objp=p

        p,objs,stream=parse_pdf_obj(d,p,pend,stop=b'endobj')
        if not objs: break # EOF
        if debug: print(objs)

        if len(objs)>=3 and objs[2]==b'obj':
            try:
                oid=int(objs[0])
                ogen=int(objs[1])
                dom[oid]=(objp,p) #objs
            except:
                print("INVALID object id!")
                errcnt+=1

            if encrypt==oid:
                if debug: print("CRYPT: "+str(objs[3:]))
                print("CRYPT: V="+str(objs_value(objs,b'/V'))+" len="+str(objs_value(objs,b'/Length'))+" cfm="+str(objs_value(objs,b'/CFM')) )


            try:
              if stream and not encrypt:
                dd=stream.decode()

                if objs_value(objs,b'/Type')==[b'/EmbeddedFile']:
                    dd=stream.decode()
                    ll=objs_value(objs,b'/Length')
                    print("FILESTREAM.size=%d/%s"%(len(dd),str(ll)))
                    if debug: open("PDF.filestream.raw","wb").write(dd)
                    content.append((dd,streamname)) # fixme filename

                if b'/ObjStm' in objs: # ebben lehet /URI elrejtve...
#                    print("OBJSTREAM(%d): %s"%(len(dd),bytes(dd[0:32])))
#                    for m in [b'http://',b'HTTP://',b'https://',b'HTTPS://',b'/URI']:
#                        mp=dd.find(m)
#                        if mp>=0: print("OBJSTREAM: embedded URL found: "+str(dd[mp:mp+64]))
                    try:
                        offs=int(objs_value(objs,b'/First')[0])
                        onum=int(objs_value(objs,b'/N')[0])
                        if debug: print("OBJSTREAM.offset=%d num=%d"%(offs,onum))
                        objsnum+=onum
                    except:
                        offs=0
                    pp,oo,ss=parse_pdf_obj(dd,offs,len(dd))
                    if debug:
                        print("OBJSTREAM<-",dd)
                        print("OBJSTREAM->",oo)
                    objs=oo # innentol ezt vizsgaljuk! az eredeti obj-ben ugyis csak Length, Filter, stream szokott lenni...
                    stream=None
            except:
              print("STREAM-Exception!!! %s" % (traceback.format_exc()))
              errcnt+=1

#            if oid==uriobjid and type(objs[3])==PDFString:
            if len(objs)>3 and type(objs[3])==PDFString:
                uri=objs[3].get()
#                if oid==uriobjid or b'script' in uri or b'http' in uri:
#                    print("OBJSTREAM.URI.obj="+str(uri))

            # [29, 0, b'obj', '<', b'/Type', b'/Action', b'/S', b'/URI', b'/URI', 30, 0, b'R', '>', b'endobj']
            # find /URI in object:
            i=0
            while not encrypt:
                try:
                    i=objs.index(b'/URI',i)
                    i+=1
#                    print(type(objs[i]))
#                    print(objs[i])
#                    if type(objs[i])==PDFString: print("OBJSTREAM.URI="+str(objs[i].get()))
                    if type(objs[i])==int: uriobjid=objs[i]
                except:
                    break

            # find FIle attachment in object:
            if b'/Filespec' in objs:
              i=0
              while not encrypt:
                try:
                    i=objs.index(b'/F',i)
                    i+=1
#                    print(type(objs[i]))
#                    print(objs[i])
                    if type(objs[i])==PDFString: print("FILESTREAM.name="+str(objs[i].get()))
                    streamname=objs[i].get().decode("utf-8",errors="ignore")
                    if len(content)>0 and content[-1][1]=="pdfstream.dat":
                        content[-1]=(content[-1][0],streamname) # hu de gany
                        streamname="pdfstream.dat"
#                    if type(objs[i])==int: uriobjid=objs[i]
                except:
                    break

            # find Javascript
            js=objs_value(objs,b'/JS')
            if js:
                try:
                    js=js[0].get()
                except:
                    pass
##                print("JSCR: "+str(js))
##                content.append((js,"pdfstream.js"))

#            if objs_value(objs,b'/Page'):
#                pagecnt+=1
#            print(objs_value(objs,b'/Type'))
            if objs_value(objs,b'/Type')==[b'/Page']: pagecnt+=1
#            if [b'/Type',b'/Page'] in objs: pagecnt+=1

            if objs_value(objs,b'/Type')==[b'/Pages']:
                pagenum=objs_value(objs,b'/Count')

        elif not objs[0] in [b'xref',b'startxref',b'%%EOF']:
            print("INVALID object type: "+str(objs[0]))
            errcnt+=1

  except:
    print("PDFparse-Exception!!! %s" % (traceback.format_exc()))
    errcnt+=10

  if debug: print(dom)
#  oids=list(dom.keys())
#  oids.sort()
#  print(oids)
#  print(words)
  print("PDF: %d/%s pages, %d+%d objs"%(pagecnt,str(pagenum),len(dom),objsnum))

  return content,errcnt


if __name__ == '__main__':
#  for n in sys.argv[1:]:
  path=sys.argv[1]
  fl=[path]
  if not os.path.isfile(path):
    fl=[]
    for n in os.listdir(path): fl.append(path+"/"+n)

  for fn in fl:
    try:
      with open(fn,"rb") as f:
        print("=================== %s ====================="%(fn))
        cont,ret=parse_pdf(f.read(),True)
        print("ERRORS=%d"%(ret))
        if ret: os.rename(fn,"hibas/"+fn.split("/")[-1])
#        ret=parse_pdf(f.read())
#        if ret: print(ret)
#        if ret: print("=================== %s ====================="%(fn))
#        print(str(ret)+"\t"+fn)
#        d=path+"/"+str(ret)
#        try:
#            os.symlink(fn,d+"/"+n)
#        except:
#            os.mkdir(d)
#            os.symlink(fn,d+"/"+n)
    except:
      print("Exception!!! %s" % (traceback.format_exc()))
#      pass

#    print(PDFiD2String(ret,False,False))

