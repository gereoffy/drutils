#! /usr/bin/python3

import os
import sys
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


USAGE="usage: indxrename.py [--all] file...\n  --all  rename to the best candidate even if the timestamp does not match"

args=sys.argv[1:]
rename_all=False  # False: csak ha a datum stimmel (vagy egyetlen jelolt van)  True: mindig a legjobb jeloltre
while args and args[0].startswith("--"):
    opt=args.pop(0)
    if opt=="--": break
    elif opt=="--all": rename_all=True
    else: print(USAGE) ; sys.exit(1)
if not args: print(USAGE) ; sys.exit(1)

filedata,dirmap = pickle.load(open("INDEX.pck","rb"))
#print(dirmap)

for fnev in args:
    s,d,e=fileinfo(fnev)
    if s in filedata:
#        if len(f)==1:
#            print(d,s,fnev,"OK",f[0])
#        else:
#            print(d,s,fnev,"MULTI",f)
        bestn=None
        bestd=0
        cnt=0
        ecnt=0
        ncnt={}
        for s1,n1,d1,fr,dr in filedata[s]:

            if n1.startswith("~"): continue # tempfile, skip
            fn=dirmap.get(dr,"dir__%d"%(dr))+"/"+n1  # regi INDEX.pck-ban nem minden szulo van benne
            if exists(fn): continue # already found
            ecnt+=1

            if e!=normext(n1): continue # extension mismatch

            ncnt[fn]=True
            cnt+=1
            dd=abs(d1-d)
        #    if e in ["doc","xls","ppt"] and dd>12*3600: continue # bad date
            if len(filedata[s])>1: print("\t\t",dd,fn)
            if not bestn or dd<bestd:
                bestn=fn
                bestd=dd
        if bestn:
            cnt=len(ncnt) # FIXME?
            if bestd<61+3600*2 or cnt==1 or rename_all:
                print(d,s,fnev,"OK(%d/%d)"%(cnt,len(filedata[s])), e, bestd, bestn)
                try:
                    os.makedirs(os.path.dirname(bestn), exist_ok=True)
                    os.rename(fnev,bestn)
                except OSError as err: print("RENAME ERROR:",fnev,bestn,repr(err))
            else:
                print(d,s,fnev,"SKIP(%d/%d)"%(cnt,len(filedata[s])), e, bestd, bestn)
                print("NAMES:",list(ncnt.keys()))     # list possible filenames
        else:
            print(d,s,fnev,"BAD(%d/%d)"%(ecnt,len(filedata[s])), filedata[s])
    else:
        print(d,s,fnev,"UNKNOWN")

