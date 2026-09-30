#! /usr/bin/python3

# A PhotoRec altal levagott utofarok (a file vegere fuzott, a JPEG FF D9 lezaras utani adat) kezelese:
#
#   fixoverlay.py [--do] file...
#       a mar kimentett <file>.overlay-bol az ismert utofarkot visszairja a file vegere (--do nelkul csak kiirja)
#   fixoverlay.py --report report.xml file...
#       a PhotoRec report.xml alapjan kiirja a file helyet a lemezen, es a kovetkezo visszaallitott file kezdeteig
#       kimaradt byte-ok szamat (gap); ha a file nem toredezett, az eredeti legfeljebb filesize+gap meretu lehetett
#   fixoverlay.py --report report.xml --dump /dev/nbd0 file...
#       a file utani reszt a kovetkezo file kezdeteig (legfeljebb TAILMAX byte-ot) kimenti <file>.overlay neven
#   fixoverlay.py --report report.xml --dump /dev/nbd0 --do file...
#       az ismert utofarkot rogton visszairja a file vegere; ami nem ismert, de nem csupa 0, az .overlay-be kerul
#       (kesobbi elemzeshez); a csupa 0 reszt nem menti.  (Az eszkoz olvasasahoz root kell.)
#
# Ismert utofarkok (overlay_len):
#   Samsung: SEF blokk (Image_UTC_Data, MCC_Data, ... SEFH ... SEFT) a "SEFT" zarojelig; a SEFT elotti 4 byte a
#            SEFH-tol a hosszmezoig tarto resz hossza, ezzel ellenorizzuk
#   HP, FinePix stb.: 0xFF kitolto byte-ok (legfeljebb OVLMAXFF), esetleg a valodi FF D9 lezarasig
# Ha a file vege mar egyezik az utofarokkal (egy korabbi futas mar visszairta), nem irja hozza ujra.
# A file ideje megmarad.  A load_report()-ot az indxrename.py --report es a vissza.py is hasznalja.

import os
import sys
import bisect
import xml.etree.ElementTree as ET

OVLMAXFF=64
TAILMAX=256*1024

def load_report(path):
    # PhotoRec report.xml: basename -> (start, end, gap, filesize, runs)   (end: az utolso adat byte utani pozicio)
    objs=[]
    for ev,el in ET.iterparse(path):
        if el.tag.rsplit("}",1)[-1]!="fileobject": continue
        name=size=None ; runs=[]
        for c in el.iter():
            tag=c.tag.rsplit("}",1)[-1]
            if tag=="filename": name=os.path.basename(c.text or "")
            elif tag=="filesize": size=int(c.text)
            elif tag=="byte_run": runs.append((int(c.get("offset",0)),int(c.get("img_offset")),int(c.get("len"))))
        el.clear()
        if not name or size is None or not runs: continue
        o,io,l=runs[-1]
        objs.append((runs[0][1],io+size-o,size,name,len(runs)))
    objs.sort()
    starts=[x[0] for x in objs]
    disk_end=max((x[1] for x in objs),default=0)
    rep={}
    for start,end,size,name,nruns in objs:
        j=bisect.bisect_left(starts,end) # az elso file, ami a mi vegunk utan kezdodik (a beagyazott elonezeti kepek kimaradnak)
        nxt=starts[j] if j<len(starts) else disk_end
        rep[name]=(start,end,max(nxt-end,0),size,nruns)
    return rep

def overlay_len(b):
    p=b.find(b"SEFT")
    if p>=4:
        L=int.from_bytes(b[p-4:p],"little")
        if 8<=L<=p-4 and b[p-4-L:p-L]==b"SEFH": return p+4 # SEFH ... <hossz 4 byte> SEFT
    n=0
    while n<len(b) and n<OVLMAXFF and b[n]==0xFF: n+=1
    if 0<n<OVLMAXFF and b[n:n+1]==b"\xd9": return n+1
    return n if n<OVLMAXFF else 0

def fix_file(fn,b,do):
    # a levagott utofarok visszairasa fn vegere a b (a file utani resz a lemezrol) alapjan; visszaad: (statusz, hossz)
    k=overlay_len(b)
    if not k: return "NOTAIL",0
    size=os.path.getsize(fn)
    with open(fn,"rb") as fi: fi.seek(max(size-k,0)) ; tail=fi.read()
    if tail==b[:k]: return "ALREADY",k  # egy korabbi futas mar visszairta
    if not do: return "FIX",k
    t=os.stat(fn)
    with open(fn,"ab") as fo: fo.write(b[:k])
    os.utime(fn,(t.st_atime,t.st_mtime))
    return "FIXED",k

USAGE="""usage: fixoverlay.py [--do] file...
       fixoverlay.py --report report.xml [--dump DEVICE [--do]] file..."""

if __name__=="__main__":
    args=sys.argv[1:]
    rep=dev=None ; do=False
    while args and args[0].startswith("--"):
        opt=args.pop(0)
        if opt=="--do": do=True
        elif opt=="--report" and args: rep=load_report(args.pop(0))
        elif opt=="--dump" and args: dev=open(args.pop(0),"rb")
        else: sys.exit(USAGE)
    if not args or (dev and not rep): sys.exit(USAGE)
    cnt={}
    for fn in args:
        if fn.endswith(".overlay"): continue
        if rep is None:  # a mar kimentett .overlay-bol
            if not os.path.exists(fn+".overlay"): st,k="NOOVERLAY",0
            else:
                with open(fn+".overlay","rb") as fi: st,k=fix_file(fn,fi.read(),do)
            print(fn,st,k)
        else:            # report.xml alapjan (--dump eseten a lemezrol olvasva)
            r=rep.get(os.path.basename(fn))
            if not r: print(fn,"NOT IN REPORT") ; cnt["NOT IN REPORT"]=cnt.get("NOT IN REPORT",0)+1 ; continue
            start,end,gap,size,nruns=r
            st=""
            if dev and nruns==1:
                dev.seek(end)
                b=dev.read(min(gap,TAILMAX))
                if do:
                    st,k=fix_file(fn,b,True)
                    if st=="NOTAIL" and b.count(0)!=len(b): st="OVERLAY" # ismeretlen utofarok: elemzeshez
                if not do or st=="OVERLAY":
                    with open(fn+".overlay","wb") as fo: fo.write(b)
            print("%s start=%d end=%d gap=%d size=%d runs=%d%s"%(fn,start,end,gap,size,nruns," tail="+st if st else ""))
            st=st or ("DUMPED" if dev and nruns==1 else "LISTED")
        cnt[st]=cnt.get(st,0)+1
    print(cnt,file=sys.stderr)
