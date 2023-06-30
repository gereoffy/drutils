#include <stdio.h>
#include <stdlib.h>

#define BLKSIZE 4096
unsigned char buff[BLKSIZE];
unsigned long long pos=0;
char* ize="0123456789ABCDEF@abcdefghijklmnopqrstuvwxyz";

int main(int argc,char* argv[]){

FILE* f=fopen(argv[1],"rb");
while(1){
    int len=fread(buff,BLKSIZE,1,f);
    if(len<=0) break;
    int i;
    int n0=0;
    int n255=0;
    unsigned char x=0;
    if((pos&0x7FFFF)==0) printf("\n%12llX: ",pos);
    for(i=0;i<BLKSIZE;i++){
	unsigned char c=buff[i];
	if(c==0) ++n0; else
	if(c==255) ++n255; else
	x=x^c;
    }
    if(n0==i) putchar('.'); else
    if(n255==i) putchar('*'); else
    putchar(ize[x&31]);
    pos+=BLKSIZE;
    if(pos>0x80000000LL) break;
}

}

