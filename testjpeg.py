#! /usr/bin/python3

from struct import unpack
import math
import os
import sys
import time

def GetArray(type, l, length):
    """
    A convenience function for unpacking an array from bitstream
    """
    s = ""
    for i in range(length):
        s = s + type
    return list(unpack(s, l[:length]))


def DecodeNumber(code, bits):
    l = 2 ** (code - 1)
    if bits >= l:
        return bits
    else:
        return bits - (2 * l - 1)





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



def testjpeg(d):
#    l=len(d)
    print("JPEG file size: %d"%(len(d)))

    huffman_ac_tables= [{}, {}, {}, {}]
    huffman_dc_tables= [{}, {}, {}, {}]
    quant={}
    component= {}

    def map_codes_to_values(codes, values):
       """ Map the huffman code to the right value """
       out= {}
       for i in range(len(codes)):
          out[codes[i]]= values[i]
       return out

    def huffman_codes(huffsize):
       """ Calculate the huffman code of each length """
       huffcode= []
       k= 0
       code= 0

       # Magic
       for i in range(len(huffsize)):
          si= huffsize[i]
          for k in range(si):
             huffcode.append((i+1,code))
             code+= 1
          code<<= 1

       return huffcode


    def DefineQuantizationTables(data):
        l=0
        while len(data)>=65:
            (hdr,) = unpack("B", data[0:1])
            quant[hdr] = GetArray("B", data[1 : 1 + 64], 64)
#            print(hdr,quant[hdr])
            data=data[65:]
            l+=65
        return l

    def decodeHuffman(data):

      offset = 0
      while offset+17<=len(data):
        (header,) = unpack("B", data[offset : offset + 1])
#        print(header, header & 0x0F, (header >> 4) & 0x0F)
        offset += 1

        Th= header & 0x0F
#        print("Th: %d" % Th)
        Tc= (header >> 4) & 0x0F
#        print("Tc: %d" % Tc)

        lengths = GetArray("B", data[offset : offset + 16], 16)
        offset += 16
        print(Th,Tc,lengths)

        # Generate the huffman codes
        huffcode=huffman_codes(lengths)
#        print("Huffcode", huffcode)

        huffval= []
#        total=0
#        for i in lengths: total+=i
        for i in huffcode:
            huffval.append(data[offset])
            offset+=1

#        print(huffval)

#        huffval=GetArray("B", data[offset : offset + huffcode], huffcode)
#        total+=huffcode

#        if offset+total>len(data): return -offset # hibas
#        offset+=total

        # Generate lookup tables
        if Tc==0:
            huffman_dc_tables[Th]= map_codes_to_values(huffcode, huffval)
        else:
            huffman_ac_tables[Th]= map_codes_to_values(huffcode, huffval)

      return offset


    bits_avail=0
    bits_data=0

    # baseline DC+AC es progressive DC parser:
    def read_data_unit(byte_stream,comp,dmax):
       nonlocal bits_avail
       nonlocal bits_data

#       refining = (A&15) and (((A>>4)-(a&15))==1)
#       refining = (A&15)!=0

#       data=[0]*64
       dc=0
       d=0

       huff_tbl= huffman_dc_tables[comp['Td']]
       # Fill data with 64 coefficients
       while d<dmax:

          key=0
          key_len=-1
          for bits in range(1, 17):
#             key<<= 1

             # Get one bit from bit_stream

             if bits_avail<=0:
                bits_data=next(byte_stream)
                if bits_data<0:
                    if d>0: print("EOI found before finish MCU block (%d/%d)"%(d,dmax))
                    return bits_data # EOF
                bits_avail+=8

             bits_avail-=1
#             key |= (bits_data >> bits_avail)&1
             key = (key<<1) | ((bits_data >> bits_avail)&1)

    #         print(bits,val)
             # If huffman code exists
             try:
                key_len= huff_tbl[(bits,key)]
    #            print(bits,key,key_len)
                break
             except:
                pass


          if key_len<0:
             print( (bits, key, bin(key)), "key not found (DC)" )
             for k in huff_tbl: print(k,huff_tbl[k])
             return -2 #break

          # If ZRL fill with 16 zero coefficients
          if key_len==0xF0:
             d+=16
#             for i in range(16): data.append(0)
             continue

          # If not DC coefficient
          if d==0:
             huff_tbl= huffman_ac_tables[comp['Ta']]
          else: #if d!=0:
             # If End of block
             if key_len==0x00:
                d=dmax #64
                break

             # The first part of the AC key_len
             # is the number of leading zeros
             d+=key_len >> 4
             key_len&= 0x0F

#          if d>dmax: break

          if key_len!=0:
             # The rest of key_len is the amount of "additional" bits
             while bits_avail<key_len:
                x=next(byte_stream)
                if x<0: return x # EOF
                bits_data=(bits_data<<8)|x
                bits_avail+=8

             ######################################################
             bits_avail-=key_len
             if d==0: # csak a DC erdekes nekunk!
                sign=bits_data>>(bits_avail+key_len-1)
                out=(bits_data>>bits_avail) & ((1<<key_len)-1)
                dc=out if (sign&1) else out-((1 << key_len)-1)
#             data[d]=out if (sign&1) else out-((1 << key_len)-1)
             ######################################################

          d+=1

       if d!=dmax: print("Wrong MCU block size", d)
       return 32768+dc #d #ata



    # progressive scan eseten az AC-t maskepp kell beolvasni, egybe van az osszes block:
    def read_data_unit_AC(byte_stream,comp,dmin,dmax):
      nonlocal bits_avail
      nonlocal bits_data

      # Fill data with 64 coefficients
      huff_tbl= huffman_ac_tables[comp['Ta']]
      current_mcu=0
      eob_run=0
      while True:
        d=dmin
        while d<=dmax:

          #---------------- read huffman code ----------------------
          key=0
          key_len=-1
          for bits in range(1, 17):
#             key<<=1
             # Get one bit from bit_stream
             if bits_avail<=0:
                bits_data=next(byte_stream)
                if bits_data<0: return current_mcu  #bits_data # EOF
                bits_avail+=8

             bits_avail-=1
#             key |= (bits_data >> bits_avail)&1
             key = (key<<1) | ((bits_data >> bits_avail)&1)

             # If huffman code exists
             try:
                key_len= huff_tbl[(bits,key)]
#                print(d,bits,"0x%02X"%(key),key_len)
                break
             except:
                pass

          if key_len<0:
             print( (bits, key, bin(key)), "key not found (AC)" )
             return current_mcu #break
          #-----------------------------------------------------------

          if key_len==0x00:
              break

          # If ZRL fill with 16 zero coefficients
          if key_len==0xF0:
              d+=16
              continue

          if key_len&0x0F==0: # EOB run
              d=(1+(d//64))*64
              key_len=key_len>>4
              while bits_avail<key_len:
                x=next(byte_stream)
                if x<0: return current_mcu # EOF
                bits_data=(bits_data<<8)|x
                bits_avail+=8
              bits_avail-=key_len
              out=(bits_data>>bits_avail) & ((1<<key_len)-1)
              current_mcu+= ((1 << key_len) | out)-1
              break

          d+=key_len>>4
          key_len&=0x0F

          if key_len>0:
             # The rest of key_len is the amount of "additional" bits
             while bits_avail<key_len:
                x=next(byte_stream)
                if x<0: return current_mcu # EOF
                bits_data=(bits_data<<8)|x
                bits_avail+=8

             #data[d]=get_bitss(key_len, byte_stream)
             ######################################################
#             sign=bits_data>>(bits_avail-1)
             bits_avail-=key_len
#             out=(bits_data>>bits_avail) & ((1<<key_len)-1)
#             data[d]=out if (sign&1) else out-((1 << key_len)-1)
             ######################################################
             d+=1

        current_mcu+=1

      return current_mcu



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
            s+="\x1b[38;2;%d;%d;%dm\u2584"%ColorConversion(dc2)
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
#            f=[0,0.25,0.5,0.75,1][i]
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

#        r,g,b=int(rgb[0]),int(rgb[1]),int(rgb[2])
#        if r<128 and g<128 and b<128:
#            return (r>>6)|((g>>6)<<1)|((b>>6)<<2)  # normal colors
#        return 60 + (r>>7)|((g>>7)<<1)|((b>>7)<<2) # bright colors

    def print_aa16(dcline,prevdcline,dither=False):
        s=u""
        if not prevdcline: prevdcline=dcline
        for dc1,dc2 in zip(prevdcline,dcline):
            if dither: s+=rgb16dither(ColorConversion(dc1)) ; continue
            s+="\x1b[%dm"%(40+rgb16(ColorConversion(dc1)))
            s+="\x1b[%dm\u2584"%(30+rgb16(ColorConversion(dc2)))
        #print(s,'\x1b[0m')
        sys.stderr.write(s+'\x1b[0m\n')
        return


    def StartOfScan(data,rst):
        hdrlen = data[3]+(data[2]<<8)+2
        Ns=data[4]
#        print("---------------------------------------------------------------------------------------------")
#        print(hdrlen,len(data),"components in scan:",Ns)
        p=5
        cids=[]
        for i in range(Ns):
          # Read the scan component selector
          Cs= data[p]
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

        # Should be zero if baseline DCT
        Ss= data[p]
        # Should be 63 if baseline DCT
        Se= data[p+1]
        # Should be zero if baseline DCT
        A= data[p+2]
        p+=3
        # Ns:3 Ss:0 Se:63 A:00 baseline
        # Ns:3 Ss:0 Se:0 A:00  progressive
        print( "Ns:%d Ss:%d Se:%d A:%02X C:%d Huff: DC=%d/AC=%d --------------------------------------------------------------------------------------------" % (Ns, Ss, Se, A, Cs, Td, Ta) )
#        num_components= Ns
#        dc= [0 for i in range(num_components+1)]

#        print("after parsing header:",p,hdrlen)
        t0=time.time()
        mcu_cnt=0

        # ---------------------------------------------------#
        def byte_reader():
            nonlocal data
            nonlocal p
            nonlocal mcu_cnt
            while p<len(data):
                c=data[p]
                if c==0xFF:
                    if data[p+1]==0: p+=1  # FF 00 ---> FF
                    elif data[p+1] in [0xD9,0xDA,0xC4]: break # EOI/SOS/DHT
                    elif data[p+1]<0xD0 or data[p+1]>0xD7: # not restart marker?
                        print("!!! unexpected marker 0xFF%02X at mcu #%d pos %d"%(data[p+1],mcu_cnt,p))
                p+=1
                yield c
            while True:
                yield -1 # EOF
        # ---------------------------------------------------#

#        print("Start bitstream parsing at",p)
        byte_stream=byte_reader()
        nonlocal bits_avail
        nonlocal bits_data
        bits_avail=0
        EOF=False
        rcnt=0

        # MCU-k szama vizszintes es fuggoleges iranyban:
        mcuw,mcuh=component["dimensions"]['MW'],component["dimensions"]['MH']
        # a subsampled componentnel (altalaban a luma) 8x8 blokkok vannak a nagyobb MCU helyett:
        if Ns==1 and (component[Cs]['H']*component[Cs]['V'])>1: mcuw,mcuh=((component["dimensions"]['W']+7)//8),((component["dimensions"]['H']+7)//8)
        mcu_max=mcuw*mcuh

        if Ss>0: # progressive AC pass  (mivel ez mindig 8x8 blokkszamot ad vissza, el kell osztani a blokkszam/mcu (subsampling) ertekkel)
          if (A>>4)==0: mcu_cnt+=read_data_unit_AC(byte_stream,component[Cs],Ss,Se) #//(component[Cs]['H']*component[Cs]['V'])
        else:
         ########################################################
         dc=[]
         prevdc=None
         dc0=[0]*Ns
         dc1=[0]*Ns
         dcy=0
         dcx=0
         mcuws=max(int(mcuw/160),1)
         if mcuw/mcuws>200: mcuws+=1
#         mcuhs=mcuws*2
#         if component[component["IDs"][0]]['H']<component[component["IDs"][0]]['V']: mcuhs//=2
#         if component[component["IDs"][0]]['H']>component[component["IDs"][0]]['V']: mcuhs*=2
         mcuhs=(mcuws*2*component[component["IDs"][0]]['H'])//component[component["IDs"][0]]['V']
         print("ASCII scaling",mcuws,mcuhs,mcuw//mcuws,mcuh//mcuhs)
         ########################################################
         while not EOF:

           # handle RST (restart marker)
           if rst>0 and mcu_cnt>0 and mcu_cnt%rst==0:
#              print("Reset! mcu #%d  bits_avail=%d p=%d marker[p]=0x%02X%02X"%(mcu_cnt,bits_avail,p,data[p],data[p+1]))
              bits_avail=0 # skip bits up to byte boundary
              dc0=[0]*Ns   # reset DC to zero
              rst_m1=next(byte_stream) # skip RST marker
              rst_m2=next(byte_stream)
              if rst_m1!=0xFF or rst_m2<0xD0 or rst_m2>0xD7: break # valami nem OK!

           # read MCU block: (HxV 8x8 blocks per component)
           for i in range(Ns):
            C=cids[i]
            comp=component[C]
            for j in range(comp['H']*comp['V'] if Ns>1 else 1):
              if (A>>4)!=0:
                # DC refining bits (1 bit/component/mcu)
                if bits_avail<=0:
                  bits_data=next(byte_stream)
                  if bits_data<0: EOF=True
                  bits_avail=8
                bits_avail-=1
                #mcu=(32768+256)*((bits_data>>bits_avail)&1) # mind1, ugyse latszik...
              elif not EOF:
                # Huffman-encoded 8x8 block:
                mcu=read_data_unit(byte_stream,comp,Se+1)
                if mcu<0:
                  EOF=True
                else:
                  dc0[i]+=mcu-32768
                  dc1[i]=(dc0[i]<<(A&15))*quant[comp['Tq']][0]

           if not EOF:
            if (dcx%mcuws)==0 and dcx<mcuws*160: dc.append(dc1[0:Ns])
            dcx+=1
            mcu_cnt+=1
            # display scan:
            if mcu_cnt%mcuw==0:
              if (A>>4)==0:
                if dcy%mcuhs==0: prevdc=dc
                if dcy%mcuhs==(mcuhs//2): print_aa16(dc,prevdc,True)
              dcy+=1
              dcx=0
              dc=[]

        t0=time.time()-t0
        if mcu_cnt>0: print("%6d/%6d MCU%s blocks read!  p:%8d +%d bits  [%02X%02X]   time: %5d ms   (%d kB/s)"%(mcu_cnt,mcu_max,"!!!" if mcu_cnt<mcu_max or mcu_cnt>mcu_max+7 else "",p,bits_avail,data[p] if p<len(data) else 0,data[p+1] if p+1<len(data) else 0,int(t0*1000.0),int(p/1024/t0)))


        #######
        p=hdrlen
        l=len(data)-1
        cnt0=0
        cntRST=0
        while p<l:
            q=data.find(0xFF,p)
            if q<=0: break
#            if data[q+1]!=0: print("%8d  %02X"%(q,data[q+1]))
            m=data[q+1]
            if m!=0 and not (m>=0xD0 and m<=0xD8): # escape, restart markers
                print("%d reset markers && %d escapes in %d bytes image data skipped"%(cntRST,cnt0,q))
                sys.stdout.flush()
#                for s in [b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF']:
                for s in [bytearray(512), bytearray([0xFF] * 4)]:
                    r=data.find(s,hdrlen,q)
                    if r>=0: print("WARNING: %d x 0x%02X bytes repeating at %d"%(len(s),s[0],r))
                print("MarkerAfterScan: FF%02X"%(m))
                return q
            if m==0: cnt0+=1
            else: cntRST+=1
            p=q+1
        return -1









    def DecodeMPExt(data):
      try:
        endian=data[0:4]
        offs,=unpack("<L",data[4:8])
        cnt,=unpack("<H",data[offs:offs+2])
        print(endian,offs,cnt)
        offs+=2+12 # skip cnt+version
        icnt,=unpack("<L",data[offs+8:offs+12])
        isize,ioffs=unpack("<LL",data[offs+12+4:offs+12+12])
        print(icnt,isize,ioffs)
        for i in range(icnt):
            attr,size,offs,dep1,dep2=unpack("<LLLHH",data[ioffs+i*16:ioffs+i*16+16])
#            print(attr,size,offs,dep1,dep2)
            print("Individual image #%d: 0x%X  (%d bytes)"%(i,offs,size))

#        for i in range(512): print(" %02X"%(data[i]),end='')
#        print("")

      except:
        return -1
      return len(data)


    data=d
    errcnt=0
    rst=0
    mpext=False
    markcnt={0xFFD8:0,0xFFD9:0,0xFFDA:0,0xFFC0:0,0xFFC2:0}
    while len(data)>1:
        if data[0]!=0xFF:
            p=data.find(0xFF)
            if p<=0: p=len(data)
            print("ERROR! skipping %d bytes"%(p))
            errcnt+=5
            data=data[p:]
            # erdemes egyaltalan folytatni? ez mar innen szar szokott lenni...
            continue

        marker = data[1]|(data[0]<<8)
        if marker not in [0xffd8,0xffd9] and len(data)>=4:
            lenchunk = data[3]+(data[2]<<8)+2
            print("0x%04X (%d) %s"%(marker,lenchunk,marker_mapping.get(marker)))
        else:
            print("0x%04X %s"%(marker,marker_mapping.get(marker)))
        try:
            markcnt[marker]+=1
        except:
            markcnt[marker]=1

        if marker == 0xffd8:
            data = data[2:]
            continue

        if marker == 0xffd9:
            print(markcnt)
            if markcnt[0xFFD8]!=1 or markcnt[0xFFD9]!=1 or markcnt[0xFFDA]<1 or markcnt[0xFFC0]+markcnt[0xFFC2]!=1:
                print("Bad marker count!")
                errcnt+=10

            p=2
            # skip FF bytes at the end of file:
#            while p<len(data):
#                if data[p]!=0xFF: break
#                p+=1
            # skip zero bytes at the end of file:
            while p<len(data):
                if data[p]!=0: break
                p+=1
            if p>2+3: print("%d zero bytes skipped"%(p-2))
            data=data[p:]

            # check for extra jpeg thumbnail/preview:
            p=data[:32].find(b'\xff\xd8')
            if p>=0 and len(data)>p+8:
#            if len(data)>8 and data[0]==0xFF and data[1]==0xD8:
                print("WARNING: %d bytes extra image !!!\n"%(len(data)))
                errcnt+=testjpeg(data[p:])
            elif data.startswith(b'\x01\n\x0e\x00\x00\x00Image_UTC_Data'):
                print("Skipping %d bytes Image_UTC_Data"%(len(data)))
            else:
#            if len(data)>=6 and not mpext:
                if len(data)>=4:
                    print("WARNING: %d bytes left:  %02X %02X %02X %02X"%(len(data),data[0],data[1],data[2],data[3]))
                    print(data[:128].hex(' '))
                    print(data[:128])
#                    errcnt+=1
            return errcnt

        if marker == 0xffda:
            hl=StartOfScan(data,rst)
            if hl<=0 or hl+2>len(data): break # EOF reached
            data = data[hl:]
            # next marker check
            marker = data[1]|(data[0]<<8)
#    420 MarkerAfterScan: FFC4
#  20900 MarkerAfterScan: FFD9
#   7131 MarkerAfterScan: FFDA
            if marker not in [0xffda,0xffd9,0xFFC4]:
                print("ERROR! bad marker after scan data: 0x%04X  "%(marker),marker_mapping.get(marker))
                errcnt+=10
                return errcnt
        else:
            lenchunk = data[3]+(data[2]<<8)+2
            if marker==0xffc4:   # huffman table
                hl=decodeHuffman(data[4:lenchunk])
#                print(hl,lenchunk-4)
            elif marker==0xffc0 or marker==0xffc2: # start of frame
                bits, height, width, components = unpack(">BHHB", data[4:4+6])
                if bits!=8 or components not in [1,3,4] or width>8*height or height>5*width or width>2*8192 or height>2*8192 or width<16 or height<16:
                    print("WARNING! ",end = '')
                    errcnt+=1   
                    # ez jo: WARNING! dimensions: 1016 x 1002 x 4 / 8bit , ez is: WARNING! dimensions: 1252 x 1075 x 4 / 8bit
                    # ez is: WARNING! dimensions: 14032 x 9922 x 3 / 8bit
                    # WARNING! dimensions: 1970 x 8120 x 3 / 8bit
                print("dimensions: %d x %d x %d / %dbit"%(width,height,components,bits))
                component["dimensions"]={'W':width,'H':height}
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
                    print("  component #%d: id=0x%02X sampling=%dx%d quant=0x%X"%(i,C,H,V,Tq))
                    component["IDs"].append(C)
                    component[C]= {}
                    # Assign horizontal sampling factor
                    component[C]['H']= H
                    # Assign vertical sampling factor
                    component[C]['V']= V
                    # Assign quantization table
                    component[C]['Tq']= Tq
                Hmax*=8
                Vmax*=8
                component["dimensions"]['MW']=((width+Hmax-1)//Hmax)
                component["dimensions"]['MH']=((height+Vmax-1)//Vmax)
                print(component["dimensions"])

#                print(hl,lenchunk-4,"dimensions: %d x %d x %d / %dbit"%(width,height,components,bits))
#                print(hl,lenchunk-4)
            elif marker==0xffdb: # quant tables
                hl=DefineQuantizationTables(data[4:lenchunk])
#                print(hl,lenchunk-4)
            elif marker==0xffe2: # MP 
#    828 APP2 extension:  b'FPXR'
#   7465 APP2 extension:  b'ICC_'
#   1824 APP2 extension:  b'MPF\x00'
                print("APP2 extension: ",data[4:8])
                if data[4:8]==b'MPF\x00':
                    hl=DecodeMPExt(data[8:lenchunk])+4
                    mpext=True
                else: hl=lenchunk-4
#                print(hl,lenchunk-4)
            elif marker==0xffdd: # reset interval
                rst = data[5]+(data[4]<<8)
                print("RESET interval =",rst)
                hl=2
#                print(hl,lenchunk-4)
            else:
                hl=lenchunk-4 # unknown type
            if hl<0:
                print("ERROR! cannot parse %d bytes"%(lenchunk-4+hl))
                errcnt+=10
            elif hl!=lenchunk-4:
                print("ERROR! only %d of %d bytes parsed"%(hl,lenchunk-4))
                errcnt+=10
            data = data[lenchunk:]

    print("ERROR! EOF reached before EOI marker!")
    errcnt+=10
    return errcnt

#f=open("/home/spamwall/backup/ext/jpg/0048b1fb20d8f0c6_19798640__IMG_3808.jpg","rb")
#f=open("/home/spamwall/backup/ext/jpg/fec98baf1e9f4697_17229344__BCR-114C-38.jpg","rb")

if __name__ == "__main__":
  path="jpeg2/"
  for n in os.listdir(path):
    print("\n\n==================== %s ======================\n"%(n))
    res=testjpeg(open(path+n,"rb").read())
    if res>0: print("!!!HIBAS!!!",res)
