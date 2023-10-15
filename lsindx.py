#! /usr/local/bin/pypy3

BLKSIZE=4096


def parseindx(data):
    def getint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=False)
    def getsint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=True)
    # header
    fixo=getint(4,2)
    fixl=getint(6,2)
    logfile=getint(8,8)
    vcn=getint(16,8)
    # nodeheader:  24- (16 bytes)
    offs=getint(24,4)  # 64 (0x40) szokott lenni
    size=getint(28,4)
    eofs=getint(32,4)
    flag=getint(36,4)
    print(offs,size,eofs,flag,vcn)
    # 0x28-0x40  fixup?

    # The question is what happened to the original data that was located at offset 510 in both of those sectors?
    # https://dtidatarecovery.com/ntfs-master-file-table-fixup/
    if fixl-1==len(data)//512:  # fixl should be 9 for 4096 byte blocks (8 sectors + reference)
        fix=data[fixo:fixo+2]
        for i in range(fixl-1):
            fix1=data[i*512+510:i*512+512]
            fix2=data[i*2+fixo+2:i*2+fixo+4]
#            print(i,fix,fix1,fix2)
            if fix==fix1: data=data[:i*512+510]+fix2+data[i*512+512:] # replace fix1 by fix2
            else: print("CRC error!",i*512)

    o=24+offs
#    e=24+eofs
    e=8+size
    if e>len(data): return # WTF
    while o<e:
        fref=getint(o,8) & 0x0000FFFFFFFFFFFF 
        s=getint(o+8,2)    # Index value size
        n=getint(o+10,2)   # Index key data size  (gyakorlatilag o+n+16 mutat a filenev vegere)
        fl=getint(o+12,4)  # Index value flags
#        print("\t",o,s,n,fl,data[o+n+16:o+s].hex())
        if n+16>=0x52:
            t=getint(o+16+16,8) # Last modification date and time
            t//=10000000;
            t-=11644473600;
            fs=getint(o+16+48,8) & 0x0000FFFFFFFFFFFF # File size
            nl=getint(o+16+64,1) #  Contains the number of characters without the end-of-string character
            ns=getint(o+16+65,1) #  Namespace of the name string
#            if nl>0:
            fn=data[o+0x52:o+0x52+nl*2].decode("utf_16_le",errors="ignore") #  Contains an UTF-16 little-endian without end-of-string character
            print("\t",o,s,n,fl,t,fref,ns,fn,fs)
        o+=s

f=open("/home/mentes-pd16g/raw2.img","rb")
while True:
    data=f.read(BLKSIZE)
    if not data or len(data)<BLKSIZE: break
    if data[0:4]!=b'INDX': continue
    parseindx(data)
