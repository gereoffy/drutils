#! /usr/bin/python3

from struct import unpack
import os
import re
import sys
import time

# DC alapu elonezet stderr-re (a DC dekodolas ellenorzesehez):
#   None        - nincs
#   "truecolor" - 24 bites szinek (iTerm2 stb.)
#   "16"        - 16 szinu ANSI, szabvany terminalokhoz
ASCII_ART = None


marker_mapping = {
    0xffc0: "Start of Frame - Baseline",
    0xffc1: "Start of Frame - Extended Seq",
    0xffc2: "Start of Frame - Progressive",
    0xffc3: "Start of Frame - Lossless",
    0xffc4: "Define Huffman Table",
    0xffc5: "Start of Frame 5 - Differential sequential DCT",
    0xffc6: "Start of Frame 6 - Differential progressive DCT",
    0xffc7: "Start of Frame 7 - Differential lossless",
    0xffc8: "JPEG Extensions",
    0xffc9: "Start of Frame 9 - Extended sequential DCT, Arithmetic coding",
    0xffca: "Start of Frame 10 - Progressive DCT, Arithmetic coding",
    0xffcb: "Start of Frame 11 - Lossless (sequential), Arithmetic coding",
    0xffcc: "Define Arithmetic Coding",
    0xffcd: "Start of Frame 13 - Differential sequential DCT, Arithmetic coding",
    0xffce: "Start of Frame 14 - Differential progressive DCT, Arithmetic coding",
    0xffcf: "Start of Frame 15 - Differential lossless, Arithmetic coding",

    0xffd8: "Start of Image",
    0xffd9: "End of Image",
    0xffda: "Start of Scan",
    0xffdb: "Quantization Table",

    0xffdc: "Define number of lines",
    0xffdd: "Define restart interval",
    0xffde: "Define Hierarchical Progression",
    0xffdf: "Expand Reference Component",

    0xffe0: "Application Segment 0 - JFIF/MJPEG",
    0xffe1: "Application Segment 1 - EXIF, thumbnail",
    0xffe2: "Application Segment 2 - ICC color profile",
    0xffe3: "Application Segment 3 - JPS Tag for Stereoscopic JPEG images",
    0xffe4: "Application Segment 4",
    0xffe5: "Application Segment 5",
    0xffe6: "Application Segment 6 - NITF Lossles profile",
    0xffe7: "Application Segment 7",
    0xffe8: "Application Segment 8",
    0xffe9: "Application Segment 9",
    0xffea: "Application Segment 10 - ActiveObject",
    0xffeb: "Application Segment 11 - HELIOS JPEG Resources (OPI Postscript)",
    0xffec: "Application Segment 12 - Picture Info",
    0xffed: "Application Segment 13 - Photoshop Save As: IRB, 8BIM, IPTC",
    0xffee: "Application Segment 14",
    0xffef: "Application Segment 15",

    0xfff8: "Lossless JPEG Extension Parameters",

    0xfffe: "Comment"
}


###############################################################################################################################
# ascii-art (DC elonezet)
###############################################################################################################################

def ColorConversion(dc):
    Y=128+dc[0]/8
    if len(dc)<3: # greyscale?
        Y=max(min(Y,255),0)
        return Y,Y,Y
    R = Y + 1.402/8 * (dc[2])
    G = Y - 0.34414/8 * (dc[1]) - 0.71414/8 * (dc[2])
    B = Y + 1.772/8 * (dc[1])
    return max(min(R,255),0), max(min(G,255),0), max(min(B,255),0)

def print_aa(dcline,prevdcline):
    s=u""
    if not prevdcline: prevdcline=dcline
    for dc1,dc2 in zip(prevdcline,dcline):
        s+="\x1b[48;2;%d;%d;%dm"%ColorConversion(dc1)
        s+="\x1b[38;2;%d;%d;%dm▄"%ColorConversion(dc2)
    #print(s,'\x1b[0m')
    sys.stderr.write(s+'\x1b[0m\n')
    return

palette16=[
    (0,0,0), # 0
    (212,26,26), # 1
    (34,211,39), # 2
    (211,211,48), # 3
    (28,15,210), # 4
    (214,32,211), # 5
    (46,212,213), # 6
    (201,201,201), # 7
    # bright:
    (146,146,146), # 0
    (250,32,32), # 1
    (43,252,48), # 2
    (253,254,60), # 3
    (36,20,250), # 4
    (252,40,252), # 5
    (57,253,253), # 6
    (216,216,216) # 7
]

def rgb16dither(rgb):
    bests=[]
    for x in range(16):
        c=palette16[x]
        def dif(i): return (c[i]-rgb[i])*(c[i]-rgb[i])
        d=dif(0)+dif(1)+dif(2)
        bests.append((d,x))
    bests.sort() # TODO: optimize!
    bg=bests[0][1] # best color
    fg=bests[1][1] # 2nd best
    c1=palette16[bg]
    c2=palette16[fg]
    besti,bestd=-1,0
    for i in range(5):
#        f=[0,0.25,0.5,0.75,1][i]
        f=[0,0.2,0.4,0.7,1][i]
        def dif(i):
            c=c1[i]+(c2[i]-c1[i])*f
            return (c-rgb[i])*(c-rgb[i])
        d=dif(0)+dif(1)+dif(2)
        if besti<0 or d<bestd: besti,bestd=i,d
    return "\x1b[%dm\x1b[%dm%s"%( 40+bg if bg<8 else 100+bg-8, 30+fg if fg<8 else 90+fg-8, " ░▒▓█"[besti])


def rgb16(rgb):
    best,bestd=-1,0
    for x in range(16):
        c=palette16[x]
        def dif(i): return (c[i]-rgb[i])*(c[i]-rgb[i])
        d=dif(0)+dif(1)+dif(2)
        if best<0 or d<bestd: best,bestd=x,d
    return best if best<8 else 60+(best-8)

def print_aa16(dcline,prevdcline,dither=True):
    s=u""
    if not prevdcline: prevdcline=dcline
    for dc1,dc2 in zip(prevdcline,dcline):
        if dither: s+=rgb16dither(ColorConversion(dc1)) ; continue
        s+="\x1b[%dm"%(40+rgb16(ColorConversion(dc1)))
        s+="\x1b[%dm▄"%(30+rgb16(ColorConversion(dc2)))
    #print(s,'\x1b[0m')
    sys.stderr.write(s+'\x1b[0m\n')
    return

aa_functions = {"truecolor": print_aa, "16": print_aa16}


###############################################################################################################################
# huffman
###############################################################################################################################

# a scan (entropy coded segment) vege: FF utan nem 00 (escape), nem RST (D0-D7) es nem D8 (ezt korabban is atengedtuk)
# az FF+ a marker elotti opcionalis FF fill byte-okat is lenyeli
scan_end_re = re.compile(b'\xff+[^\x00\xd0-\xd8\xff]')
rst_split_re = re.compile(b'\xff+([\xd0-\xd7])')

# ennyi 0 byte kerul a scan adat vegere, hogy a bitolvasonak ne kelljen a buffer veget figyelnie.
# egy MCU max. 10 blokk, blokkonkent max 64*(16+16) bit = 256 byte -> 4096 boven eleg
SCAN_PAD = bytes(4096)


def build_huffman_luts(lengths, values):
    """
    65536 elemu lookup tablak (16 bites elonezet alapjan):
      raw: (kodhossz<<8) | symbol
      ac:  baseline AC-hez: ((kodhossz+extra bitek)<<8) | (run+1)   EOB: 0x80   (ZRL: 16, run=15+1 miatt)
    0 = nem letezo kod.  Hiba eseten (None, None, hibauzenet)
    """
    raw = [0] * 65536
    ac = [0] * 65536
    code = 0
    k = 0
    for L in range(1, 17):
        for _ in range(lengths[L - 1]):
            if code >= (1 << L): return None, None, "invalid huffman table (code overflow at length %d)" % L
            sym = values[k]
            shift = 16 - L
            start = code << shift
            n = 1 << shift
            raw[start:start + n] = [(L << 8) | sym] * n
            r, t = sym >> 4, sym & 15
            if t: e = ((L + t) << 8) | (r + 1)
            elif r == 15: e = (L << 8) | 16   # ZRL
            elif r == 0: e = (L << 8) | 0x80  # EOB
            else: e = 0                       # EOBRUN: baseline-ban nem lehet
            ac[start:start + n] = [e] * n
            code += 1
            k += 1
        code <<= 1
    return raw, ac, None


###############################################################################################################################
# entropy dekodolok. Mindegyik (dekodolt_mcu_szam, hibauzenet_vagy_None) -t ad vissza.
# buf: a scan destuffolt (FF00->FF) adata RST markerek nelkul + SCAN_PAD, segs: [(start,end)] byte offsetek RST szegmensenkent
# A bitolvaso: acc-ban nbits db ervenyes bit van (a felso bitek szemetek lehetnek), 32 bit ala esve 32 bittel toltjuk.
# log: debug kiiras (nem szamolt figyelmeztetesek)
###############################################################################################################################

def decode_sequential(buf, segs, rst, mcu_max, blocks, ncomp, Se, disp, log):
    """ baseline/extended DC+AC es progressive DC first pass (Se=0) """
    mcu = 0
    kend = Se + 1
    mcuw, mcuws, rowmax = disp[0], disp[1], disp[2]
    row_cb = disp[3]
    x = 0
    row = []
    for (sstart, send) in segs:
        pos = sstart
        acc = 0
        nbits = 0
        pred = [0] * ncomp
        n = mcu_max - mcu
        if rst and rst < n: n = rst
        endbits = send * 8
        for _ in range(n):
            for (ci, dclut, aclut) in blocks:
                if nbits < 32:
                    acc = ((acc & ((1 << nbits) - 1)) << 32) | (buf[pos] << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3]
                    pos += 4
                    nbits += 32
                e = dclut[(acc >> (nbits - 16)) & 0xFFFF]
                if e == 0: return mcu, "DC huffman code not found"
                nbits -= e >> 8
                t = e & 0xFF
                if t:
                    if t > 16: return mcu, "bad DC magnitude %d" % t
                    nbits -= t
                    v = (acc >> nbits) & ((1 << t) - 1)
                    if v < (1 << (t - 1)): v -= (1 << t) - 1
                    pred[ci] += v
                k = 1
                while k < kend:
                    if nbits < 32:
                        acc = ((acc & ((1 << nbits) - 1)) << 32) | (buf[pos] << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3]
                        pos += 4
                        nbits += 32
                    e = aclut[(acc >> (nbits - 16)) & 0xFFFF]
                    if e == 0: return mcu, "AC huffman code not found (or EOBRUN in sequential scan) at coef %d" % k
                    nbits -= e >> 8
                    s = e & 0xFF
                    if s == 0x80: break  # EOB
                    k += s
                if k > kend: return mcu, "AC coefficient index overflow (%d)" % k
            if pos * 8 - nbits > endbits: return mcu, "unexpected end of scan data"
            mcu += 1
            # ascii-art: minden mcuws-edik MCU DC erteke
            if row_cb:
                if x % mcuws == 0 and x < rowmax: row.append(tuple(pred))
                x += 1
                if x == mcuw:
                    row_cb(row)
                    row = []
                    x = 0
        left = send * 8 - (pos * 8 - nbits)
        if left >= 8: log("WARNING: %d extra bytes at end of scan segment (MCU #%d)" % (left // 8, mcu))
        if mcu >= mcu_max: break
    return mcu, None


def decode_dc_refine(buf, segs, rst, mcu_max, nblocks):
    """ progressive DC refinement: 1 bit / blokk """
    mcu = 0
    for (sstart, send) in segs:
        n = mcu_max - mcu
        if rst and rst < n: n = rst
        need = (n * nblocks + 7) // 8
        if sstart + need > send: return mcu + ((send - sstart) * 8) // nblocks, "unexpected end of scan data"
        mcu += n
        if mcu >= mcu_max: break
    return mcu, None


def decode_ac_first(buf, segs, rst, bmax, raw, Ss, Se, mask, log):
    """ progressive AC first pass (non-interleaved, 1 komponens). mask[blokk]: nem-nulla koefficiensek bitmaszkja (bit k-1) """
    b = 0
    for (sstart, send) in segs:
        pos = sstart
        acc = 0
        nbits = 0
        eobrun = 0
        n = bmax - b
        if rst and rst < n: n = rst
        endbits = send * 8
        bend = b + n
        while b < bend:
            if eobrun:
                # EOB run: ezekben a blokkokban nincs ebben a savban nem-nulla koefficiens
                skip = eobrun if eobrun < bend - b else bend - b
                eobrun -= skip
                b += skip
                continue
            m = mask[b]
            k = Ss
            while k <= Se:
                if nbits < 32:
                    acc = ((acc & ((1 << nbits) - 1)) << 32) | (buf[pos] << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3]
                    pos += 4
                    nbits += 32
                e = raw[(acc >> (nbits - 16)) & 0xFFFF]
                if e == 0: return b, "AC huffman code not found at coef %d" % k
                nbits -= e >> 8
                r = (e >> 4) & 15
                t = e & 15
                if t:
                    k += r
                    nbits -= t
                    m |= 1 << (k - 1)
                    k += 1
                elif r == 15:
                    k += 16  # ZRL
                else:
                    eobrun = 1 << r
                    if r:
                        nbits -= r
                        eobrun += (acc >> nbits) & ((1 << r) - 1)
                    eobrun -= 1  # ez a blokk
                    break
            if k > Se + 1: return b, "AC coefficient index overflow (%d)" % k
            mask[b] = m
            b += 1
            if pos * 8 - nbits > endbits: return b, "unexpected end of scan data"
        if eobrun: log("WARNING: EOBRUN %d crosses restart marker / end of scan" % eobrun)
        left = send * 8 - (pos * 8 - nbits)
        if left >= 8: log("WARNING: %d extra bytes at end of scan segment (block #%d)" % (left // 8, b))
        if b >= bmax: break
    return b, None


def decode_ac_refine(buf, segs, rst, bmax, raw, Ss, Se, mask, log):
    """ progressive AC refinement pass (libjpeg decode_mcu_AC_refine alapjan) """
    b = 0
    for (sstart, send) in segs:
        pos = sstart
        acc = 0
        nbits = 0
        eobrun = 0
        n = bmax - b
        if rst and rst < n: n = rst
        endbits = send * 8
        bend = b + n
        while b < bend:
            m = mask[b]
            k = Ss
            if nbits < 32:
                acc = ((acc & ((1 << nbits) - 1)) << 32) | (buf[pos] << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3]
                pos += 4
                nbits += 32
            if eobrun == 0:
                while k <= Se:
                    if nbits < 32:
                        acc = ((acc & ((1 << nbits) - 1)) << 32) | (buf[pos] << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3]
                        pos += 4
                        nbits += 32
                    e = raw[(acc >> (nbits - 16)) & 0xFFFF]
                    if e == 0: return b, "AC refine huffman code not found at coef %d" % k
                    nbits -= e >> 8
                    r = (e >> 4) & 15
                    t = e & 15
                    if t:
                        if t != 1: return b, "bad AC refine magnitude %d" % t
                        nbits -= 1  # sign
                    elif r != 15:
                        eobrun = 1 << r
                        if r:
                            nbits -= r
                            eobrun += (acc >> nbits) & ((1 << r) - 1)
                        break
                    # r db meg nulla koefficiens atugrasa, kozben a nem-nullakhoz 1-1 korrekcios bit
                    while k <= Se:
                        if (m >> (k - 1)) & 1:
                            if nbits < 1:
                                acc = ((acc & ((1 << nbits) - 1)) << 32) | (buf[pos] << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3]
                                pos += 4
                                nbits += 32
                            nbits -= 1
                        else:
                            r -= 1
                            if r < 0: break
                        k += 1
                    if t:
                        if k > Se: return b, "AC refine coefficient index overflow"
                        m |= 1 << (k - 1)
                    k += 1
            if eobrun > 0:
                # a maradek nem-nulla koefficiensek korrekcios bitjei
                while k <= Se:
                    if (m >> (k - 1)) & 1:
                        if nbits < 1:
                            acc = ((acc & ((1 << nbits) - 1)) << 32) | (buf[pos] << 24) | (buf[pos + 1] << 16) | (buf[pos + 2] << 8) | buf[pos + 3]
                            pos += 4
                            nbits += 32
                        nbits -= 1
                    k += 1
                eobrun -= 1
            mask[b] = m
            b += 1
            if pos * 8 - nbits > endbits: return b, "unexpected end of scan data"
        if eobrun: log("WARNING: EOBRUN %d crosses restart marker / end of scan" % eobrun)
        left = send * 8 - (pos * 8 - nbits)
        if left >= 8: log("WARNING: %d extra bytes at end of scan segment (block #%d)" % (left // 8, b))
        if b >= bmax: break
    return b, None


###############################################################################################################################


def testjpeg(d,debug=False):
    """ visszaad: hibapont (0 = jo). Alapbol csak a szamolt hibakat irja ki, debug=True eseten mindent. """

    def log(*args,**kw):
        if debug: print(*args,**kw)

    log("JPEG file size: %d"%(len(d)))

    huffman_ac_tables= [None, None, None, None]   # (raw_lut, ac_lut)
    huffman_dc_tables= [None, None, None, None]
    quant={}
    component= {}
    acmask= {}   # progressive: komponensenkent a blokkok nem-nulla AC koefficiens bitmaszkja
    scan_no=0

    def DefineQuantizationTables(data):
        l=0
        while len(data)>=1:
            hdr = data[0]
            size = 128 if (hdr>>4) else 64   # Pq=1: 16 bites tabla
            if len(data)<1+size: break
            quant[hdr&15] = list(unpack(">64H" if size==128 else "64B", data[1:1+size]))
            data=data[1+size:]
            l+=1+size
        return l

    def decodeHuffman(data):
      offset = 0
      while offset+17<=len(data):
        header = data[offset]
        offset += 1

        Th= header & 0x0F
        Tc= (header >> 4) & 0x0F

        lengths = list(data[offset : offset + 16])
        offset += 16
        log(Th,Tc,lengths)
        total = sum(lengths)
        if Th>3 or Tc>1 or total>256 or offset+total>len(data):
            print("ERROR! bad huffman table header (Th=%d Tc=%d)"%(Th,Tc))
            return -offset
        huffval = data[offset:offset+total]
        offset += total

        # Generate lookup tables
        raw, ac, err = build_huffman_luts(lengths, huffval)
        if err:
            print("ERROR!", err)
            return -offset
        if Tc==0:
            huffman_dc_tables[Th]= raw
        else:
            huffman_ac_tables[Th]= (raw, ac)

      return offset


    def StartOfScan(data,rst):
        """ visszaad: (a scan utani marker pozicioja vagy -1, hibapont) """
        nonlocal scan_no
        scan_no+=1
        hdrlen = data[3]+(data[2]<<8)+2
        Ns=data[4]
        if Ns<1 or Ns>4 or hdrlen!=6+2*Ns+2 or len(data)<hdrlen:
            print("ERROR! bad SOS header (scan #%d)"%(scan_no))
            return -1,10
        if "dimensions" not in component:
            print("ERROR! SOS before SOF")
            return -1,10
        p=5
        cids=[]
        for i in range(Ns):
          # Read the scan component selector
          Cs= data[p]
          if Cs not in component:
              print("ERROR! SOS refers to unknown component 0x%02X (scan #%d)"%(Cs,scan_no))
              return -1,10
          cids.append(Cs)
          # Read the huffman table selectors
          Ta= data[p+1]
          p+=2
          Td= Ta >> 4
          Ta&= 0xF
          # Assign the DC huffman table
          component[Cs]['Td']= Td
          # Assign the AC huffman table
          component[Cs]['Ta']= Ta

        Ss= data[p]
        Se= data[p+1]
        A= data[p+2]
        Ah,Al = A>>4, A&15
        p+=3
        # Ns:3 Ss:0 Se:63 A:00 baseline
        # Ns:3 Ss:0 Se:0 A:00  progressive
        scaninfo="scan #%d Ns:%d Ss:%d Se:%d A:%02X C:%d Huff: DC=%d/AC=%d" % (scan_no, Ns, Ss, Se, A, Cs, Td, Ta)
        log(scaninfo, "-"*80)

        t0=time.time()
        dims=component["dimensions"]

        # ---------------- entropy coded data kivagasa, RST szegmensekre bontas, destuffing -------------------------
        m=scan_end_re.search(data,hdrlen)
        if m:
            q=m.end()-2         # a marker (utolso FF) pozicioja
            region=data[hdrlen:m.start()]
        else:
            q=-1
            region=data[hdrlen:]
        parts=rst_split_re.split(region)
        segdata=parts[0::2]
        rstmarkers=parts[1::2]
        errs=0
        if region.find(b'\xff\xd8')>=0: log("WARNING: FFD8 inside scan data")
        for i,mk in enumerate(rstmarkers):
            if mk[0]!=0xD0+(i&7):
                print("ERROR! bad restart marker sequence: FF%02X instead of FF%02X (#%d) in %s"%(mk[0],0xD0+(i&7),i,scaninfo))
                errs+=10
                break
        if rstmarkers and not rst:
            print("ERROR! %d restart markers without restart interval in %s"%(len(rstmarkers),scaninfo))
            errs+=10
            segdata=[b''.join(segdata)]
        bufparts=[]
        segs=[]
        o=0
        for s in segdata:
            s=s.replace(b'\xff\x00', b'\xff')
            bufparts.append(s)
            segs.append((o,o+len(s)))
            o+=len(s)
        bufparts.append(SCAN_PAD)
        buf=b''.join(bufparts)

        # ---------------- MCU/blokk szamok ---------------------------------------------------------------------------
        # MCU-k szama vizszintes es fuggoleges iranyban:
        mcuw,mcuh=dims['MW'],dims['MH']
        if Ns==1:
            # non-interleaved scan: a komponens sajat 8x8 blokkjai (subsampled komponensnel kevesebb, mint az MCU-k*H*V)
            c=component[Cs]
            mcuw=(-(-dims['W']*c['H']//dims['Hmax'])+7)//8
            mcuh=(-(-dims['H']*c['V']//dims['Vmax'])+7)//8
        mcu_max=mcuw*mcuh

        err=None
        mcu_cnt=0
        try:
          if Ss>0: # progressive AC pass
            if Ns!=1 or Se>63 or Ss>Se or not dims['progressive']:
                err="bad AC scan parameters"
            elif huffman_ac_tables[Ta] is None:
                err="missing AC huffman table %d"%(Ta)
            else:
                mask=acmask.get(Cs)
                if mask is None or len(mask)!=mcu_max:
                    mask=acmask[Cs]=[0]*mcu_max
                if Ah==0: mcu_cnt,err=decode_ac_first(buf,segs,rst,mcu_max,huffman_ac_tables[Ta][0],Ss,Se,mask,log)
                else:     mcu_cnt,err=decode_ac_refine(buf,segs,rst,mcu_max,huffman_ac_tables[Ta][0],Ss,Se,mask,log)
          elif Ah!=0: # progressive DC refining bits (1 bit/blokk)
            nblocks=sum(component[C]['H']*component[C]['V'] for C in cids) if Ns>1 else 1
            mcu_cnt,err=decode_dc_refine(buf,segs,rst,mcu_max,nblocks)
          else:
            if dims['progressive'] and Se!=0: err="bad DC scan parameters"
            elif not dims['progressive'] and (Se!=63 or A!=0): log("WARNING: sequential scan with Ss=%d Se=%d A=%02X"%(Ss,Se,A))
            blocks=[]
            for i,C in enumerate(cids):
                comp=component[C]
                dct=huffman_dc_tables[comp['Td']]
                act=huffman_ac_tables[comp['Ta']] if Se>0 else (None,None)
                if dct is None or act is None:
                    err="missing huffman table"
                    break
                for j in range(comp['H']*comp['V'] if Ns>1 else 1): blocks.append((i,dct,act[1]))
            if not err:
                ########################################################
                disp=(mcuw,1,0,None)
                aa=aa_functions.get(ASCII_ART)
                if aa and (Cs==component["IDs"][0] or Ns>1):   # ascii-art csak ha a luma is benne van
                    mcuws=max(int(mcuw/160),1)
                    if mcuw/mcuws>200: mcuws+=1
                    c0=component[component["IDs"][0]]
                    mcuhs=max((mcuws*2*c0['H'])//c0['V'],1)
                    log("ASCII scaling",mcuws,mcuhs,mcuw//mcuws,mcuh//mcuhs)
                    qs=[quant.get(component[C]['Tq'],[1])[0]<<Al for C in cids]
                    dcy=0
                    prevdc=None
                    def row_cb(row):
                        nonlocal dcy,prevdc
                        if dcy%mcuhs==0 or dcy%mcuhs==(mcuhs//2):
                            dc=[[v*qq for v,qq in zip(r,qs)] for r in row]
                            if dcy%mcuhs==0: prevdc=dc
                            if dcy%mcuhs==(mcuhs//2): aa(dc,prevdc)
                        dcy+=1
                    disp=(mcuw,mcuws,mcuws*160,row_cb)
                ########################################################
                mcu_cnt,err=decode_sequential(buf,segs,rst,mcu_max,blocks,Ns,Se,disp,log)
        except IndexError:
            err="scan data overrun"

        t0=time.time()-t0
        log("%6d/%6d MCU%s blocks read!  %d bytes  time: %5d ms   (%d kB/s)"%(mcu_cnt,mcu_max,"!!!" if mcu_cnt!=mcu_max else "",len(region),int(t0*1000.0),int(len(region)/1024/max(t0,1e-6))))
        if err:
            print("ERROR! decoding failed at MCU #%d/%d: %s  (%s)"%(mcu_cnt,mcu_max,err,scaninfo))
            errs+=10
        elif mcu_cnt!=mcu_max:
            print("ERROR! only %d of %d MCUs decoded  (%s)"%(mcu_cnt,mcu_max,scaninfo))
            errs+=10

        # nullaval feltoltott (kinullazott) teruletek a scan adatban:
        r=data.find(bytes(512),hdrlen,q if q>=0 else len(data))
        if r>=0:
            print("ERROR! 512+ x 0x00 bytes repeating at %d  (%s)"%(r,scaninfo))
            errs+=10
        if debug:
            r=data.find(b'\xff'*4,hdrlen,q if q>=0 else len(data))
            if r>=0: print("WARNING: 4 x 0xFF bytes repeating at %d"%(r))

        #######
        if q<0: return -1,errs
        log("%d reset markers && %d escapes in %d bytes image data skipped"%(len(rstmarkers),region.count(b'\xff\x00') if debug else 0,q))
        log("MarkerAfterScan: FF%02X"%(data[q+1]))
        return q,errs



    def DecodeMPExt(data):
      try:
        endian=data[0:4]
        if endian==b'MM\x00\x2a': e='>'
        elif endian==b'II\x2a\x00': e='<'
        else: return -1
        offs,=unpack(e+"L",data[4:8])
        cnt,=unpack(e+"H",data[offs:offs+2])
        log(endian,offs,cnt)
        icnt=isize=ioffs=0
        for i in range(cnt):
            tag,typ,count,value=unpack(e+"HHLL",data[offs+2+i*12:offs+2+i*12+12])
            if tag==0xB001: icnt=value          # NumberOfImages
            elif tag==0xB002: isize,ioffs=count,value   # MPEntry
        log(icnt,isize,ioffs)
        if isize:
            for i in range(isize//16):
                attr,size,offs,dep1,dep2=unpack(e+"LLLHH",data[ioffs+i*16:ioffs+i*16+16])
                log("Individual image #%d: 0x%X  (%d bytes)"%(i,offs,size))

      except Exception:
        return -1
      return len(data)


    data=d
    errcnt=0
    rst=0
    markcnt={0xFFD8:0,0xFFD9:0,0xFFDA:0,0xFFC0:0,0xFFC1:0,0xFFC2:0}
    while len(data)>1:
        if data[0]!=0xFF:
            p=data.find(0xFF)
            if p<=0: p=len(data)
            print("ERROR! skipping %d bytes at %d"%(p,len(d)-len(data)))
            errcnt+=5
            data=data[p:]
            # erdemes egyaltalan folytatni? ez mar innen szar szokott lenni...
            continue

        marker = data[1]|(data[0]<<8)
        if debug:
            if marker not in [0xffd8,0xffd9] and len(data)>=4:
                lenchunk = data[3]+(data[2]<<8)+2
                print("0x%04X (%d) %s"%(marker,lenchunk,marker_mapping.get(marker)))
            else:
                print("0x%04X %s"%(marker,marker_mapping.get(marker)))
        markcnt[marker]=markcnt.get(marker,0)+1

        if marker == 0xffd8:
            data = data[2:]
            continue

        if marker == 0xffd9:
            log(markcnt)
            if markcnt[0xFFD8]!=1 or markcnt[0xFFD9]!=1 or markcnt[0xFFDA]<1 or markcnt[0xFFC0]+markcnt[0xFFC1]+markcnt[0xFFC2]!=1:
                print("ERROR! bad marker count:",", ".join("%04X:%d"%(k,v) for k,v in markcnt.items()))
                errcnt+=10

            p=2
            # skip zero bytes at the end of file:
            while p<len(data):
                if data[p]!=0: break
                p+=1
            if p>2+3: log("%d zero bytes skipped"%(p-2))
            data=data[p:]

            # check for extra jpeg thumbnail/preview:
            p=data[:32].find(b'\xff\xd8')
            if p>=0 and len(data)>p+8:
                log("WARNING: %d bytes extra image !!!\n"%(len(data)))
                e=testjpeg(data[p:],debug)
                if e: print("ERROR! ^^^ in extra image at %d (%d bytes)"%(len(d)-len(data)+p,len(data)-p))
                errcnt+=e
            elif data.startswith(b'\x01\n\x0e\x00\x00\x00Image_UTC_Data'):
                log("Skipping %d bytes Image_UTC_Data"%(len(data)))
            else:
                if len(data)>=4 and debug:
                    print("WARNING: %d bytes left:  %02X %02X %02X %02X"%(len(data),data[0],data[1],data[2],data[3]))
                    print(data[:128].hex(' '))
                    print(data[:128])
            return errcnt

        if len(data)<4: break

        if marker == 0xffda:
            hl,e=StartOfScan(data,rst)
            errcnt+=e
            if hl<=0 or hl+2>len(data): break # EOF reached
            data = data[hl:]
            # next marker check
            marker = data[1]|(data[0]<<8)
            if marker not in [0xffda,0xffd9,0xFFC4]:
                print("ERROR! bad marker after scan data: 0x%04X  "%(marker),marker_mapping.get(marker))
                errcnt+=10
                return errcnt
        else:
            lenchunk = data[3]+(data[2]<<8)+2
            if lenchunk<4 or lenchunk>len(data):
                print("ERROR! bad segment length %d for marker 0x%04X"%(lenchunk,marker))
                errcnt+=10
                break
            if marker==0xffc4:   # huffman table
                hl=decodeHuffman(data[4:lenchunk])
            elif marker in [0xffc0,0xffc1,0xffc2]: # start of frame
                bits, height, width, components = unpack(">BHHB", data[4:4+6])
                if bits!=8 or components not in [1,3,4] or width>8*height or height>5*width or width>2*8192 or height>2*8192 or width<16 or height<16:
                    print("WARNING! ",end = '')
                    errcnt+=1
                    # ez jo: WARNING! dimensions: 1016 x 1002 x 4 / 8bit , ez is: WARNING! dimensions: 1252 x 1075 x 4 / 8bit
                    # ez is: WARNING! dimensions: 14032 x 9922 x 3 / 8bit
                    # WARNING! dimensions: 1970 x 8120 x 3 / 8bit
                    print("dimensions: %d x %d x %d / %dbit"%(width,height,components,bits))
                else:
                    log("dimensions: %d x %d x %d / %dbit"%(width,height,components,bits))
                if width==0 or height==0 or components==0 or lenchunk<10+components*3:
                    print("ERROR! bad frame header")
                    errcnt+=10
                    break
                component.clear()
                acmask.clear()
                component["dimensions"]={'W':width,'H':height,'progressive':marker==0xffc2}
                hl=6+(components)*3
                Vmax=1
                Hmax=1
                component["IDs"]=[]
                for i in range(components):
                    C=data[10+i*3+0]
                    V=data[10+i*3+1]
                    H= V >> 4
                    V&= 0xF
                    if H>Hmax: Hmax=H
                    if V>Vmax: Vmax=V
                    Tq=data[10+i*3+2]
                    log("  component #%d: id=0x%02X sampling=%dx%d quant=0x%X"%(i,C,H,V,Tq))
                    if H<1 or H>4 or V<1 or V>4:
                        print("ERROR! bad sampling factor %dx%d"%(H,V))
                        errcnt+=10
                        return errcnt
                    component["IDs"].append(C)
                    component[C]= {}
                    # Assign horizontal sampling factor
                    component[C]['H']= H
                    # Assign vertical sampling factor
                    component[C]['V']= V
                    # Assign quantization table
                    component[C]['Tq']= Tq
                component["dimensions"]['Hmax']=Hmax
                component["dimensions"]['Vmax']=Vmax
                component["dimensions"]['MW']=((width+Hmax*8-1)//(Hmax*8))
                component["dimensions"]['MH']=((height+Vmax*8-1)//(Vmax*8))
                log(component["dimensions"])
            elif marker==0xffdb: # quant tables
                hl=DefineQuantizationTables(data[4:lenchunk])
            elif marker==0xffe2: # MP
                log("APP2 extension: ",data[4:8])
                if data[4:8]==b'MPF\x00':
                    hl=DecodeMPExt(data[8:lenchunk])
                    if hl>=0: hl+=4
                else: hl=lenchunk-4
            elif marker==0xffdd: # reset interval
                rst = data[5]+(data[4]<<8)
                log("RESET interval =",rst)
                hl=2
            else:
                hl=lenchunk-4 # unknown type
            if hl<0:
                print("ERROR! cannot parse %d bytes of marker 0x%04X"%(lenchunk-4+hl,marker))
                errcnt+=10
            elif hl!=lenchunk-4:
                print("ERROR! only %d of %d bytes parsed of marker 0x%04X"%(hl,lenchunk-4,marker))
                errcnt+=10
            data = data[lenchunk:]

    print("ERROR! EOF reached before EOI marker!")
    errcnt+=10
    return errcnt

#f=open("/home/spamwall/backup/ext/jpg/0048b1fb20d8f0c6_19798640__IMG_3808.jpg","rb")
#f=open("/home/spamwall/backup/ext/jpg/fec98baf1e9f4697_17229344__BCR-114C-38.jpg","rb")

if __name__ == "__main__":
  args=sys.argv[1:]
  path=args[0] if args else "data/"
  if os.path.isdir(path):
    files=[os.path.join(path,n) for n in os.listdir(path)]
  else:
    files=args
  for n in files:
    print("\n\n==================== %s ======================\n"%(os.path.basename(n)))
    with open(n,"rb") as f: res=testjpeg(f.read(),debug=True)
    if res>0: print("!!!HIBAS!!!",res)
