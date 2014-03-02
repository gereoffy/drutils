#include <stdio.h>
#include <stdlib.h>
#include <string.h>


int main(int argc,char* argv[]){
if(argc<2) return -1;
FILE* f=fopen(argv[1],"rb");
if(!f){
    printf("cannot open file\n");
    return 1;
}

int last_soi=-1;
int last_sos=-1;
int last_eoi=0;
int last_dct=-1;
int huffstart=-1;
int kepstart=-1;
int javitani=0;

int c1=fgetc(f);
int c2=fgetc(f);
if(c1!=0xFF || c2!=0xD8){
    printf("invalid JPG format!\n");
    fseek(f,512,0);
    javitani=1;
} else last_soi=0;

int c;
while((c=fgetc(f))>=0){
    if(c==0xFF){
ujra:	c=fgetc(f); if(c<0) break;
	if(c==0xFF) goto ujra;
	if(c>=0xC0){
	    char* marker="???";
	    if(c==0xD8) marker="Start Of Image"; else
	    if(c==0xC0) marker="Start Of Frame (Baseline DCT)"; else
	    if(c==0xC2) marker="Start Of Frame (Progressive DCT)"; else
	    if(c==0xC4) marker="Define Huffman Table(s)"; else
	    if(c==0xDB) marker="Define Quantization Table(s)"; else
	    if(c==0xDD) marker="Define Restart Interval"; else
	    if(c==0xDA) marker="Start Of Scan"; else
	    if(c>=0xD0 && c<=0xD7) marker="Restart #"; else
	    if(c==0xE0) marker="APP0 - JFIF segment"; else
	    if(c==0xE1) marker="APP1 - EXIF segment"; else
	    if(c>=0xE0 && c<=0xEF) marker="Application-specific #"; else
	    if(c==0xFE) marker="Contains a text comment."; else
	    if(c==0xD9) marker="End Of Image";
	    printf("%08X marker: %02X (%s)\n",(unsigned int)ftell(f)-2,c,marker);
	    
	    if(huffstart<0)
		if(c==0xC0 || c==0xC2 || c==0xC4 || c==0xDA || c==0xDB || c==0xDD || c==0xFE || (c>=0xE0 && c<=0xE1) ){
		    huffstart=ftell(f)-2;
		}
	    if(c==0xD9){ last_eoi=ftell(f); huffstart=-1; last_dct=-1; }
	    if(c==0xD8) last_soi=ftell(f)-2;
	    if(c==0xC0 || c==0xC2 || c==0xC4 || c==0xDB) last_dct=ftell(f)-2;
	    if(c==0xDA){
		last_sos=ftell(f)-2;
		if(last_dct>=huffstart)	kepstart=huffstart;
	    }

	    if(c==0xE0){
		// JFIF
		int len=fgetc(f);len=(len*256)+fgetc(f);
		char id[6];
		fread(id,5,1,f); id[5]=0;
		printf("  JFIF extension: len=%d id=%s\n",len,id);
		int ver=fgetc(f);ver=(ver*256)+fgetc(f);
	    } else
	    if(c==0xE1){
		// EXIF
		int len=fgetc(f);len=(len*256)+fgetc(f);
		char id[6];
		fread(id,4,1,f); id[4]=0;
		printf("  EXIF extension: len=%d (0x%X) id=%s\n",len,len,id);
//		int ver=fgetc(f);ver=(ver*256)+fgetc(f);
	    }
	}
    }
}

printf("picture start: 0x%X   lasts: SOI=0x%X SOS=0x%X EOI=0x%X\n",
    kepstart,last_soi,last_sos,last_eoi);

if(!javitani) return 0;

if(kepstart<0){
    printf("NEM JAVITHATO: '%s'\n",argv[1]);
    return 5;
}

char* nev=malloc(strlen(argv[1])+100);
sprintf(nev,"%s.HIBAS",argv[1]);
if(rename(argv[1],nev)!=0){
    printf("cannot rename bad file!\n");
    return 1;
}

FILE* f2=fopen(argv[1],"rb");
if(f2){
    printf("cannot rename bad file! WTF?\n");
    return 1;
}
f2=fopen(argv[1],"wb");
if(!f2){
    printf("cannot write file\n");
    return 1;
}

fseek(f,kepstart,0);
#define BUFFER 8192
unsigned char buffer[BUFFER];
if(last_soi<kepstart){
    // write SOI
    fputc(0xFF,f2);
    fputc(0xD8,f2);
}
  while(1){
    int len=last_eoi-ftell(f);
    if(len<=0) break;
    if(len>BUFFER) len=BUFFER;
    if(fread(buffer,len,1,f)<0) break;
    fwrite(buffer,len,1,f2);
  }
  fclose(f2);

  printf("JAVITVA: '%s'\n",argv[1]);

fclose(f);
return 0;
}
