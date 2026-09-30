#! /usr/bin/python3

import os
import re
import sys
import bisect
import pickle

import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from os.path import exists

import olefile

# get last modification date from office xml-zip files:
def docxdate(fnev,debug=False):
  datum=0
  try:
    with zipfile.ZipFile(fnev, mode="r") as zf:
      data=zf.read("docProps/core.xml")
      root = ET.fromstring(data)
      for child in root:
        try:
          if child.text and child.text.startswith("20"):
            d=str(child.text)
#            print('d="'+d+'"')
            if d.endswith("Z"): d=d[:-1] # old python workaround
            d=datetime.fromisoformat(d).timestamp()
            if d>datum: datum=d
#            print(d)
#        print("\t".join(child.attrib.values()))
        except Exception as e:
          if debug:  print(repr(e))
  except Exception as e:
    if debug: print(repr(e))
#  print(datum)
  return datum


def oledate(fnev,debug=False):
  try:
    with olefile.OleFileIO(fnev) as ole:
#      print(ole.get_metadata().dump())
      d=ole.get_metadata().last_saved_time
      if not d: d=ole.get_metadata().create_time
#      print("OLE:",type(d),d)
    d=int(d.timestamp()) if d else 0
  except Exception as e: # serult OLE file
    if debug: print(repr(e))
    d=0
#  print(d,fnev)
  return d

#    try: d=ole.getmtime('WordDocument') ; print("DOC:",type(d),d)
#    except: pass
#    try: d=ole.getmtime('Workbook') ; print("XLS:",type(d),d)
#    except: pass
#    try: d=ole.getmtime('PowerPoint') ; print("PPT:",type(d),d)
#    except: pass

#    print(ole.listdir(streams=False, storages=True))
#    print(ole.listdir())

# a PhotoRec altal adott es az eredeti kiterjesztes elterhet (pl. .jpeg -> .jpg), ezeket egy nevre hozzuk:
EXT_ALIAS={"jpeg":"jpg","jpe":"jpg","jfif":"jpg","tiff":"tif","htm":"html","pps":"ppt","ppsx":"pptx","mpeg":"mpg"}

def normext(fnev):
    e=os.path.splitext(fnev)[1][1:].lower()
    return EXT_ALIAS.get(e,e)

# detect file size, date & extension from content
def fileinfo(fnev):
    st=os.stat(fnev)
    d=int(st.st_mtime)
    s=st.st_size
    e=normext(fnev)
    with open(fnev,"rb") as f: data=f.read(4096)
#    print(data[:8], e)
    if data.startswith(b'PK\x03\x04'): # ZIP file
        d2=docxdate(fnev)    # get docx/xlsx date
#        print(d-d2,d,d2)
        if d2: d=d2
    elif data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'): # OLE2 file
        d2=oledate(fnev)    # get doc/xls date
        if d2>852076801: d=d2 # >=1997
    return s,d,e


# Parositas: alapbol a legszigorubb modon, csak ha a meret pontosan egyezik, ES a datum is egyezik (date_ok):
# +-DATETOL masodperc, vagy pontosan 1..TZMAX ora elteres +-DATETOL masodperccel (idozona, nyari ido).
# Lazitasok:  --alldate  a datumot nem nezi (a meretnek egyeznie kell, a legkozelebbi datumu jelolt nyer)
#             --larger   az eredeti nagyobb is lehet (pl. a PhotoRec altal levagott JPEG utofarok, amit a fixoverlay.py
#                        nem ismert fel), ilyenkor a datumnak mindenkepp egyeznie kell
#             --tz N     legfeljebb N ora idozona-elteres (alapbol TZMAX)
#             --tol N    N masodperc tures a datumnal (alapbol DATETOL; egyes fenykepezogepek a filet par mp-cel kesobb irjak ki)
DATETOL=2
TZMAX=2
THUMB=re.compile(r"^t\d+\.")  # PhotoRec: EXIF-bol kimentett beagyazott elonezeti kep, ezt nem parositjuk --larger-rel
DOSNAME=re.compile(r"^[^~]{1,6}~\d+(\.[^.]{0,3})?$")  # DOS 8.3 alias (ha van hosszu nev is, azt valasztjuk)
datelist={}
report={}  # --report: PhotoRec report.xml alapjan basename -> (start,end,gap,size,runs), lasd prtail.py

def date_ok(d1,d):
    diff=d1-d ; h=int(round(diff/3600.0))
    return abs(h)<=TZMAX and abs(diff-h*3600)<=DATETOL

def by_larger(s,d,e,fnev):
    # nagyobb (legalabb akkora) meretu, datum szerint egyezo jelolt; tobb kozul a legkisebb meretkulonbsegu
    if THUMB.match(os.path.basename(fnev)): return None,0,0,False
    if not datelist:
        for v in filedata.values():
            for s1,n1,d1,fr,dr in v:
                if n1 and not n1.startswith("~"): datelist.setdefault(normext(n1),[]).append((d1,s1,n1,fr,dr))
        for k in datelist: datelist[k].sort() ; datelist[k]=(datelist[k],[x[0] for x in datelist[k]])
    lst,times=datelist.get(e,([],[]))
    cands={}
    w=TZMAX*3600+DATETOL
    for d1,s1,n1,fr,dr in lst[bisect.bisect_left(times,d-w):bisect.bisect_right(times,d+w)]:
        if s1<s or not date_ok(d1,d): continue
        fn=dirmap.get(dr,"dir__%d"%(dr))+"/"+n1
        if exists(fn): continue
        over=False
        r=report.get(os.path.basename(fnev))
        if r and r[4]==1 and s1-s>r[2]: over=True  # nagyobb, mint ami a kovetkezo visszaallitott file kezdeteig elfer
        key=(over,s1-s,bool(DOSNAME.match(n1)),abs(d1-d),fn)
        if fr not in cands or key<cands[fr]: cands[fr]=key  # egy file (MFT#) csak egyszer, lehetoleg a hosszu nevevel
    if not cands: return None,0,0,False
    best=min(cands.values())  # a felso korlaton beluli jeloltek elonyben
    return best[4],len(cands),best[1],best[0]

# --neighbor: ha van pontosan azonos meretu jelolt, de a datuma nem egyezik (pl. az INDX-ben a felmasolas ideje van, nem
# a felvetele), akkor is elfogadjuk, ha a file lemezszomszedjanak (a report.xml szerint kozvetlenul elotte/utana kezdodo
# PhotoRec file, az elonezeti kepeket atugorva) is van azonos meretu jeloltje UGYANABBAN a konyvtarban, mas neven.
# (Egy konyvtar tartalma egyben kerult fel a lemezre, igy a fileok egymas melle kerultek.)
neighbors={}  # PhotoRec basename -> (elozo, kovetkezo) basename
recpath={}    # PhotoRec basename -> utvonal (a report.xml konyvtara alatt)

def load_neighbors(rep_path):
    order=[n for st,n in sorted((r[0],n) for n,r in report.items()) if not THUMB.match(n)]
    for i,n in enumerate(order): neighbors[n]=(order[i-1] if i else None, order[i+1] if i+1<len(order) else None)
    for root,dirs,files in os.walk(os.path.dirname(os.path.abspath(rep_path))):
        for f in files:
            if f in neighbors: recpath[f]=os.path.join(root,f)

def cand_dirs(n):
    # a lemezszomszed n azonos meretu (es kiterjesztesu) jeloltjeinek (konyvtar, nev) parjai, a mar kiosztottakkal egyutt
    p=recpath.get(n)
    if not p or not os.path.exists(p): return set()
    s1=os.path.getsize(p) ; e1=normext(p)
    return {(dirmap.get(dr,"dir__%d"%(dr)),n1) for x,n1,d1,fr,dr in filedata.get(s1,[]) if e1==normext(n1) and not n1.startswith("~")}

def by_neighbor(fnev,cands):
    nb=neighbors.get(os.path.basename(fnev))
    if not nb: return []
    near=set().union(*[cand_dirs(n) for n in nb if n])
    return [c for c in cands if any(dd==os.path.dirname(c[2]) and nn!=os.path.basename(c[2]) for dd,nn in near)]

def do_link(fnev,bestn):
    # nem mozgatunk: hard link az uj nevre, a PhotoRec file a helyen marad (egy elrontott menet utan eleg a
    # MENTES alkonyvtarait torolni).  Hogy egy file csak egy nevet kapjon, a mar linkelt (st_nlink>1) fileokat kihagyjuk.
    try:
        os.makedirs(os.path.dirname(bestn), exist_ok=True)
        os.link(fnev,bestn)
    except OSError as err: print("LINK ERROR:",fnev,bestn,repr(err))

USAGE="""usage: indxrename.py [--alldate] [--larger] [--neighbor] [--report report.xml] [--tz N] [--tol N] file...
  default: link only if the size matches exactly AND the date matches (+-%ds, or 1..%d hours timezone offset +-%ds)
  --alldate  ignore the date (the size must still match), the candidate with the closest date wins
  --larger   the original may be larger (cut-off tail), the date must still match
  --neighbor same size but the date does not match: accept if a disk neighbour (previous/next PhotoRec file)
             also has a same size candidate in the same directory (needs --report)
  --report   PhotoRec report.xml: disk order for --neighbor, with --larger prefer candidates that fit before the next file
  --tz N     allow up to N hours timezone offset (default %d)
  --tol N    date tolerance in seconds (default %d)
The matched files are hard linked to their new name (the PhotoRec file stays), files already linked are skipped."""%(DATETOL,TZMAX,DATETOL,TZMAX,DATETOL)

args=sys.argv[1:]
alldate=False  # --alldate: a datumot nem nezi
larger=False   # --larger: nagyobb eredeti is lehet (datum egyezessel)
neighbor=False # --neighbor: azonos meret, a datum helyett a lemezszomszed konyvtara igazolja
rep_path=None
while args and args[0].startswith("--"):
    opt=args.pop(0)
    if opt=="--": break
    elif opt=="--alldate": alldate=True
    elif opt=="--larger": larger=True
    elif opt=="--neighbor": neighbor=True
    elif opt=="--tz" and args: TZMAX=int(args.pop(0))
    elif opt=="--tol" and args: DATETOL=int(args.pop(0))
    elif opt=="--report" and args:
        import prtail
        rep_path=args.pop(0)
        report=prtail.load_report(rep_path)
    else: print(USAGE) ; sys.exit(1)
if not args: print(USAGE) ; sys.exit(1)
if neighbor and not rep_path: print("--neighbor needs --report report.xml") ; sys.exit(1)

filedata,dirmap = pickle.load(open("INDEX.pck","rb"))
if neighbor: load_neighbors(rep_path)

for fnev in args:
    if os.stat(fnev).st_nlink>1: print(fnev,"LINKED") ; continue # mar kapott nevet (hard link a MENTES-ben)
    s,d,e=fileinfo(fnev)
    if s in filedata:
        cands=[] ; ecnt=0
        for s1,n1,d1,fr,dr in filedata[s]:
            if n1.startswith("~"): continue # tempfile, skip
            fn=dirmap.get(dr,"dir__%d"%(dr))+"/"+n1  # regi INDEX.pck-ban nem minden szulo van benne
            if exists(fn): continue # already found
            ecnt+=1
            if e!=normext(n1): continue # extension mismatch
            cands.append((abs(d1-d),bool(DOSNAME.match(n1)),fn,d1))
        if len(filedata[s])>1:
            for c in cands: print("\t\t",c[0],c[2])
        ok=cands if alldate else [c for c in cands if date_ok(c[3],d)]
        if ok:
            best=min(ok)
            print(d,s,fnev,"OK(%d/%d)"%(len(ok),len(filedata[s])), e, best[0], best[2])
            do_link(fnev,best[2])
            continue
        nok=by_neighbor(fnev,cands) if neighbor and cands else []
        if nok:
            best=min(nok)
            print(d,s,fnev,"NEIGH(%d/%d)"%(len(nok),len(filedata[s])), e, best[0], best[2])
            do_link(fnev,best[2])
            continue
        if cands:
            best=min(cands)
            status="SKIP(%d/%d) %s %d %s\nNAMES: %s"%(len(cands),len(filedata[s]),e,best[0],best[2],[c[2] for c in cands])
        else: status="BAD(%d/%d) %s"%(ecnt,len(filedata[s]),filedata[s])
    else: status="UNKNOWN"
    # nincs azonos meretu, datum szerint egyezo szabad jelolt: --larger eseten nagyobb eredetit keresunk
    bestn,cnt,sdiff,over=by_larger(s,d,e,fnev) if larger else (None,0,0,False)
    if bestn:
        print(d,s,fnev,"%s(%d)"%("LARGERX" if over else "LARGER",cnt), e, sdiff, bestn)
        do_link(fnev,bestn)
    else: print(d,s,fnev,status)
