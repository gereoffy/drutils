#! /usr/local/bin/pypy3

import os
import pickle

BLKSIZE=4096
MFTSIZE=1024

filedata={}
mftpos={}
dirlist={}
dirmap={}


def parse_MFT(data,fpos=0,debug=False):
    def getint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=False)
    def getsint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=True)

    mft=getint(44,4) # elvileg itt tarolja az mft szamat
    seqnum=getsint(16,2)
    refcnt=getsint(18,2)
    o=getint(20,2)
    flags=getint(22,2) # https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#mft_entry_flags
    size=getint(24,4)  # Used entry size
    size2=getint(28,4) # Total entry size
    if size2!=MFTSIZE or size<32 or size>size2 or size>len(data):
        if debug: print("MFT#%d: bad size %d/%d/%d"%(mft,size,size2,len(data)))
        return # bad size

    print("MFT#%d: fpos=0x%X  size=%d/%d offs=0x%X flags=0x%X seq=%d refcnt=%d"%(mft,fpos,size,size2,o,flags,seqnum,refcnt))
    if not (flags&1): return  # MFT_RECORD_IN_USE
    
    # The question is what happened to the original data that was located at offset 510 in both of those sectors?
    # https://dtidatarecovery.com/ntfs-master-file-table-fixup/
    fixo=getint(4,2)
    fixl=getint(6,2)
    if (fixl-1) != (size2//512): print("BAD fixup size!",fixl,fixo) ; return
    fix1=data[510:512]
    fix2=data[512+510:512+512]
#    print("  fixup offs=0x%X size=%d data:"%(fixo,fixl), data[fixo:o].hex(' '), "Sect1:", fix1.hex(' '), "Sect2:", fix2.hex(' ') )  #   47136   fixup offs=0x30 size=3
    if data[fixo:fixo+2]==fix1: # and fix1==fix2:
        if fix1!=fix2: print("BAD fixup for 2nd sector!") ; return
        data=data[:510] + data[fixo+2:fixo+4] + data[512:512+510] + data[fixo+4:fixo+6] + data[1024:] # fuck ms!
    else:
        print("BAD fixup, NOT patching sector data...") ; return

    tt=0    # datetime
    fs=0    # filesize
    fnev=''
    parent=-1
    while o+4<=size:
        t=getsint(o,4)         # attrib type!  https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#6-the-attributes
        if t==-1: break        # end tag
        if o+16>size: break    # not enough data to parse header
        l=getint(o+4,4)        # attrib size
        nl=data[o+9]           # namelen
        res=data[o+8]          # resident flag
        no=getint(o+10,2)      # name offset
        aflags=getint(o+12,2)  # attrib flags:  also 8 bit: compression   0x4000=encrypted   0x8000=sparse
        aid=getint(o+14,2)     # An unique identifier to distinguish between attributes that contain segmented data.
        name=data[o+no:o+no+nl*2].decode("utf_16_le",errors="ignore") #  Contains an UTF-16 little-endian without end-of-string character
        if debug: print("  attr type=0x%02X len=%d aflags=0x%04X resident=%d aid=%d start=0x%X name='%s'"%(t,l,aflags,res,aid,o+16,name));
        if l<=0 or o+l>size: break # invalid len

        if res==0:  # resident
            attsize=getint(o+16,4)
            attoffs=getint(o+16+4,2)
#            if t==0x10: # $STANDARD_INFORMATION
#                tt=getint(o+attoffs+8,8) # Last modification date and time
#                print("TIME:",tt)
            if t==0x30: # $FILE_NAME
                parent=getint(o+attoffs,4)
                tt=getint(o+attoffs+16,8) # Last modification date and time
                tt=(tt//10000000)-11644473600    # windows time -> unix time:
                if not fs: fs=getint(o+attoffs+48,8) # File size  NEM MINDIG JO!!!
                namelen=data[o+attoffs+64] # name length in chars
                namespc=data[o+attoffs+65] # namespace (0=posix 1=win 2=dos 3=same) # https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#641-namespace
                nameoff=o+attoffs+66
                name=data[nameoff:nameoff+namelen*2].decode("utf_16_le",errors="ignore") #  Contains an UTF-16 little-endian without end-of-string character
                if debug: print("NAME: ",nameoff,namelen,namespc,name,parent,"SIZE:",fs,"TIME:",tt)
                if namespc<2 or not fnev: fnev=name
        else:
            fs=getint(o+16+32,8) & 0x0000FFFFFFFFFFFF # Data size (or file size)  0x18 0000 0000 A1EA;

        o+=l


    if not (flags&2): # When this flag is set the file entry represents a directory (that contains sub file entries)
        entry=(fs,fnev,tt,mft,parent)
        try:
            filedata[fs].append(entry)
        except:
            filedata[fs]=[entry]
    else:
        dirlist[mft]=(fnev,parent)

    return



def parseindx(data,fpos=0,debug=False):
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
    if debug: print(offs,size,eofs,flag,vcn)
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
            else: print("CRC error!",i*512) ; return
    else: print("Bad fixup size: %d (for %d sectors)"%(fixl,len(data)//512)) ; return

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
            if fpos and not parent in mftpos: mftpos[parent]=fpos #; print("MFT#%d = 0x%X"%(parent,fpos))
            t=getint(o+16+16,8)   # Last modification date and time
            t//=10000000;
            t-=11644473600;
            fs=getint(o+16+48,8) & 0x0000FFFFFFFFFFFF # File size
            fl=getint(o+16+56,4) #  File attribute flags  0x10=DIR  0x80=normal
            nl=getint(o+16+64,1) #  Contains the number of characters without the end-of-string character
            ns=getint(o+16+65,1) #  Namespace of the name string
#            if nl>0:
            fn=data[o+0x52:o+0x52+nl*2].decode("utf_16_le",errors="ignore") #  Contains an UTF-16 little-endian without end-of-string character
            if debug: print("\t",o,s,n,"0x%X"%fl,t,"%d/%d"%(fref,parent),ns,fn,fs)
            if not (fl&0x10000000): # directory?
                entry=(fs,fn,t,fref,parent)
                try:
                    filedata[fs].append(entry)
                except:
                    filedata[fs]=[entry]
            else:
                try:
                    old=dirlist[fref] # check if we already has it
                    new=(fn,parent)
                    if old!=new: print("MFT!=INDX mismatch:",old,new)
                except:
                    dirlist[fref]=(fn,parent) # new entry!

        o+=s

f=open("/home/mentes-pd16g/raw2.img","rb")

# find FILE (MFT) entries:
#fpos=0xC0000000 ; f.seek(fpos)
fpos=0; f.seek(fpos)
while True:
    data=f.read(MFTSIZE)
    if not data or len(data)<MFTSIZE: break # EOF
    if data[0:4]==b'FILE': parse_MFT(data,fpos)
    fpos+=len(data)

# find INDX (dir) entries:
fpos=0 ; f.seek(fpos)
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

