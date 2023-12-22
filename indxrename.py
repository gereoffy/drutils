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


def oledate(fnev):
  with olefile.OleFileIO(fnev) as ole:
#    print(ole.get_metadata().dump())
    d=ole.get_metadata().last_saved_time
    if not d: d=ole.get_metadata().create_time
#    print("OLE:",type(d),d)
  d=int(d.timestamp()) if d else 0
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

# detect file size, date & extension from content
def fileinfo(fnev):
    st=os.stat(fnev)
    d=int(st.st_mtime)
    s=st.st_size
    e=fnev.split(".")[-1].lower()
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


filedata,dirmap = pickle.load(open("INDEX.pck","rb"))
#print(dirmap)

for fnev in sys.argv[1:]:
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
            fn=dirmap[dr]+"/"+n1
            if exists(fn): continue # already found
            ecnt+=1

            e1=n1.split(".")[-1].lower()
            if e1=="pps": e1="ppt"
            if e!=e1: continue # extension mismatch

            ncnt[fn]=True
            cnt+=1
            dd=abs(d1-d)
        #    if e in ["doc","xls","ppt"] and dd>12*3600: continue # bad date
            if len(filedata[s])>1: print("\t\t",dd,dirmap[dr]+"/"+n1)
            if not bestn or dd<bestd:
                bestn=fn
                bestd=dd
        if bestn:
            cnt=len(ncnt) # FIXME?
            print(d,s,fnev,"OK(%d/%d)"%(cnt,len(filedata[s])), e, bestd, bestn)
            if bestd<61+3600*2 or cnt==1 or 1:    # 1=rename all  0=if timestamp match
                os.rename(fnev,bestn)
            else: print("NAMES:",ncnt.keys())     # list possible filenames
        else:
            print(d,s,fnev,"BAD(%d/%d)"%(ecnt,len(filedata[s])), filedata[s])
    else:
        print(d,s,fnev,"UNKNOWN")

