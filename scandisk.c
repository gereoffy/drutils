
#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int analyze(unsigned char* data,int len,long long fpos){
    unsigned int magic=*((unsigned int*)data);
    unsigned int magic2=*((unsigned int*)(data+4));
    if(magic==0x58444E49){      // NTFS:INDX
        unsigned int used=*((unsigned int*)(data+28)); // Size of Index Node
        unsigned int size=*((unsigned int*)(data+32)); // Allocated_Size_of_Index_Node
        unsigned int vcn=*((unsigned int*)(data+16));  // Virtual Cluster Number (VCN) of the index entry
        size+=24;
        if(used<=size && size<=16384 && size>=1024 && !(size&511)){
            printf("%012llX: NTFS:INDX #%d  %d/%d\n",fpos,vcn,used,size);
            return 64;
        } else return 0; // invalid
    }
    if(magic==0x454C4946){      // NTFS:FILE
        unsigned int used=*((unsigned int*)(data+24)); // Used entry size
        unsigned int size=*((unsigned int*)(data+28)); // Total entry size
        unsigned int mft=*((unsigned int*)(data+44));  // elvileg itt tarolja az mft szamat
        if(used<=size && size<=16384 && size>=1024 && !(size&511)){
            printf("%012llX: NTFS:MFT #%d  %d/%d\n",fpos,mft,used,size);
            return 128;
        } else return 0; // invalid
    }
    if(magic==0x04034B50){      // ZIP
//        printf("%012llX: ZIP v%d%s\n",fpos,256*data[5]+data[4],memmem(data,len,"[Content_Types].xml",19)?"":" MSOffice");
//        printf("%012llX: ZIP v%d comp=%d%s\n",fpos,256*data[5]+data[4],256*data[9]+data[8],memcmp(data+30,"[Content_Types].xml",19)?"":" MSOffice");
        printf("%012llX: ZIP v%d comp=%d '%.*s'\n",fpos,magic2&0xFFFF,256*data[9]+data[8], data[26],data+30);
        return (magic2&0xFFFF)==8 ? 1 : 0;
    }
    if(magic==0xE011CFD0 && magic2==0xE11AB1A1){      // OLE2
        printf("%012llX: OLE2 v%d.%d\n",fpos,data[26],data[24]);
        return 1;
    }
    if(magic==0x74725C7B && magic2==0x615C3166){      // RTF
        printf("%012llX: RTF\n",fpos);
        return 1;
    }
    if(magic==0x324C4624 && magic2==0x29232840){      // SPSS  24 46 4C 32 │ 40 28 23 29
        printf("%012llX: SAV %.56s\n",fpos,data+8);
        return 1;
    }
    if(magic==0x46445025 && data[4]==0x2D && data[6]==0x2E && data[7]>=0x30 && data[7]<=0x39){
        printf("%012llX: %.7s\n",fpos,data+1);  // PDF  # 25 50 44 46 │ 2D 31 2E 37  
        return 1;
    }
    if(magic==0x474E5089 && magic2==0x0A1A0A0D && !memcmp(data+12,"IHDR",4)){      // PNG (first chunk must be IHDR)
        printf("%012llX: PNG %dx%dx%d\n",fpos, 256*data[16+2]+data[16+3], 256*data[20+2]+data[20+3],data[24]);
        return 2;
    }
    if( (magic&0xF0FFFFFF)==0xE0FFD8FF){   // FF D8 FF Ex
        int l=0; while(data[6+l]>=32 && data[6+l]<127) l++; // find ascii string len
        printf("%012llX: JPEG %02X:%.*s\n",fpos,data[3],l,data+6);
        return !memcmp(data+6,"JFIF",4) || !memcmp(data+6,"Exif",4) ? 2 : 0;   //   1788  JPEG E0:JFIF    5323  JPEG E1:Exif
    }
    if( magic2==0x70797466 && (magic&0xFFFFFF)==0 && data[3]>=16 ){   // 66 74 79 70
        printf("%012llX: MOV:%.4s %d\n",fpos,data+8, data[3] );
        return 2;
    }
//    else printf("%12llX: %08X %08X %d\n",fpos,magic,magic2,12345);
    return 0;
}

int entropy(unsigned char* data,int len){
    unsigned int* p=(unsigned int*)data;
    len/=sizeof(unsigned int);
    int i=1;
    while(i<len && p[i]==p[0]) i++;
    return (i==len)?0:1;
}

#define BUFFCOUNT 128
#define BUFFSIZE (8*1024*1024)
unsigned char buffer[BUFFSIZE];

int main(){
  FILE* f=fopen("/dev/nvme0n1p3","rb");
  long long fpos=0;
  int c=0;
  while(fread(buffer,BUFFSIZE,1,f)==1){
    int e=0,f=0;
    if(!((c++)%BUFFCOUNT)) fprintf(stderr,"\n%8d GB - ",(int)(fpos>>30));
    for(int bpos=0;bpos<BUFFSIZE;bpos+=512){
      f|=analyze(buffer+bpos,512,fpos);
      e+=entropy(buffer+bpos,512);
      fpos+=512;
    }
    if(f) // found known file format
        fputc( (f&128)?'M': (f&64)?'I': (f&1)?'d': (f&2)?'p' : '?' ,stderr); // MFT/INDX/doc/pic
    else // raw data
        fputc( (e==0)?'0' : (e==BUFFSIZE/512)?'*' : '.' ,stderr); // null / full / mixed
  }
}

