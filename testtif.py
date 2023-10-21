#!/usr/bin/python3


tagnames={}
try:
    for line in open("tiff.csv","rt"):
        td,th,tn=line.strip().split("\t",2)
        tagnames[int(td)]=tn
except: pass

tiffcompress={
   1:"UNCOMPRESSED",
   2:"CCITTRLE",
   3:"CCITTFAX3",
   4:"CCITTFAX4",
   5:"LZW",
   6:"OJPEG",
   7:"JPEG",
   8:"ADOBE_DEFLATE",
   32766:"NEXT",
   32771:"CCITTRLEW",
   32773:"PACKBITS",
   32809:"THUNDERSCAN",
   32895:"IT8CTPAD",
   32896:"IT8LW",
   32897:"IT8MP",
   32898:"IT8BL",
   32908:"PIXARFILM",
   32909:"PIXARLOG",
   32946:"DEFLATE",
   32947:"DCS",
   34661:"JBIG",
   34676:"SGILOG",
   34677:"SGILOG24",
   34712:"JP2000"}


def testtif(data):
    magic=data[0:2]
    def getint(i,l,s=False): return int.from_bytes(data[i:i+l],byteorder=("little" if magic==b'II' else "big"),signed=s)
    ifd=getint(4,4)
    print(magic,getint(2,2),ifd)
    if getint(2,2)!=42: return 100 # bad magic
    typmap={1:"BYTE",2:"ASCII",3:"SHORT",4:"LONG",5:"RATIONAL",6:"SBYTE",7:"UNDEFINE",8:"SSHORT",9:"SLONG",10:"SRATIONAL",11:"FLOAT",12:"DOUBLE"}
    typlen={1:1,2:1,3:2,4:4,5:8,6:1,8:2,9:4,10:8,11:4,12:8}
    comp=None
    ok=False
    while True:
      if ifd<8 or ifd+2>len(data): return 10 # bad ifd pointer
      num=getint(ifd,2)
      tagvalues={}
      for i in range(num):
        p=ifd+2+12*i
        tag=getint(p,2)   # The tag identifier
        typ=getint(p+2,2) # The scalar type of the data items
        cnt=getint(p+4,4) # The number of items in the tag data
        ofs=getint(p+8,4) # The byte offset to the data items
        size=typlen.get(typ,1)*cnt
        if size<=4: ofs=p+8 # hack
        value="#%d"%ofs
        if typ==2: value=data[ofs:ofs+cnt-1] # ascii
        elif typ in [1,3,4]: value=[ getint(ofs+i*typlen[typ],typlen[typ]) for i in range(cnt) ]
        elif typ in [6,8,9]: value=[ getint(ofs+i*typlen[typ],typlen[typ],True) for i in range(cnt) ]
        elif typ==5: value="%d/%d"%(getint(ofs,4),getint(ofs+4,4))
        elif typ==10: value="%d/%d"%(getint(ofs,4,True),getint(ofs+4,4,True))
        tagvalues[tag]=value
        if tag==259: comp=value=tiffcompress.get(value[0],value) # compression
        print("ifd#%d: "%i,tag,tagnames.get(tag,"%d"%tag),typmap.get(typ,"%d"%typ),"x",cnt,"=",str(value)[:100])
      # end of IFD
      if 273 in tagvalues and 279 in tagvalues and 258 in tagvalues:
        datasize=sum(tagvalues[279]) # StripByteCounts
        bits=sum(tagvalues[258])
        pixels=tagvalues.get(256,[1])[0]*tagvalues.get(257,[1])[0]
        rawsize=tagvalues.get(257,[1])[0] * ((tagvalues.get(256,[1])[0]*bits+7)//8)
        print("TIFF %s bits=%d  datasize=%d  rawsize=%d  pixels=%d"%(str(comp),bits,datasize,rawsize, pixels ))
        if comp and datasize<=len(data)-(8+2+12+4): ok=True
        if comp=="UNCOMPRESSED" and datasize!=rawsize: ok=False # bad size
      ifd=getint(ifd+2+12*num,4)
      print("Next IFD:",ifd,comp)
      if ifd==0: return 0 if ok else 1 # OK
    return 10 # no END ifd?


if __name__ == "__main__":
#    with open("tif/Griffmulde_R15080534.tif", 'rb') as f: testtif(f.read())
#    with open("tif/M1401d433.tif", 'rb') as f: testtif(f.read())
#    with open("tif/500542_tif_0.tif", 'rb') as f: testtif(f.read())
    with open("tif/600DQ_421740_tif_1.tif", 'rb') as f: testtif(f.read())
