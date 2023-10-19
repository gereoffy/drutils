#! /usr/bin/python3

import os,sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

for fnev in sys.argv[1:] if len(sys.argv)>1 else ["f22341399.docx"]:
  print(fnev)
  datum=None
  try:
    with zipfile.ZipFile(fnev, mode="r") as zf:
      data=zf.read("docProps/core.xml")
      root = ET.fromstring(data)
      for child in root:
#        help(child)
#        print(child.attrib)
#        print(child.text)
        try:
          if child.text.startswith("20"):
            d=str(child.text)
#            print('"'+d+'"')
            if d.endswith("Z"): d=d[:-1]
            d=datetime.fromisoformat(d).timestamp()
            if not datum or d>datum: datum=d
#            print(d)
#        print("\t".join(child.attrib.values()))
        except: pass
    if datum: os.utime(fnev, (datum,datum))
  except Exception as e:
    print(repr(e))
