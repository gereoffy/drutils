#! /usr/bin/python3

import os
import lznt1

blksize=4096
part_start=0x100000

def decode_run1(data,compr,debug=False,tryfix=False,size=0,runs=[]):
    total=0
    cluster=0
    i=0
    pad=0
    if debug: print(data.hex(' '))
    lastx=0
    lastl=0
    while i<len(data):
        x=data[i]
        if debug: print("  run#%d: (p=%d) %02X   "%(len(runs),i,x),"end" if x==0 else data[i+1:i+11].hex(' ') )
        if x==0: return -1,total # OK!
        if (x&15)==0 or (x&15)>4 or (pad and compr and x!=1): # a padding mindig 01+pad elvileg...
            if tryfix and compr:
                #   run#17: (p=46) 05    00 11 0a 0a 01 06 11 0a 0a 01
                print("TRYtoFIX1!!!!")
                if pad:
                    # probaljuk ezt:  01 pad
                    errpos,errval=decode_run1(data[i+2:],compr,debug=False) # a padding utani jonak tunik?
                    if errpos==-1 and errval>0:
                        # jonak tunik! patcheljunk.
                        data=data[:i]+bytes([0x01,pad])+data[i+2:]
                        print(data.hex(' '))
                        continue # retry!
                elif i+10<=len(data) and data[i+3]==1 and data[i+5]==0x11: # ha a kovetkezo 2 blokk padding es data lesz, 1-1 byte merettel:
#  run#10: (p=30) 11    =?? 2f         a ??-t kell kitalalni, de a kovetkezo data blokkban elvileg az lesz a cluster deltaja is
#                 01    02
#                 11    0f +0e
#                 01    01
                    nextl=data[i+7]
                    print("Trying l=%d pad=%d"%(nextl,data[i+4]))
                    errpos,errval=decode_run1(bytes([0x11,nextl])+data[i+2:],compr,debug=False)
                    if errpos==-1 and errval>0:
                        # jonak tunik! patcheljunk.
                        print("looks good!  totals: %d+%d=%d vs %d"%(total,errval,total+errval,size))
                        data=data[:i]+bytes([0x11,nextl])+data[i+2:]
                        print(data.hex(' '))
                        continue # retry!
                elif i+5<len(data) and data[i+3]==1 and data[i+5]==0: # ez az utolso data block!
#ERROR at 6: bad ssize
#21 29 33 0a 01 07 06 00 29 01 0b 00 00 00 00 00
#  run#0: (p=0) 21    29 33 0a 01 07 06 00 29 01 0b
#  run#1: (p=4) 01    07 06 00 29 01 0b 00 00 00 00
#   pad=7  l=7
#  run#2: (p=6) 06    00 29 01 0b 00 00 00 00 00
#TRYtoFIX!!!!
#145 262144/227328/227328 64 bad ssize 65536
                    nextl=size-total # mennyi van meg hatra?
                    print("ez az utolso data block!  next pad=%d  guessed len=%d"%(data[i+4],nextl))
                    if 0<nextl<=0x80 and (nextl%compr)==0:
                        nextl-=data[i+4] # padding lejon belole!
                        data=data[:i]+bytes([0x11,nextl])+data[i+2:]
                        print(data.hex(' '))
                        continue # retry!

            return i,"bad ssize"
        if (x>>4)>8: return i,"bad csize"
        if i+1+(x>>4)+(x&15)>len(data): return i,"overflow"
#        l=data[i+1]
#        if (x&15)>1: l+=data[i+2]<<8
#        if (x&15)>2: l+=data[i+3]<<16
        ii=i+1+(x&15)
        l=int.from_bytes(data[i+1:ii],byteorder="little",signed=True) # 1..3 bytes
        delta= 0 if (x>>4)==0 else int.from_bytes(data[ii:ii+(x>>4)],byteorder="little",signed=True)
        cluster+=delta

        if debug: print("     l:",l,"  delta:",delta,"  cluster:",cluster)

        if l<=0: return i,"wrong size"

        if compr:
          if (x>>4)!=0:  # nem sparse block
            # data block!
            if pad!=0: return i,"pad nonzero" # print("WTF? pad=",pad)
            pad=(l%compr) # tomoritett meret clusterben
            if pad: pad=compr-pad # ha nem 0, akkor kell padding!
            lastl=l
          else:
            if pad==0: return i,"pad zero" #  print("WTF? pad=",pad)
            if debug: print("   pad=%d  l=%d"%(pad,l))
            if pad!=l:
                if tryfix and x==0x01:
                    # try to fix padding :)
                    print("TRYtoFIX2!!!!")
                    #   run#11: (p=33) 01    02 21 1f 8e 00 01 01 11 7f 1f
                    #            fix1: 01   pad 11 1f 8e | 00 01 01 11 7f 1f
                    errpos,errval=decode_run1(bytes([0x21])+data[i+3:],compr,debug=False)
                    if errpos==-1 and errval>0:
                        # jonak tunik! patcheljunk.
                        print("looks good (0x21)!  totals: %d+%d=%d vs %d"%(total+pad,errval,total+pad+errval,size))
                        data=data[:i]+bytes([x,pad,0x21])+data[i+3:]
                        print(data.hex(' '))
                        continue # retry!
                    errpos,errval=decode_run1(bytes([0x11])+data[i+3:],compr,debug=False)
                    if errpos==-1 and errval>0:
                        # jonak tunik! patcheljunk.
                        print("looks good (0x11)!  totals: %d+%d=%d vs %d"%(total+pad,errval,total+pad+errval,size))
                        data=data[:i]+bytes([x,pad,0x11])+data[i+3:]
                        print(data.hex(' '))
                        continue # retry!
                return i,"pad mismatch"
            pad=0

        total+=l
        i+=1+(x>>4)+(x&15)
#        runs.append((cluster if delta else 0, l))
        runs.append((part_start+blksize*cluster if delta else 0, blksize*l))
        lastx=x
    return i,"overflow"


def decode_runs(data,sizes,compr,mft=-1,fnev=None):
#    print(sizes,compr,data[:32])
#    p=data.find(b'\xff\xff\xff\xff\x82yG\x11')
    p=data.find(b'\xff\xff\xff\xff')
    if p>0: data=data[:p]
    p=data.find(b'[ZoneTransfer]\r\n')
    if p>0: data=data[:p]
    s=int(sizes.split("/")[0])//4096
    runs=[]
    pos,total=decode_run1(data,compr//4096,runs=runs)
    if pos>=0:
        print("ERROR at %d:"%(pos),total)
        runs2=[]
        pos,total=decode_run1(data,compr//4096,debug=True,tryfix=True,size=s,runs=runs2)
        if pos<0 and total==s:
            print("__status=FIXED")
            runs=runs2
        else: print("__status=CantFIX")
#    print(sizes,s,total,compr,data)
    else:
        if total==s: print("__status=GOOD")
        else: print("__status=BadSIZE")
    print(mft,sizes,s,total,compr,fnev)
    print(runs)
    return runs


MFT={}

# __MFT=47678,size=1024 offs=0x38  flags=0x1  refcnt=2
# __fnev=KZSGEK~4.DOC
# __fnev=községeknépesség_2020-04-02_vegl (2) CSB (2).docx
# __run#0=124544729088,2420736
# __run#1=0,4096
# __file=47678,47671,1650888116,3894608,DOCX


def fnscore(s):
    try:
        ss=s.encode("us-ascii")
        p=s.find('~')
        x=0
        if p>0:
            x=-10 if s[p+1:p+2].isnumeric() else -5
        if s==s.upper(): x-=3
        return x
    except:
        return 10 # ekezetes

def parse_MFT(data,mft,debug=False):

    def getint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=False)
    def getsint(i,l): return int.from_bytes(data[i:i+l],byteorder="little",signed=True)

    seqnum=getsint(16,2)
    refcnt=getsint(18,2)
    o=getint(20,2)
    flags=getint(22,2) # https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#mft_entry_flags
    size=getint(24,4)  # Used entry size
    size2=getint(28,4) # Total entry size
    if debug: print("MFT#%d: size=%d/%d offs=0x%X flags=0x%X seq=%d refcnt=%d"%(mft,size,size2,o,flags,seqnum,refcnt))
    # __MFT=19009,size=488/1024 offs=0x38  flags=0x1  seq=2 refcnt=2
    if not (flags&1): return  # MFT_RECORD_IN_USE
    if size2<1024 or size<32 or size>size2 or size>len(data):
        print("MFT#%d: bad size %d/%d/%d"%(mft,size,size2,len(data)))
        return # bad size
    
    # The question is what happened to the original data that was located at offset 510 in both of those sectors?
    # https://dtidatarecovery.com/ntfs-master-file-table-fixup/
    fixo=getint(4,2)
    fixl=getint(6,2)
    fix1=data[510:512]
    fix2=data[512+510:512+512]
#    print("  fixup offs=0x%X size=%d data:"%(fixo,fixl), data[fixo:o].hex(' '), "Sect1:", fix1.hex(' '), "Sect2:", fix2.hex(' ') )  #   47136   fixup offs=0x30 size=3
    if data[fixo:fixo+2]==fix1: # and fix1==fix2:
        if fix1!=fix2: print("BAD fixup for 2nd sector!")
        data=data[:510] + data[fixo+2:fixo+4] + data[512:512+510] + data[fixo+4:fixo+6] + data[1024:] # fuck ms!
    else:
        print("BAD fixup, NOT patching sector data...")

#        MFT[i]={"p":p,"s":s,"d":d,"n":fnev,"r":runs,"t":vv[6],"f":f,"cs":cs}

    tt=0    # datetime
    fnev=''
    parent=-1
    MFT[mft]={"flags":flags,"c":[]}

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
        
        if res==0:  # resident                # TODO: read date/time
            attsize=getint(o+16,4)
            attoffs=getint(o+16+4,2)
#            print("! resident attr  size=%d  offs=%d"%(attsize,attoffs))
            # filename  https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#64-the-file-name-attribute
            if t==0x30: 
                parent=getint(o+attoffs,4)
                nameoff=o+attoffs+66
                namelen=data[o+attoffs+64] # name length in chars
                namespc=data[o+attoffs+65] # namespace (0=posix 1=win 2=dos 3=same) # https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#641-namespace
                name=data[nameoff:nameoff+namelen*2].decode("utf_16_le",errors="ignore") #  Contains an UTF-16 little-endian without end-of-string character
                if debug: print("NAME: ",nameoff,namelen,namespc,name,parent)
#                if namespc<2 or len(name)>len(fnev): fnev=name
                if namespc<2 or not fnev: fnev=name
            elif t==0x20:
#              print(data[o+attoffs:o+attoffs+attsize].hex(' '))
              while attsize>=26:
                # Some of these attributes could not be stored in the MFT entry due to space limitations.
                # https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#6-the-attributes
                altype=getint(o+attoffs,4)   # Attribute type (or type code) https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#attribute_types
                alsize=getint(o+attoffs+4,2) #  The size of the attribute including the 6 bytes of the attribute type and size
                namelen=data[o+attoffs+6]  # Name size (or name length)
                nameoff=o+attoffs+data[o+attoffs+7]  #  Contains an offset relative from the start of the attribute list entry
                vcn=getint(o+attoffs+8,8)  #  Data first (or lowest) VCN
                ref=getint(o+attoffs+16,8) #  The file reference to the MFT entry that contains (part of) the attribute data
                aid=getint(o+attoffs+24,2) #   An unique identifier to distinguish between attributes that contain segmented data.
                name=data[nameoff:nameoff+namelen*2].decode("utf_16_le",errors="ignore") #  Contains an UTF-16 little-endian without end-of-string character
                if debug: print("    ATTRlist: type=0x%02X/size=%d  ref=0x%X (%d) vcn=%d  id=%d name='%s'"%(altype,alsize,  ref,ref&0xFFFFFFFFFFFF,vcn, aid,name))
                if altype==0x80 and namelen==0: MFT[mft]["c"].append(ref&0xFFFFFFFFFFFF) # child data nodes
                attoffs+=alsize
                attsize-=alsize
            elif t==0x80:
                if debug: print("??? resident data:",data[o+attoffs:o+attoffs+attsize])  #  b'[ZoneTransfer]\r\nZoneId=3\r\n'      WTF???????
        else:
            vcn1=getint(o+16,8) & 0x0000FFFFFFFFFFFF
            vcn2=getint(o+24,8) & 0x0000FFFFFFFFFFFF
            vcnsize=vcn2+1-vcn1  # clusters referenced here
            runso=getint(o+16+16,2) # Contains an offset relative from the start of the MFT attribute
            compr=getint(o+16+18,2) # Contains the compression unit size as 2^(n) number of cluster blocks
            size1=getint(o+16+24,8) & 0x0000FFFFFFFFFFFF # Allocated data size (or allocated length).
            size2=getint(o+16+32,8) & 0x0000FFFFFFFFFFFF # Data size (or file size)  0x18 0000 0000 A1EA;
            size3=getint(o+16+40,8) & 0x0000FFFFFFFFFFFF # Valid data size (or valid data length)
            size4=0 if compr==0 else getint(o+16+48,8) & 0x0000FFFFFFFFFFFF #  if compressed:  Contains the total allocated size in number of cluster blocks.
            if debug: print("    VCN %d - %d  (%d/%d)  Size: %d/%d/%d/%d  Name: '%s' compr=%d  runs.offs=%d (0x%X)"%(vcn1,vcn2,vcnsize,size1//blksize,size1,size2,size3,size4,str(fnev),compr,runso,o+runso));

            runs=[]
#            runs=decode_runs(data[runso:size],"%d/%d/%d"%(size1,size2,size3),blksize*(1<<compr),mft=-1,fnev=None):
            rundata=data[o+runso:o+l] #.split(b'\xff\xff\xff\xff')[0]
#            print("    RUNdata:",rundata.hex(' '))
            runerr,runtotal=decode_run1(rundata,compr//4096,runs=runs)
            if runerr>=0:
                print("    RUNlist error:",runerr,o+runso+runerr, runtotal)
                runs=[]
                runerr,runtotal=decode_run1(rundata,compr//4096,debug=True,tryfix=True,size=vcnsize,runs=runs)
            elif runtotal!=vcnsize:
                print("    RUNlist bad total:",runtotal)
            if debug: print("    RUNlist:",runs)
            
#            if t in [0x80,0xA0] and nl==0 and len(runs)>0:
            if t in [0x80,0xA0] and nl==0:
                # data block
                MFT[mft]["s"]=size2 # file size
                MFT[mft]["cs"]=blksize*(1<<compr) if aflags&255 else 0 # compress blocksize or 0
                MFT[mft]["r"]=runs

        o+=l

    if tt: tt=(tt//10000000)-11644473600    # windows time -> unix time:
    MFT[mft]["d"]=tt
    MFT[mft]["n"]=fnev
    MFT[mft]["p"]=parent
    if debug: print(MFT[mft])
    return


MFTfile=open("MFT","rb").read()
#MFTfile2=[]
MFTsize=1024
p=0
while p<len(MFTfile):
    data=MFTfile[p:p+MFTsize]
#    if data[:4]==b'USBC': data=MFTfile[p+512:p+MFTsize+512] # shifted
    if data[:4]!=b'FILE':
#        if data[:4]==b'USBC':
#            print(data[:512].hex(' '))
#            print("mft#%d: %d"%( (p//MFTsize), int.from_bytes(data[44:48],byteorder="little",signed=False) ))
        data=MFTfile[p+512:p+512+MFTsize] # try shifted
        if data[:4]==b'FILE':
            if data[512:512+4]==b'FILE':
                print("MFT#%d shifted by 512 bytes and truncated...!"%(p//MFTsize))
                data=data[:512]+bytes(510)+data[510:512]  # ugly hack... de pici fileoknal meg mukodik.
            else:
                print("MFT#%d shifted by 512 bytes!"%(p//MFTsize))
        else:
            print("MFT#%d is garbage :("%(p//MFTsize))
#    else: print(data[:512].hex(' '))
#    print("mft#%d:  "%(p//MFTsize), data[:32].hex(' '))
    if data[:4]==b'FILE':
        mft=int.from_bytes(data[44:48],byteorder="little",signed=False) # elvileg itt tarolja az nft szamat
        if mft!=(p//MFTsize): print("MFT#%d wrong ID: %d"%( (p//MFTsize), mft))
        parse_MFT(data, p//MFTsize)
    p+=MFTsize
#    MFTfile2.append(data)
#open("MFTjav","wb").write(b''.join(MFTfile2))


#print(MFT)
keys=list(MFT.keys())

while True:
    n=0
    for i in MFT:
        p=MFT[i]["p"]
        if p>0 and p!=i and p in MFT:
#            print(i,p,MFT[p]["n"],MFT[p]["s"])
            MFT[p]["c"].append(i)
#            MFT[i]["p"]=-1
            keys.remove(i)
            n+=1
    print(n,len(keys),len(MFT))
    break

#exit(0)

fin=open("/dev/sda","rb")

def copyfile(path,size,runs,compr=0,write=False,read=True,debug=False):
    print("COPY:",size,compr,len(runs),path)
#    if size<=0 or size>512*1024*1024 or compr>1024*1024: return 0
#    if path.lower().endswith(".mp3"): return 0
#    if path.lower().endswith(".avi"): return 0
#    if path.lower().endswith(".vob"): return 0

    if write: f=open(path,"wb")
    total=0
    run=0
    while run<len(runs) and total<size:
        p,s=runs[run]
        if debug: print("   run#%d: %d,%d"%(run,p,s))
        run+=1
        if compr and p: # compressed & not sparse!!!
          fin.seek(p)
          while s>=compr and total<size:
            if read: data=fin.read(compr)
            else: fin.seek(compr,1)
            s-=compr
            if write: f.write(data)
            total+=compr
          if 0<s<compr:
            # compressed block!
            if run<len(runs):
                p2,s2=runs[run]
                if debug: print("   run#%d: %d,%d"%(run,p2,s2))
                if p2!=0: print("COPY ERROR! not sparse block after compressed!!!???",run,p2,s2)
                run+=1
                if s+s2!=compr: print("COPY ERROR! compr blocksize mismatch %d+%d=%d != %d"%(s,s2,s+s2,compr))
            else:
                print("COPY ERROR! missing sparse block for compressed padding!",run)
                s2=compr-s
            data=fin.read(s)
            data+=bytes(compr-s) # padding bytes
#            data2=lznt1.decompress(data)
            data2,inlen=lznt1.decomp2(data,compr)
            if debug: print("Decompressed  %d / %d(+%d) -> %d"%(inlen,s,s2,len(data2)))
            if len(data2)!=compr: print("COPY ERROR! wrong decompressed blocksize: %d != %d",len(data2),compr)
            if write: f.write(data2)
            total+=len(data2)
            # sparse?
            while s2>=compr:
                data2=bytes(compr)
                if write: f.write(data2)
                total+=len(data2)
                s2-=compr
        else:  # uncompressed:
          if total+s>size: s=size-total
          if p and read:
            fin.seek(p)
            data2=fin.read(s)
          else:
            data2=bytes(s)
          if write: f.write(data2)
          total+=len(data2)

    if write:
        f.truncate(size)
        f.close()
    if total<size: print("COPY ERROR! not enough data! %d of %d"%(total,size))
    if debug: print("COPY %d of %d bytes done."%(total,size))
    return total


total=0
total2=0

def printree(i,path=""):
    global total
    global total2
    fnev=MFT[i]["n"]
    path=path+"/"+fnev
    parent=MFT[i]["p"]
    flags=MFT[i]["flags"]
#    t=MFT[i]["t"] # type
    size=MFT[i].get("s",-1)
    compr=MFT[i].get("cs",0)
#    total+=size
    print("=================================================")
    print("%d/%d  (%d)  '%s'"%(parent,i,size,path))
    if fnev:
        if flags&2: # dir?
          try:
            os.mkdir(path.rstrip("/."))
          except:
            pass
        else:
            runs=MFT[i].get("r",[])
            if len(runs)==0 and len(MFT[i]["c"])>0:
                print("empty runs!!!  collect children:",MFT[i]["c"])
                for j in MFT[i]["c"]:
                    if j in MFT:
                        print(j,MFT[j]["cs"],len(MFT[j]["r"]), sum(j for i,j in MFT[j]["r"]) )
                        runs+=MFT[j].get("r",[])
                        compr=max(compr,MFT[j]["cs"])
                        size=max(size,MFT[j]["s"])
#                print(compr, runs)
            if len(runs)>0:
                total+=size
                size2=copyfile(path,size,runs,compr)
                total2+=size2

#        except Exception as e:
#          print(repr(e))
    if flags&2:
        for j in MFT[i]["c"]: printree(j,path)

for i in keys: printree(i,"MENTES")

print("%d of %d MBytes recovered"%( total2//(1024*1024), total//(1024*1024) ))

