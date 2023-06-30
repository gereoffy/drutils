#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define BLKSIZE 4096
//0x1000

static int blksize=4096;  // ntfs cluster alapegysege
static long long part_start=0;
static unsigned char fnev[65536];
static int debug=1;

int unicode16to8(unsigned char* out,unsigned short* in,unsigned char len){
    int l=0;
    int i;
    for(i=0;i<len;i++){
//        printf("  char#%d: %d '%c'\n",i,in[i],in[i]);
        if(in[i]>=32 && in[i]<256) out[l++]=in[i];
    }
    out[l]=0; return l;
}

// SIZEOF  short=2  int=4  long=8  longlong=8
long long readsint(void* p,char l){
//    unsigned char* q=p;
//    printf("readsint(%d): %02X %02X %02X %02X   %08X  (%08X)\n",l, q[0],q[1],q[2],q[3],  *((int*)p),  *((int*)(p-1)));
    switch(l){
    case 0: return 0;
    case 1: return *((char*)p);
    case 2: return *((short*)p);
    case 3: return (*((int*)(p-1)))/256;
    case 4: return *((int*)p);
    case 8: return *((long long*)p);
    }
    return -1;
}



//00F0  entry  T=1494622907980 (2105.04.15)   size=88 size=635637MB  name=0x10 (0)
//0148  entry  T=1494622907980 (2105.04.15)   size=88 size=1364500053MB  name=0x10 (0)

void parseindx(unsigned char* p){
    int i;
    unsigned int offs=*((unsigned int*)(p+0x18));
    unsigned int size=*((unsigned int*)(p+0x1C));
    printf("INDX offs=0x%X  size=0x%X\n",offs,size);
    unsigned int o=0x18+offs;
    while(o<size){
	unsigned short s=*((unsigned short*)(p+o+8));
	unsigned short n=*((unsigned short*)(p+o+10));
	unsigned long long t=*((unsigned long long*)(p+o+0x30));
	t/=10000000;
	t-=11644473600;
	time_t timep=(unsigned int)t;
	struct tm *tt=localtime(&timep);

	unsigned long long fs=*((unsigned long long*)(p+o+0x40));
	int nl=p[o+0x50];
      if(n!=0x10 || nl>0){
	printf("%04X  entry  T=%8lld (%d.%02d.%02d)   size=%d size=%dMB  name=0x%X (%d) ",o,t,
		1900+tt->tm_year,1+tt->tm_mon,tt->tm_mday,  s,(int)(fs/(1024*1024)),n,nl);
//	printf("%04X  entry  T=%8lld (%s)   size=%d size=%dMB  name=0x%X (%d) ",o,t,
//		ctime(&timep),  s,(int)(fs/(1024*1024)),n,nl);
	for(i=0;i<nl;i++) putchar(p[o+0x52+2*i]);
	printf("\n");
      }
	if(s<16 || s>=size) break; // WTF
	o+=s;
    }
}


void parsefile(unsigned char* p,long long fpos){
// https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#file_reference
    unsigned int o=*((unsigned short*)(p+20));
    unsigned int size=*((unsigned int*)(p+28));
    unsigned int flags=*((short*)(p+22));
    //if(debug) 
    printf("FILE size=%d offs=0x%X  flags=0x%X  refcnt=%d  fpos=0x%llX\n",size,o,flags,*((short*)(p+18)),fpos);
//    if(!(flags&1)) return; // MFT_RECORD_IN_USE https://github.com/libyal/libfsntfs/blob/main/documentation/New%20Technologies%20File%20System%20(NTFS).asciidoc#mft_entry_flags
//    printf("FILE size=%d offs=0x%X  fileref=0x%lld  fpos=0x%llX\n",size,o,*((long long*)(p+32)),fpos);
    if(size>blksize) return; // bad size
    fnev[0]=0;
    while(o<size){
	// attribs
	int t=*((unsigned int*)(p+o));
	if(t==-1) break; // EOA
	int l=*((unsigned int*)(p+o+4));
	if(l<=0) break; // bad len
	int nl=p[o+9];
	int no=*((unsigned short*)(p+o+10));
	int fl=*((unsigned short*)(p+o+12));
	int id=*((unsigned short*)(p+o+14));

	char meta[1024];
	int nl2=0;
	meta[0]=0;
	if(nl>0) nl2=unicode16to8(meta,(unsigned short*)(p+o+no),nl);

	if(debug){
	    printf("  attr type=0x%02X len=%d resident=%d flag=0x%X id=0x%X  start=0x%X  name(len=%d/%d,off=%d): '%s'\n",t,l,p[o+8],fl,id,o+16,nl,nl2,no, meta);
	}

	
	if(p[o+8]==0){	// resident
//	  int attsize=*((unsigned int*)(p+o+16));
	  int attoffs=*((unsigned short*)(p+o+20));
	  if(t==0x30){
	    int fl=*((unsigned int*)(p+o+attoffs+56));
	    int l2=unicode16to8(fnev,(unsigned short*)(&p[o+attoffs+66]),p[o+attoffs+64]);
	    if(debug) printf("    fnev='%s' fmt=%d flags=0x%X len=%d->%d\n",fnev,p[o+attoffs+65],fl,p[o+attoffs+64],l2);
	  }
	} else {	// not resident
	  unsigned long long vcn1=*((unsigned long long*)(p+o+16)) & 0x0000FFFFFFFFFFFFLL;
	  unsigned long long vcn2=*((unsigned long long*)(p+o+16+8)) & 0x0000FFFFFFFFFFFFLL;
	  int runs=*((unsigned short*)(p+o+16+16));
	  int compr=*((unsigned short*)(p+o+16+18));
	  unsigned long long size1=*((unsigned long long*)(p+o+16+24)) & 0x0000FFFFFFFFFFFFLL;
	  unsigned long long size2=*((unsigned long long*)(p+o+16+32)) & 0x0000FFFFFFFFFFFFLL;
	  unsigned long long size3=*((unsigned long long*)(p+o+16+40)) & 0x0000FFFFFFFFFFFFLL;
//	  if(debug) printf("    VCN %lld - %lld  Size: %lld/%lld/%lld  Name: '%s'  runs.offs=%d/len=%02X   fpos=0x%X%03X\n",vcn1,vcn2,size1,size2,size3,fnev,runs,p[o+runs],(int)(fpos>>12),o+runs);
	  if(debug) printf("    VCN %lld - %lld  t=%02X  Size: %lld/%lld/%lld  Name: '%s'  runs.offs=%d/len=%02X/fpos=0x%llX\n",vcn1,vcn2,t,size1,size2,size3,fnev,runs,p[o+runs],fpos+o+runs);
	  // parse runs:
	  unsigned char* q=p+o+runs;
	  int runcnt=0;
	  long long rc=0;
	  while(q<p+size){
	    unsigned char x=*q++;
//	    printf("    run.len=%02X\n",x);
	    if((x&15)==0 || (x&15)>4) break; // vege!
	    long long rs=readsint(q,x&15);
	    q+=x&15;
//	    long long rc=readsint(q,x>>4);
	    rc+=readsint(q,x>>4);
	    q+=x>>4;
//            if(!runcnt) printf("cluster %lld / 0x%X000 : '%s'  %lld bytes  (%d)  %s\n",rc,(unsigned int)((rc*blksize+part_start)>>12),fnev,size2,(int)(vcn2-vcn1),(rs!=1+vcn2-vcn1)?"FRAGMENTED":"OK");
            if(!runcnt) printf("cluster %lld / 0x%llX : %s '%s'  %lld bytes  (%d)  %s\n",rc,rc*blksize+part_start,(flags&2)?"DIR!":(nl?meta:"FILE"),fnev,size2,(int)(1+vcn2-vcn1),(rs!=1+vcn2-vcn1)?"FRAGMENTED":"OK");
	    if(debug) printf("    run#%d: len=%02X size=%lld cluster=%lld\n",runcnt,x,rs,rc);
	    if(!vcn1 && vcn2>100 && !strcmp(fnev,"$MFT")){
	        if(!runcnt){
	            int blksize=size1/(vcn2+1);
	            long long part_start=fpos-rc*blksize; // a $MFT az mft#0-as file, tehat sajat magara mutat!
	            printf("!!! FOUND MFT !!!  blksize=%d  partition_start=0x%llX (%d. sector)  cluster=%lld\n",blksize,part_start,(int)(part_start/512),rc);
	        }
	        printf("dd if=/dev/sdb bs=%d skip=%lld count=%lld conv=noerror\n",blksize,rc+part_start/blksize,rs);
	    }
	    runcnt++;
	  }
	}
	o+=l;
    }
}


char* old_detect(unsigned char* buffer){
    unsigned int magic=*((unsigned int*)buffer);
    switch(magic){
	case 0x04034B50:
	    if(memmem(buffer,BLKSIZE,"[Content_Types].xml",18)){
		if(memmem(buffer,BLKSIZE,"document.xml",12)) return "DOCX";
		if(memmem(buffer,BLKSIZE,"workbook.xml",12)) return "XLSX";
		if(memmem(buffer,BLKSIZE,"presentation",12)) return "PPTX";
		if(memmem(buffer,BLKSIZE,"word/",5)) return "DOCX";
		if(memmem(buffer,BLKSIZE,"xl/_rels",8)) return "XLSX";
		if(memmem(buffer,BLKSIZE,"ppt/",4)) return "PPTX";
		return "DOCX/XLSX/PPTX";
	    }
	    return "ZIP";
	case 0xE0FFD8FF:
	case 0xE1FFD8FF:
	    return "JPG";
	case 0x2A004D4D:
	case 0x002A4949:
	    return "TIFF";
	case 0xE011CFD0:    return "OLE";
	case 0x74725C7B:    return "RTF";
	case 0x21726152:    return "RAR";
	case 0xAFBC7A37:    return "7z";
	case 0x46445025:    return "PDF";
	case 0x53504238:    return "PSD";
	case 0x474E5089:    return "PNG";
	case 0x38464947:    return "GIF";
	case 0x30314341:    return "DWG";
	case 0xA3DF451A:    return "MKV";
	case 0xF5ED0606:    return "INDD";
	case 0x01BC4949:    return "JPEG-XR";
	case 0x53502125:    return "PS";
	case 0x46464952:
	    if(buffer[8]=='C' && buffer[9]=='D' && buffer[10]=='R') return "CDR";
	    if(buffer[8]=='W' && buffer[9]=='A' && buffer[10]=='V') return "WAV";
	    if(buffer[8]=='A' && buffer[9]=='V' && buffer[10]=='I') return "AVI";
	    if(buffer[8]=='W' && buffer[9]=='E' && buffer[10]=='B') return "WEBP";
	    return "RIFF";
    }
    if(buffer[0]=='M' && buffer[1]=='Z' && (buffer[2]+256*buffer[3])<512) return "EXE";
    return NULL;
}

char* detect(unsigned char* buffer){
    unsigned int magic=*((unsigned int*)buffer);
    switch(magic){
	case 0x04034B50:
	    if(memmem(buffer,BLKSIZE,"vnd.makemusic.notation",22)) return "MUSX";
	    if(memmem(buffer,BLKSIZE,"NotationMetadata.xml",20)) return "MUSX";
	    if(memmem(buffer,BLKSIZE,"[Content_Types].xml",18)){
		if(memmem(buffer,BLKSIZE,"document.xml",12)) return "DOCX";
		if(memmem(buffer,BLKSIZE,"workbook.xml",12)) return "XLSX";
		if(memmem(buffer,BLKSIZE,"presentation",12)) return "PPTX";
		if(memmem(buffer,BLKSIZE,"word/",5)) return "DOCX";
		if(memmem(buffer,BLKSIZE,"xl/_rels",8)) return "XLSX";
		if(memmem(buffer,BLKSIZE,"ppt/",4)) return "PPTX";
		return "DOCX/XLSX/PPTX";
	    }
	    return "ZIP";
	case 0xE0FFD8FF:
	case 0xE1FFD8FF:
	case 0xE2FFD8FF:
	case 0xEDFFD8FF:
	case 0xFEFFD8FF:
	    return "JPG";
	case 0x2A004D4D:
	case 0x002A4949:
	    return "TIFF";
        case 0x46465848:    return "VDB"; // HXFF ???
        case 0x66676572:    return "REG"; // regf  (win registry)
        case 0x2E736E64:    return "AU";  // .snd
        case 0x4B504653:    return "SFK"; // SFPK
        case 0x6D783F3C:    return "XML";
        case 0x44445A53:    return "??_"; // Microsoft compressed file in Quantum format
        case 0x4A41574B:    return "??_"; // Microsoft compressed file in Quantum format
	case 0x6E6F5A5B:    return "ZoneTransfer"; // WTF?????
	case 0x47494E45:   
	    if(!memcmp(buffer,"ENIGMA BINARY FILE",18)) return "MUS"; // Finale music file
	    return "MUS???";
	case 0x39545043:    return "CPT"; // wtf?
	case 0x33444741:    return "FH8"; // wtf?
	case 0x454C4946:    return "$MFT";
	case 0xE011CFD0:    return "OLE";
	case 0x74725C7B:    return "RTF";
	case 0x21726152:    return "RAR";
//	case 0x002CED52:    return "ACE";
	case 0xAFBC7A37:    return "7z";
	case 0x46445025:    return "PDF";
	case 0x53504238:    return "PSD";
	case 0x474E5089:    return "PNG";
	case 0x38464947:    return "GIF";
	case 0x30314341:    return "DWG";
	case 0x0D302020:    return "DXF";
	case 0xA3DF451A:    return "MKV";
	case 0x5367674F:    return "OGG";
	case 0x43614C66:    return "FLAC";
	case 0x75B22630:    return "WMV";
	case 0x9AC6CDD7:    return "WMF";
	case 0x6468544D:    return "MID";
	case 0xF5ED0606:    return "INDD";
	case 0x01BC4949:    return "JPEG-XR";
	case 0x53502125:    return "PS";
	case 0x6E696150:    return "PSP";
	case 0x4353414A:    return "JBF";
	case 0xFE12ADCF:    return "DBX";
	case 0x950412DE:    return "MO";
	case 0xC6D3D0C5:    return "EPS"; // ?
	case 0x696B541A:    return "DMX";
	case 0x54265441:    return "DjVu";
	case 0x6D74683C:    return "html";
	case 0x4D54483C:    return "HTML";
	case 0x3CBFBBEF:    return "HTML.BOM";
	case 0x4F44213C:    return "XHTML";  // doctype
	case 0x6F64213C:    return "xhtml";  // doctype
	case 0x20726176:    return "JS.var"; // var x
	case 0x002DA5DB:    return "DOC?";
	case 0x613A3864:    return "torrent";
	case 0x4C54414D:    return "Matlab";
	case 0x694C5153:    return "SQlite";
	case 0x4643534D:    return "CAB";
	case 0x54584523:    return "M3U";
	case 0x56AB9C78:    return "MP3";  // ??
//	case 0x00000100:    return "TTF?"; // !!!!!!
	case 0x46464952:
	    if(buffer[8]=='C' && buffer[9]=='D' && buffer[10]=='R') return "CDR";
	    if(buffer[8]=='W' && buffer[9]=='A' && buffer[10]=='V') return "WAV";
	    if(buffer[8]=='A' && buffer[9]=='V' && buffer[10]=='I') return "AVI";
	    if(buffer[8]=='W' && buffer[9]=='E' && buffer[10]=='B') return "WEBP";
	    return "RIFF";
    }
    if(buffer[0]=='M' && buffer[1]=='Z' && (buffer[2]+256*buffer[3])<512) return "EXE";
    if(buffer[0]=='F' && buffer[1]=='L' && buffer[2]=='V') return "FLV";
    if(buffer[0]=='C' && buffer[1]=='W' && buffer[2]=='S') return "SWF.comp";
    if(buffer[0]=='F' && buffer[1]=='W' && buffer[2]=='S') return "SWF";
    if(buffer[0]=='I' && buffer[1]=='D' && buffer[2]=='3') return "MP3.ID3";
    if(buffer[4]=='f' && buffer[5]=='t' && buffer[6]=='y' && buffer[7]=='p') return "MP4";
    if(buffer[0]=='B' && buffer[1]=='M') return "BMP?";
//    if(buffer[0]==0xFF && buffer[1]>=0xF0) return "MP3.raw";
    if(!memcmp(buffer+4,"Standard",8)) return "MDB"; // MS Access
    if(!memcmp(buffer+7,"**ACE**",7)) return "ACE";
//    if(magic) printf("Unknown magic 0x%08X\n",magic);
    return NULL;
}




unsigned char buffer[BLKSIZE];

static char mft_name[]={0x24,0,0x4D,0,0x46,0,0x54,0};

int main(){

//printf("SIZEOF  short=%d  int=%d  long=%d  longlong=%d\n",sizeof(short),sizeof(int),sizeof(long),sizeof(long long));

//A_mbr_ntfs5P.img  B_ntfs2.img  C_ntfs1.img  D_ntfs3.img  E_mbr_ntfs4.img

FILE* f=fopen("/dev/sda","rb");
//FILE* f=fopen("/home/sda_orig.img","rb");

//fseek(f,0x186A000000LL,0);
//fseek(f,0x3FFC43000LL,0);
//fseek(f,0xD8015000,0);
while(fread(buffer,BLKSIZE,1,f)>0){
    long long p=ftell(f)-BLKSIZE;
//    int cl=(p-0x100000)/1024;
    int cl=(p-part_start)/blksize;
    unsigned int magic=*((unsigned int*)buffer);
//    printf("magic=0x%X\n",magic);

    int i;
    for(i=0;i<BLKSIZE;i+=512)
      if(buffer[i+510]==0x55 && buffer[i+511]==0xAA){
        if(buffer[i+3]==0x4E && buffer[i+4]==0x54 && buffer[i+5]==0x46 && buffer[i+6]==0x53){
            unsigned int ss=buffer[i+11]+256*buffer[i+12];
            unsigned long long s=*((unsigned long long*)(buffer+i+0x28));
            unsigned long long mft=*((unsigned long long*)(buffer+i+0x30));
            printf("NTFS boot sector found! fpos=0x%llX  bytes/sect=%d  sect/cluster=%d  size=%lld GB (%lld sectors)  mft=%lld (0x%llX)\n",p+i,ss,buffer[i+13], (s*ss)>>30, s, mft, p+i+mft*ss*buffer[i+13] );
            part_start=p;
        } else
            printf("MBR boot sector found?  fpos=0x%llX  @DA=%02X%02X  drive=0x%X  magic=%08X\n",p+i, buffer[i+0xDA],buffer[i+0xDB], buffer[i+0xDC], magic);
      }

    if(magic==0x58444E49){ // INDX
	unsigned long long vcn=*((unsigned long long*)(buffer+16));
//	printf("cluster %d / 0x%X000 : Index!  VCN=%lld\n",cl,(int)(p>>12),vcn);
	printf("cluster %d / 0x%llX : Index #%lld\n",cl,p,vcn);
	//if(debug) 
	parseindx(buffer); 
    } else
    if(magic==0x454C4946){ // FILE
        unsigned int offs=*((unsigned int*)(buffer+0x18));
        unsigned int size=*((unsigned int*)(buffer+0x1C));
	if(offs<BLKSIZE && size<=BLKSIZE && size>=512 && offs<size){
//	    if(memmem(buffer,BLKSIZE,mft_name,sizeof(mft_name))) savemft(buffer,p);
            for(i=0;i<BLKSIZE;i+=size) parsefile(buffer+i,p+i); // handle 4x 1024-byte MFT blocks in 4096 cluster...
	}
        else printf("_FILE offs=%d  size=%d\n",offs,size);
    } else {
//	printf("\nmagic: 0x%08X ",magic);
	char* type=detect(buffer);
	if(type) printf("cluster %d / 0x%llX : %s\n",cl,p,type);
    }
    if(!(p&0xffffff)){ fflush(stdout); fprintf(stderr,"%llX   %5.3f GB\r",p,p/(1024.0*1024*1024));fflush(stderr);}
//    break;
}

}
