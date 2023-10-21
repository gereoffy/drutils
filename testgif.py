#!/usr/bin/python3

# based on:  https://github.com/deshipu/circuitpython-gif/blob/master/code.py

import struct

def read_blockstream(f):
    data=b''
    while True:
        size = f.read(1)[0]
#            print("block",size)
        if size==0: break
        data+=f.read(size)
    print("GIF blockstream len:",len(data))
    return data


class EndOfData(Exception):
    pass


class LZWDict:
    def __init__(self, code_size):
        self.code_size = code_size
        self.clear_code = 1 << code_size
        self.end_code = self.clear_code + 1
        self.codes = []
        self.clear()

    def clear(self):
        self.last = b''
        self.code_len = self.code_size + 1
        self.codes[:] = []

    def decode(self, code):
        if code == self.clear_code:
            print("GIF lzw: clear code found")
            self.clear()
            return b''
        elif code == self.end_code:
            print("GIF lzw: end code reached")
            raise EndOfData()
        elif code < self.clear_code:
            value = bytes([code])
        elif code <= len(self.codes) + self.end_code:
            value = self.codes[code - self.end_code - 1]
        else:
            value = self.last + self.last[0:1]
        if self.last:
            self.codes.append(self.last + value[0:1])
        if (len(self.codes) + self.end_code + 1 >= 1 << self.code_len and
            self.code_len < 12):
                self.code_len += 1
        self.last = value
        return value


def lzw_decode(data, code_size):
    dictionary = LZWDict(code_size)
    bit = 0
    byte=data[0]
    p=1
    try:
        while True:
            code = 0
            for i in range(dictionary.code_len):
                if bit >= 8:
                    bit = 0
#                    if p>=len(data): break # EOF
                    byte=data[p]
                    p+=1
                code |= ((byte >> bit) & 0x01) << i
                bit += 1
            yield dictionary.decode(code)
    except EndOfData:
        print("GIF EndOfData:",p,len(data))
    except Exception as e:
        print("GIF lzw error:",repr(e))

class Frame:
    def __init__(self, f, colors):
#        self.bitmap_class = bitmap
#        self.palette_class = palette
        self.x, self.y, self.w, self.h, flags = struct.unpack('<HHHHB', f.read(9))
        self.palette_flag = (flags & 0x80) != 0
        self.interlace_flag = (flags & 0x40) != 0
        self.sort_flag = (flags & 0x20) != 0
        self.palette_size = 1 << ((flags & 0x07) + 1)
        print("GIF-frame:",self.x, self.y, self.palette_size if self.palette_flag else -1, self.w, self.h, flags) # GIF-frame: 0 0 2 721 721 0
        if self.palette_flag:
            self.read_palette(f)
            colors = self.palette_size
        self.min_code_sz = f.read(1)[0]
        self.data = read_blockstream(f)
        self.pixels=0
        for decoded in lzw_decode(self.data, self.min_code_sz): self.pixels+=len(decoded) # decode stream

    def read_palette(self, f):
        self.palette = [None]*self.palette_size
        for i in range(self.palette_size):
            self.palette[i] = f.read(3)


def testgif(f):
    try:
        # header
        magic = f.read(6)
        if magic not in [b'GIF87a', b'GIF89a']: return 100 #  raise ValueError("Not GIF file")
        w, h, flags, background, aspect = struct.unpack('<HHBBB', f.read(7))
        palette_flag = (flags & 0x80) != 0
        sort_flag = (flags & 0x08) != 0
        color_bits = ((flags & 0x70) >> 4) + 1
        palette_size = 1 << ((flags & 0x07) + 1)
        print("GIF:",w, h, palette_size, flags, background, aspect) # GIF: 721 721 64 213 0 0
        if w<0 or w>2048 or h<0 or h>2048: return 10 # bad size
        if palette_flag: palette = f.read(3*palette_size)
        ok=0
        while True:
            block_type = f.read(1)[0]
            print("GIF: block 0x%X"%block_type)
            if block_type == 0x3b:
                break
            elif block_type == 0x2c:
                frame=Frame(f, palette_size)
                print("GIF frame pixels:",frame.pixels,frame.w*frame.h)
                if frame.pixels == frame.w*frame.h: ok+=1
#                break # XXX only read the first frame for now
            elif block_type == 0x21:
                extension_type = f.read(1)[0]  # 0x01 = label, 0xfe = comment
                ext_data = read_blockstream(f)
            else:
                return 20 # raise ValueError('Bad block {0:2x}'.format(block_type))
        print("GIF: %d frames decoded OK"%ok)
        return 0 if ok else 1
    except Exception as e:
        print(repr(e))
        return 100


if __name__ == "__main__":
    with open("hibas.gif", 'rb') as f: testgif(f)
