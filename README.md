# drutils - Data recovery utilities

scandisk.c  - raw disk visualization tool useful for NTFS volumes (MFT, INDX, document and picture files search)

raid-stat.c - raw disk visualization tool useful for RAID volume members

indx3.c     - raw disk data scanner, tries to detect file types, partitions and ntfs metadata

olefix.c    - OLE file (doc/xls/etc) analyzer & fixer

jpgfix.c    - JPEG file fixer

# NTFS data recovery tools for broken or missing MFT disks:

lstree.py   - ntfs MFT file parser and fixer (recovers files from raw device using extracted MFT file) see LSTREE.md

lsindx.py   - ntfs INDX directory entries parser/lister (rebuilds directory tree using only INDX entries) see LSINDX.md

fixoverlay.py - fix "truncated" files using PhotoRec's report.xml (eg. extra metadata appended to jpeg files)

indxrename.py - link PhotoRec-recovered files to their original filename and dirtree-location based on size/date heuristics using INDEX.pck of lsindx.py

# testfiles - file consistency checker / validator / verifier / tester

Detects damaged/truncated files, e.g. after data recovery, see FORMATS.md for details:
  - old msoffice documents (doc/xls/ppt and other OLE2 files, Thumbs.db listing)
  - new office documents   (docx/xlsx/pptx, odt/ods/odp, epub, spv and other ZIP-based files)
  - image formats          (jpg, png/apng, gif, tif, psd/psb, webp, wmf/emf)
  - CAD drawings           (dxf, dwg R10-2018)
  - vector graphics        (CorelDRAW cdr: RIFF 3-X3 and ZIP X4+)
  - SPSS data files        (sav/zsav)
  - video/audio containers (mp4, mov, m4a, 3gp and heic/avif images - ISO Base Media File Format; avi; wmv/wma; mkv/webm)
  - audio                  (mp3, wav)
  - flash                  (swf)
  - pdf                    (supports new extended parser at https://github.com/gereoffy/pdfparse3)

File types are detected by content, not by extension. All-zero files are reported as BAD,
extension/content mismatches as warnings. See FORMATS.md for what exactly is checked per format.

For dwg, dxf, cdr, zip-based, ole, jpeg, tif, webp, mp4/mov/heic, avi, wmv/wma, mkv/webm, mp3, wav, swf and sav files a metadata line is printed per file
(XXX_INFO;filename;version;type;created;modified;...), to identify recovered files: grep -a '^JPG_INFO;' out.txt > jpg.csv

Pure Python, no external dependencies (OLE2 files are read by an own reader, olefile is no longer needed).
PyPy is recommended for large data sets.


testfiles.py- runs the tests bellow in parallel based on the detected filetype  
testjpeg.py - jpeg parser & validator (full Huffman decoding, optional ASCII-art preview)  
testpng.py  - png/apng parser & validator  
testgif.py  - gif  parser & validator  
testtif.py  - tif  parser & validator  
testpsd.py  - psd/psb parser & validator  
testwmf.py  - wmf/emf parser & validator  
testzip.py  - zip-based formats (office, odf, epub, spv, cdr X4+...) validator  
testole.py  - OLE2 (doc/xls/ppt...) validator, built on parseole  
testsav.py  - SPSS sav/zsav parser & validator  
testdxf.py  - dxf (ASCII & binary) parser & validator  
testdwg.py  - dwg integrity checker (CRC/checksums/Reed-Solomon)  
testmp4.py  - mp4/mov/heic (ISOBMFF) structure & sample table validator  
testavi.py  - RIFF formats (avi, wav, webp, cdr) validator  
testmp3.py  - mp3 frame chain, CRC, ID3/Xing/LAME validator  
testswf.py  - swf (Flash: FWS/CWS/ZWS) decompression, tag chain & embedded image validator  
testasf.py  - wmv/wma (ASF) object, packet & payload structure validator  
testmkv.py  - mkv/webm (Matroska) EBML tree, block, H.264/HEVC NAL & cue index validator  
testpdf.py  - old pdf parser & validator  (used as fallback when pdfparse3 is not available)  
fileinfo.py - common code of the per-file metadata lines (XXX_INFO: dates, author, program, device)  
parseole.py - standalone OLE2 reader (olefile replacement, strict & lenient mode, metadata), no dependencies  

Usage (directories are checked recursively, -j N: N parallel worker processes, output is identical to a sequential run):

    pypy testfiles.py -j 32 /mnt/recovered/

All modules are used by testfiles.py, but can be run standalone (in debug mode) on a file or a directory, e.g.:

    pypy testdwg.py dwg/
