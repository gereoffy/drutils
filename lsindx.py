#! /usr/local/bin/pypy3

import os
import sys
import json
import time
import struct
import pickle

BLKSIZE=4096
MFTSIZE=1024

SCANCHUNK=1024*1024          # egyszerre ennyit olvas az eszkozrol (512 tobbszorose, es nagyobb mint SCANMAXREC!)
SCANPROGRESS=1024*1024*1024  # ennyi byte-onkent egy progress karakter az stdout-ra (M=mft I=indx 0=ures .=egyeb)
SCANLINE=64                  # ennyi progress karakter utan uj sor (statisztikaval)
SCANALIGN=512                # a FILE/INDX/NTFS rekordokat ennyire igazitva keresi
SCANMAXREC=65536             # legnagyobb elfogadott rekordmeret, ennyi atfedessel olvas (blokkhataron atlogo rekordok)
SCANCHECKPOINT=1024*1024*1024 # ennyi olvasas utan menti a folytatashoz szukseges allapotot
SCANFILE="SCAN.dat"          # a talalt FILE/INDX/boot rekordok nyersen: fpos(8)+meret(4)+data
SCANPOS="SCAN.pos"           # checkpoint (json): meddig jutott a scan, es mekkora volt ekkor a SCANFILE

part_start=0 #0x7000+0xE00 #63*512
# az eszkozt/image-et a --scandisk kapcsoloval kell megadni, a SCAN.pos-ban eltarolja

filedata={}
dirlist={}
dirmap={}
mftfiles={}

# start of INDX entries data, as retrieved from INDX and MFT records:
mftpos={}
idxpos={}


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
            size1=getint(o+16+24,8) & 0x0000FFFFFFFFFFFF # Allocated data size (or allocated length).
            size2=getint(o+16+32,8) & 0x0000FFFFFFFFFFFF # Data size (or file size)  0x18 0000 0000 A1EA;
            # decode runs:
            runso=getint(o+16+16,2) # Contains an offset relative from the start of the MFT attribute
            compr=getint(o+16+18,2) # Contains the compression unit size as 2^(n) number of cluster blocks
            rundata=data[o+runso:o+l] #.split(b'\xff\xff\xff\xff')[0]
            runs=[]
            r_cluster=0 ; r_total=0
            while runso<l:
                rl=data[o+runso] ; runso+=1
                if rl==0: break # done
                r_size=getsint(o+runso,rl&15) ; runso+=rl&15 ; r_total+=r_size
                r_delta=getsint(o+runso,rl>>4) ; runso+=rl>>4 ; r_cluster+=r_delta
                runs.append((r_cluster if r_delta else 0, r_size))
            if t==0x80 and nl==0: # $DATA (file)
                fs=size2
                if debug:  print("DATA: start=0x%X size=%d/%d/%d runs=%d compr=0x%X flags=0x%X %s"%(runs[0][0], BLKSIZE*r_total,size1,size2, len(runs), compr, flags, "OK" if BLKSIZE*r_total==size1 else "BAD"), rundata.hex(' '))
                if fnev and flags==1 and compr==0 and fs and BLKSIZE*r_total==size1 and BLKSIZE*r_total<1024*1024*1024: mftfiles[mft]=(fnev,parent,fs,tt,runs)
                elif debug: print("DATA: skipping...") # TODO: implement mft reference lookup... (0x20 attr)
            elif t==0xA0: # $INDEX_ALLOC (dir)
                mftpos[mft]=BLKSIZE*runs[0][0] # direntry

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
            if fpos and not parent in idxpos:
                idxpos[parent]=fpos
                if parent in mftpos: print("MFT#%d = 0x%X  vs.  0x%X    offs=0x%X"%(parent,fpos,mftpos[parent],fpos-mftpos[parent]))
                elif debug: print("MFT#%d = 0x%X  not in MFT"%(parent,fpos))
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

# 1. menet: a teljes eszkoz egyszeri vegigolvasasa nagy blokkokban, a FILE (MFT) es INDX
#    rekordokat nyersen kiirjuk a SCANFILE-ba:  fpos (8 byte) + meret (4 byte) + data
#    Megszakadas eseten a SCANPOS alapjan onnan folytatja, ahol az utolso checkpoint volt.
# 2. menet: a SCANFILE-bol dolgozik a parse_MFT es parseindx (a lemezt mar nem kell olvasni).

USAGE="""usage:
  %(p)s --scandisk <device|image>   scan the disk, create/resume %(sf)s
  %(p)s [--restore [--delete-from-device]]
        parse %(sf)s, rebuild the tree, write INDEX.pck
        --restore             copy the files with intact MFT records from the device (read-only)
        --delete-from-device  ZERO the clusters of the restorable files ON THE DEVICE!"""%{"p":sys.argv[0],"sf":SCANFILE}

def load_scanpos(device=None):
    try:
        with open(SCANPOS) as fp: st=json.load(fp)
    except FileNotFoundError:
        return {"device":device,"pos":0,"outsize":0,"done":False} if device else None
    if device and st["device"]!=device:
        sys.exit("%s egy masik eszkozhoz tartozik (%s)! torold a %s es %s fileokat az ujrakezdeshez."%(SCANPOS,st["device"],SCANFILE,SCANPOS))
    return st

def save_scanpos(st):
    with open(SCANPOS+".tmp","w") as fp: json.dump(st,fp)
    os.replace(SCANPOS+".tmp",SCANPOS) # atomi csere, hogy megszakadaskor se legyen felig irt checkpoint

def recsize(buf,i,sig):
    # a rekord merete a sajat headerebol (ha ertelmetlen, az alapertelmezett meret)
    if sig==b'FILE': n=int.from_bytes(buf[i+28:i+32],"little") ; default=1024     # allocated entry size
    elif sig==b'INDX': n=int.from_bytes(buf[i+32:i+36],"little")+24 ; default=4096 # allocated index node size + 24 byte header
    else: return 512 # boot sector
    return n if SCANALIGN<=n<=SCANMAXREC and n&(n-1)==0 else default

def scan_device(device):
    assert SCANCHUNK%SCANALIGN==0 and SCANCHUNK>SCANMAXREC
    device=os.path.abspath(device)
    st=load_scanpos(device)
    if st["done"]: print("SCAN: %s mar kesz (%s)."%(SCANFILE,device),file=sys.stderr) ; return
    if st["outsize"] and (not os.path.exists(SCANFILE) or os.path.getsize(SCANFILE)<st["outsize"]):
        sys.exit("A %s hianyzik vagy rovidebb, mint a %s szerint kellene! torold mindkettot az ujrakezdeshez."%(SCANFILE,SCANPOS))
    f=open(device,"rb")   # CSAK OLVASAS!
    devsize=f.seek(0,2) # blokkeszkoznel az os.path.getsize() 0-t adna
    out=open(SCANFILE,"ab")
    out.truncate(st["outsize"])  # az utolso checkpoint utan irt (esetleg felig kiirt) rekordok eldobasa
    out.seek(st["outsize"])
    base=st["pos"]  # a buf elejenek pozicioja az eszkozon; minden ennel elorebb kezdodo rekord mar fel van dolgozva
    if base: print("SCAN: resume at 0x%X (%d MB)"%(base,base>>20),file=sys.stderr)
    f.seek(base)
    buf=b''
    lastcp=base
    t0=time.time() ; p0=base
    cnt={b'FILE':0,b'INDX':0,b'NTFS':0}
    marks={}                  # progress: GB index -> "M"/"I"/"." (ami nincs benne, az csupa 0 volt)
    shown=sgb=base//SCANPROGRESS  # a kovetkezo kiirando progress karakter GB indexe (sgb: ahonnan most indultunk)
    rpos=base                 # olvasasi pozicio
    zero=bytes(SCANCHUNK)
    def progress(upto):
        nonlocal shown
        while shown<upto:
            if (shown-sgb)%SCANLINE==0: sys.stdout.write("%8d GB "%(shown*SCANPROGRESS>>30))
            sys.stdout.write(marks.pop(shown,"0"))
            shown+=1
            if (shown-sgb)%SCANLINE==0 or shown*SCANPROGRESS>=devsize:
                dt=time.time()-t0
                sys.stdout.write("  %d/%d GB  %.0f MB/s  FILE=%d INDX=%d NTFS=%d\n"%(min(shown*SCANPROGRESS,devsize)>>30,devsize>>30,
                    (min(shown*SCANPROGRESS,devsize)-p0)/(1<<20)/max(dt,0.001),cnt[b'FILE'],cnt[b'INDX'],cnt[b'NTFS']))
        sys.stdout.flush()
    while True:
        data=f.read(SCANCHUNK)
        eof=len(data)<SCANCHUNK
        if data!=zero[:len(data)]: # nem ures blokk: a nem ures reszet tartalmazo GB-ok legalabb "."
            for g in range(rpos//SCANPROGRESS,(rpos+len(data)-1)//SCANPROGRESS+1):
                seg=data[max(g*SCANPROGRESS-rpos,0):(g+1)*SCANPROGRESS-rpos]
                if seg!=zero[:len(seg)]: marks.setdefault(g,".")
        rpos+=len(data)
        buf+=data  # az elozo korbol atvett atfedes + az uj blokk
        limit=len(buf) if eof else len(buf)-SCANMAXREC  # csak az ez elott kezdodo rekordokat nezzuk, a tobbi a kovetkezo korre marad
        for sig,so in ((b'FILE',0),(b'INDX',0),(b'NTFS    ',3)):  # boot sector: "NTFS    " a 3. bajttol
            i=buf.find(sig,so)
            while 0<=i and i-so<limit:
                j=i-so
                if j%SCANALIGN==0:
                    n=recsize(buf,j,sig[:4])
                    if j+n<=len(buf): # csak a lemez vegen csonka rekord marad ki
                        out.write(struct.pack("<QI",base+j,n)) ; out.write(buf[j:j+n])
                        cnt[sig[:4]]+=1
                        g=(base+j)//SCANPROGRESS
                        if sig==b'FILE': marks[g]="M"
                        elif sig==b'INDX' and marks.get(g)!="M": marks[g]="I"
                i=buf.find(sig,i+1)
        buf=buf[limit:] ; base+=limit
        progress((devsize+SCANPROGRESS-1)//SCANPROGRESS if eof else base//SCANPROGRESS) # a base elotti GB-ok mar keszek
        if eof or base-lastcp>=SCANCHECKPOINT:
            out.flush() ; os.fsync(out.fileno())
            st.update(pos=base,outsize=out.tell(),done=eof)
            save_scanpos(st)
            lastcp=base
        if eof: break
    out.close()
    f.close()
    print("SCAN: kesz.",file=sys.stderr)

def read_scanfile():
    with open(SCANFILE,"rb") as sf:
        while True:
            hdr=sf.read(12)
            if len(hdr)<12: break
            fpos,rsize=struct.unpack("<QI",hdr)
            yield fpos,sf.read(rsize)

args=sys.argv[1:]
if len(args)==2 and args[0]=="--scandisk":
    scan_device(args[1])
    sys.exit(0)
opt_restore="--restore" in args
opt_delete="--delete-from-device" in args
if set(args)-{"--restore","--delete-from-device"}: sys.exit(USAGE)

st=load_scanpos()
if not st or not os.path.exists(SCANFILE):
    sys.exit("Nincs %s ebben a konyvtarban. Eloszor a lemezt kell vegigolvasni:\n\n%s"%(SCANFILE,USAGE))
if not st["done"]:
    sys.exit("A %s meg nem teljes (%d MB-ig jutott). Folytatas:\n  %s --scandisk %s"%(SCANFILE,st["pos"]>>20,sys.argv[0],st["device"]))
device=st["device"]

# NTFS boot sectorok (az elso a particio elejen, a tartalek a particio utolso szektoraban):
for fpos,data in read_scanfile():
    if data[3:11]!=b'NTFS    ': continue
    def getint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=False)
    def recsz(x,clu): return clu*x if x<128 else 1<<(256-x)  # pozitiv: klaszterben, negativ: 2^-x bajt
    bps=getint(11,2) ; spc=getint(13,1) ; spc=spc if spc<=128 else 1<<(256-spc)
    total=getint(40,8) ; clu=bps*spc
    print("BOOT at 0x%X: sector=%d cluster=%d MFTrec=%d INDXrec=%d volume=%d MB MFT@LCN %d  =>  part_start=0x%X (ha elso)"%(
        fpos,bps,clu,recsz(getint(64,1),clu),recsz(getint(68,1),clu),total*bps>>20,getint(48,8),fpos),
        " / 0x%X (ha tartalek)"%(fpos-total*bps) if fpos>=total*bps else "")

# find FILE (MFT) entries:
for fpos,data in read_scanfile():
    if data[0:4]==b'FILE': parse_MFT(data,fpos)

# find INDX (dir) entries:
for fpos,data in read_scanfile():
    if data[0:4]==b'INDX': parseindx(data,fpos)

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

# a kis fajlok szuloihez is legyen utvonal a dirmap-ben (indxrename.py hasznalja):
for k in filedata:
    for fs,fn,t,fref,parent in filedata[k]: get_path(parent)

pickle.dump((filedata,dirmap),open("INDEX.pck","wb"))

# --restore / --delete-from-device nelkul az eszkozt meg sem nyitjuk, --delete-from-device nelkul csak olvasasra!
if opt_restore or opt_delete: f=open(device,"r+b" if opt_delete else "rb")

# restore files:
if opt_restore:
  for mft in mftfiles:
    fnev,parent,fs,tt,runs = mftfiles[mft]
    fn=get_path(parent)+"/"+fnev
    print("COPY %d bytes to %s  (%d runs)"%(fs,fn,len(runs)))
    with open(fn,"wb") as fo:
        for ro,rl in runs:
            if not ro: fo.write(bytes(BLKSIZE*rl)) ; continue # sparse run
            f.seek(part_start+BLKSIZE*ro)
            fo.write(f.read(BLKSIZE*rl))
        fo.truncate(fs)
    if tt: os.utime(fn, (tt,tt))

# delete files:
if opt_delete:
  for mft in mftfiles:
    fnev,parent,fs,tt,runs = mftfiles[mft]
    fn=get_path(parent)+"/"+fnev
    print("DELETE %d bytes of %s  (%d runs)"%(fs,fn,len(runs)))
    for ro,rl in runs:
        if not ro: continue # sparse run: nincs mit torolni (es a boot szektort se nullazzuk!)
        f.seek(part_start+BLKSIZE*ro)
#### WARNING !!! this line ZEROES all the recovered files in the source image !!! use with CAUTION!!! ####
        f.write(bytes(BLKSIZE*rl))
