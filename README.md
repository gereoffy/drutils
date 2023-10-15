# drutils - Data recovery utilities

raid-stat.c - raw disk visualization tool :)

indx3.c     - raw disk data scanner, tries to detect file types, partitions and ntfs metadata

olefix.c    - OLE file (doc/xls/etc) analyzer & fixer

lstree.py   - ntfs MFT file parser and fixer

lsindx.py   - ntfs INDX directory entries parser/lister

testfiles.py - file content validator/verifier, supports:
  - old msoffice documents (doc/xls/ppt and other OLE2 files)
  - new office documents   (docx/xlsx/pptx and other ZIP-based xml files)
  - common image formats   (jpg, png, psd)
  - pdf


testjpeg.py - jpeg parser & validator, used by testfiles  
testpdf.py  - pdf  parser & validator, used by testfiles  
lznt1.py    - ntfs decompress, used by lstree.py (not my code)  
