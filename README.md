# drutils - Data recovery utilities

raid-stat.c - raw disk visualization tool :)

indx3.c     - raw disk data scanner, tries to detect file types, partitions and ntfs metadata

olefix.c    - OLE file (doc/xls/etc) analyzer & fixer

lstree.py   - ntfs MFT file parser and fixer

lsindx.py   - ntfs INDX directory entries parser/lister

testfiles.py - file content validator/verifier (detects damaged/truncated files, e.g. after data recovery), supports:
  - old msoffice documents (doc/xls/ppt and other OLE2 files)
  - new office documents   (docx/xlsx/pptx, odt/ods/odp, epub, spv and other ZIP-based files)
  - image formats          (jpg, png/apng, gif, tif, psd/psb, wmf/emf)
  - CAD drawings           (dxf, dwg R10-2018)
  - SPSS data files        (sav/zsav)
  - video/audio containers (mp4, mov, m4a, 3gp and heic/avif images - ISO Base Media File Format)
  - pdf

File types are detected by content, not by extension. All-zero files are reported as BAD,
extension/content mismatches as warnings. See FORMATS.md for what exactly is checked per format.

Pure Python, the only (optional) dependency is olefile for OLE2 files (pip3 install olefile).
PyPy is recommended for large data sets.


testjpeg.py - jpeg parser & validator (full Huffman decoding, optional ASCII-art preview)  
testpng.py  - png/apng parser & validator  
testgif.py  - gif  parser & validator  
testtif.py  - tif  parser & validator  
testpsd.py  - psd/psb parser & validator  
testwmf.py  - wmf/emf parser & validator  
testzip.py  - zip-based formats (office, odf, epub, spv...) validator  
testole.py  - OLE2 (doc/xls/ppt...) validator, needs olefile  
testsav.py  - SPSS sav/zsav parser & validator  
testdxf.py  - dxf (ASCII & binary) parser & validator  
testdwg.py  - dwg integrity checker (CRC/checksums/Reed-Solomon)  
testmp4.py  - mp4/mov/heic (ISOBMFF) structure & sample table validator  
testpdf.py  - pdf  parser & validator  

All modules are used by testfiles.py, but can be run standalone (in debug mode) on a file or a directory, e.g.:

    pypy testdwg.py dwg/
