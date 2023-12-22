#! /usr/local/bin/pypy3

import os
import pickle

BLKSIZE=4096

filedata={}
mftpos={}
dirlist={}
dirmap={}

def parseindx(data,fpos=0):
    def getint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=False)
    def getsint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=True)
    # header
    fixo=getint(4,2)
    fixl=getint(6,2)
    logfile=getint(8,8)
    vcn=getint(16,8)   # Virtual Cluster Number (VCN) of the index entry
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
    else: print("Bad fixup size: %d (for %d sectors)"%(fixl,len(data)//512))

    o=24+offs
#    e=24+eofs
    e=8+size
    if e>len(data): return # WTF
    while o<e:
#        fref=getint(o,8) & 0x0000FFFFFFFFFFFF 
        fref=getint(o,4)   #  Note that the index value in the MFT entry is only 32-bit of size.
        s=getint(o+8,2)    # Index value size
        n=getint(o+10,2)   # Index key data size  (gyakorlatilag o+n+16 mutat a filenev vegere)
        ifl=getint(o+12,4)  # Index value flags
#        print("\t",o,s,n,fl,data[o+n+16:o+s].hex())
        if n+16>=0x52:
            parent=getint(o+16,4) # Parent file reference
            if fpos and not parent in mftpos: mftpos[parent]=fpos ; print("MFT#%d = 0x%X"%(parent,fpos))
            t=getint(o+16+16,8)   # Last modification date and time
            t//=10000000;
            t-=11644473600;
            fs=getint(o+16+48,8) & 0x0000FFFFFFFFFFFF # File size
            fl=getint(o+16+56,4) #  File attribute flags  0x10=DIR  0x80=normal
            nl=getint(o+16+64,1) #  Contains the number of characters without the end-of-string character
            ns=getint(o+16+65,1) #  Namespace of the name string
#            if nl>0:
            fn=data[o+0x52:o+0x52+nl*2].decode("utf_16_le",errors="ignore") #  Contains an UTF-16 little-endian without end-of-string character
            print("\t",o,s,n,"0x%X"%fl,t,"%d/%d"%(fref,parent),ns,fn,fs)
            if not (fl&0x10000000): # directory?
                entry=(fs,fn,t,fref,parent)
                try:
                    filedata[fs].append(entry)
                except:
                    filedata[fs]=[entry]
            else:
                dirlist[fref]=(fn,parent)

        o+=s

f=open("/home/mentes-pd16g/raw2.img","rb")
fpos=0
while True:
    data=f.read(BLKSIZE)
    if not data or len(data)<BLKSIZE: break # EOF
    if data[0:4]==b'INDX': parseindx(data,fpos)
    fpos+=len(data)

#exit(0)

for k in sorted(dirlist.keys()): print(k,dirlist[k])

def get_path(ref):
    if ref in dirmap: return dirmap[ref]
    oref=ref
    x=[]
    while True:
        try:
            fn,parent=dirlist[ref]
        except:
            x.append("dir__%d"%(ref))
            break
        x.append(fn)
        if ref==parent: break # reached root
        ref=parent
    y="/".join(reversed(x))
    os.makedirs(y, exist_ok=True)
    dirmap[oref]=y
    return y

for k in sorted(filedata.keys()):
    if k<1024: continue
    for fs,fn,t,fref,parent in filedata[k]:
        print(fs,t,"%d/%d"%(fref,parent),'"%s/%s"'%(get_path(parent),fn))

pickle.dump((filedata,dirmap),open("INDEX.pck","wb"))

