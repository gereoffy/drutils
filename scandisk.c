
#define _GNU_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void analyze(unsigned char* data,int len,long long fpos){
    unsigned int magic=*((unsigned int*)data);
    unsigned int magic2=*((unsigned int*)(data+4));
    if(magic==0x58444E49){      // NTFS:INDX
        unsigned int used=*((unsigned int*)(data+28)); // Size of Index Node
        unsigned int size=*((unsigned int*)(data+32)); // Allocated_Size_of_Index_Node
        unsigned int vcn=*((unsigned int*)(data+16));  // Virtual Cluster Number (VCN) of the index entry
        printf("%012llX: NTFS:INDX #%d  %d/%d\n",fpos,vcn,used,size+24);
    } else
    if(magic==0x454C4946){      // NTFS:FILE
        unsigned int used=*((unsigned int*)(data+24)); // Used entry size
        unsigned int size=*((unsigned int*)(data+28)); // Total entry size
        unsigned int mft=*((unsigned int*)(data+44));  // elvileg itt tarolja az mft szamat
        printf("%012llX: NTFS:MFT #%d  %d/%d\n",fpos,mft,used,size);
    } else
    if(magic==0x04034B50){      // ZIP
//        printf("%012llX: ZIP v%d%s\n",fpos,256*data[5]+data[4],memmem(data,len,"[Content_Types].xml",19)?"":" MSOffice");
//        printf("%012llX: ZIP v%d comp=%d%s\n",fpos,256*data[5]+data[4],256*data[9]+data[8],memcmp(data+30,"[Content_Types].xml",19)?"":" MSOffice");
        printf("%012llX: ZIP v%d comp=%d '%.*s'\n",fpos,256*data[5]+data[4],256*data[9]+data[8], data[26],data+30);
    } else
    if(magic==0xE011CFD0 && magic2==0xE11AB1A1){      // OLE2
        printf("%012llX: OLE2 v%d.%d\n",fpos,data[26],data[24]);
    } else
    if(magic==0x474E5089 && magic2==0x0A1A0A0D && !memcmp(data+12,"IHDR",4)){      // PNG (first chunk must be IHDR)
        printf("%012llX: PNG %dx%dx%d\n",fpos, 256*data[16+2]+data[16+3], 256*data[20+2]+data[20+3],data[24]);
    } else
    if(magic==0x74725C7B && magic2==0x615C3166){      // RTF
        printf("%012llX: RTF\n",fpos);
    } else
    if(magic==0x324C4624 && magic2==0x29232840){      // SPSS  24 46 4C 32 │ 40 28 23 29
        printf("%012llX: SAV %.56s\n",fpos,data+8);
    } else
    if(magic==0x46445025 && data[4]==0x2D && data[6]==0x2E && data[7]>=0x30 && data[7]<=0x39){
        printf("%012llX: %.7s\n",fpos,data+1);  // PDF  # 25 50 44 46 │ 2D 31 2E 37  
    } else
    if( (magic&0xF0FFFFFF)==0xE0FFD8FF){   // FF D8 FF Ex
        int l=0; while(data[6+l]>=32 && data[6+l]<127) l++; // find ascii string len
        printf("%012llX: JPEG %02X:%.*s\n",fpos,data[3],l,data+6);
    } else
    if( magic2==0x70797466 && (magic&0xFFFFFF)==0 && data[3]>=16 ){   // 66 74 79 70
        printf("%012llX: MOV:%.4s %d\n",fpos,data+8, data[3] );
    }
//    else printf("%12llX: %08X %08X %d\n",fpos,magic,magic2,12345);

}


#define BUFFSIZE (256*1024)
unsigned char buffer[BUFFSIZE];

int main(){
  FILE* f=fopen("/dev/nvme1n1p3","rb");
  long long fpos=0;
  while(fread(buffer,BUFFSIZE,1,f)==1) for(int bpos=0;bpos<BUFFSIZE;bpos+=512){
    analyze(buffer+bpos,512,fpos);
    fpos+=512;
  }
}
