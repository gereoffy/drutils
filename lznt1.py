#! /usr/bin/python3

import struct
import sys
import copy

def _decompress_chunk(chunk):
    out = bytes()
    while chunk:
        flags = ord(chunk[0:1])
        chunk = chunk[1:]
        for i in range(8):
            if not (flags >> i & 1):
                out += chunk[0:1]
                chunk = chunk[1:]
            else:
                flag = struct.unpack('<H', chunk[:2])[0]
                pos = len(out) - 1
                l_mask = 0xFFF
                o_shift = 12
                while pos >= 0x10:
                    l_mask >>= 1
                    o_shift -= 1
                    pos >>= 1

                length = (flag & l_mask) + 3
                offset = (flag >> o_shift) + 1

                if length >= offset:
                    tmp = out[-offset:] * int(0xFFF / len(out[-offset:]) + 1)
                    out += tmp[:length]
                else:
                    out += out[-offset:-offset+length]
                chunk = chunk[2:]
            if len(chunk) == 0:
                break
    return out

def decompress(buf, length_check=True):
    out = bytes()
    while len(buf)>=2:
        header = struct.unpack('<H', buf[:2])[0]
        if header==0: break # FIXME?
        length = (header & 0xFFF) + 1
#        print("LZNT1: hdr=%d len=%d"%(header>>12,length))
        if length_check and length > len(buf[2:]):
            raise ValueError('invalid chunk length')
        else:
            chunk = buf[2:2+length]
            if header & 0x8000:
                out += _decompress_chunk(chunk)
            else:
                out += chunk
        buf = buf[2+length:]

    return out


def decomp2(buf,compr=0):
  try:
    inlen=0
    out = bytes()
    while len(buf)>=2:
        header = struct.unpack('<H', buf[:2])[0]
#        if header==0: break # FIXME?
#            5 hdr=0   hibasak!
#      1602524 hdr=11  
#       314996 hdr=3
        length = (header & 0xFFF) + 1
        if (header&0x7000)!=0x3000:  # a felso 4 bit 3 vagy 11 szokott lenni...
            if header!=0: print("LZNT1: hdr=%d len=%d"%(header>>12,length))
            break
        if length > len(buf[2:]):
            raise ValueError('invalid chunk length')
        else:
            chunk = buf[2:2+length]
            if header & 0x8000:
                out += _decompress_chunk(chunk)
            else:
                out += chunk
            if compr and len(out)>compr: ValueError('invalid output length')
#            if len(out)==compr: break # megvagyunk!
        buf = buf[2+length:]
        inlen+=2+length
    return out,inlen
  except Exception as e:
    print(repr(e));

  return buf,-1



if __name__ == "__main__":
#  data=open("know.pdf.nt1","rb").read()
#  outf=open("know.pdf","wb")
#  size=204246
  data=open("docfix.doc.NT","rb").read()
  outf=open("docfix.doc","wb")
  size=4159488
  compr=65536
  blksize=4096
  total=0
  pos=0
  while total<size:
    # detect if compressed!
    out,inlen=decomp2(data[pos:pos+compr],compr)
    print("pos=0x%X  inlen=%d  size=%d"%(pos,inlen,len(out)))
    if inlen==0 and len(out)==0:
        print("0x%08X: zero padding block found!"%(pos))
        pos+=blksize
        continue
    if inlen<=0 or len(out)!=compr:
        # probably uncompressed!
        out=data[pos:pos+compr]
        inlen=compr
        print("0x%08X: uncompressed block found! size=%d"%(pos,compr))
    else:
        # tomoritett block
        pad=inlen&(blksize-1)
        if pad: pad=blksize-pad
        print("0x%08X: compressed block found! size=%d+%d   (%d blocks)"%(pos,inlen,pad,(inlen+pad)//blksize))
        inlen+=pad
#        inlen=65536 # ha nem sparse

    pos+=inlen
    outf.write(out)
    total+=len(out)

  outf.truncate(size)
