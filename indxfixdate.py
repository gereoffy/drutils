#! /usr/bin/python3

import os
import sys
import pickle
from os.path import exists

filedata,dirmap = pickle.load(open("INDEX.pck","rb"))
#print(dirmap)

fixed={}

for s in filedata:
    for s1,n1,d1,fr,dr in filedata[s]:
        if not dr in dirmap: continue # ???
        fn=dirmap[dr]+"/"+n1
        if fn in fixed: continue # dupe
        if exists(fn):
            fixed[fn]=True
            print(d1,fn)
            os.utime(fn, (d1,d1))
