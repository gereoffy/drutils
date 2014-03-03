#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WINDOWS_TICK 10000000
#define SEC_TO_UNIX_EPOCH 11644473600LL
time_t convtime(long long *tp){
    long long t=*tp;
    t=t/WINDOWS_TICK;
    t=t-SEC_TO_UNIX_EPOCH;
    return (unsigned int) t;
}

inline long long gettime(long long *tp){
    return *tp;
}

int main(int argc,char* argv[]){
int javitanikell=0;

FILE* f=fopen(argv[1],"r+b");
if(!f){
    printf("cannot open: %s\n",argv[1]);
    return 2;
}

//fseek(f,0,0);
unsigned char hdr[512];
fread(hdr,512,1,f);//fseek(f,0x1E,0);

//00000000 7B 5C 72 74 ? 66 31 5C 61 ? 6E 73 69 5C ? 61 6E 73 69  {\rtf1\ansi\ansi  
if(hdr[0]==0x7B && hdr[1]==0x5C && hdr[2]==0x72) return 1; // RTF!!!
if(hdr[0]!=0xd0 || hdr[7]!=0xe1) javitanikell=1; //return 1;  // TESTING ONLY

fseek(f,0,2);
int fs=ftell(f);

printf("=====================================================================\n");
printf("Analyzing '%s' size=%d\n",argv[1],fs);
printf("=====================================================================\n");


unsigned char rootentry[]={0x52,0,0x6F,0,0x6F,0,0x74,0,0x20,0,0x45,0,0x6E,0,0x74,0,0x72,0,0x79,0};
unsigned char docsumm[]=  {0x05,0,0x44,0,0x6F,0,0x63,0,0x75,0,0x6D,0,0x65,0,0x6E,0};

unsigned char rootentry2[]={0x52,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       2,0,5,0, 0xFF,0xFF,0xFF,0xFF, 0xFF,0xFF,0xFF,0xFF};

unsigned char rootentry3[]={0,0x52,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0,
			       2,0,5,0, 0xFF,0xFF,0xFF,0xFF, 0xFF,0xFF,0xFF,0xFF};

//00000400 00 52 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  .R..............  
//00000410 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  ................  
//00000420 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  ................  
//00000430 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  ................  
//00000440 02 00 05 00 ? FF FF FF FF ? FF FF FF FF ? 02 00 00 00  ....ÿÿÿÿÿÿÿÿ....  


//00000400 52 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  R...............  
//00000410 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  ................  
//00000420 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  ................  
//00000430 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00  ................  
//00000440 02 00 05 00 ? FF FF FF FF ? FF FF FF FF ? 02 00 00 00  ....ÿÿÿÿÿÿÿÿ....  
//00000450 20 08 02 00 ? 00 00 00 00 ? C0 00 00 00 ? 00 00 00 46   .......À......F  
//00000460 00 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 0B 7D 31 72  .............}1r  
//00000470 95 95 CE 01 ? 3F 00 00 00 ? 80 08 00 00 ? 00 00 00 00  ..Î.?...........  


unsigned int fat[1+512/4];

int fatsize=1+(fs>>9);
if(fatsize<=512) fatsize=514; // minifat miatt!!!
unsigned char* fattable=malloc(fatsize+128);

int fatmax=-1;
int fatmax2=-1;

int fatpos[fatsize+128];
memset(fatpos,0xFF,fatsize*4);

unsigned char* secttype=malloc(fatsize+128);
memset(secttype,0,fatsize+128);

#define SECT_ROOT 1
#define SECT_FAT 2
#define SECT_MARKEDFAT 4
#define SECT_MARKEDDIFAT 8
#define SECT_MARKEDDATA 16
#define SECT_MARKEDEND 32
#define SECT_OLD 64
#define SECT_MARKEDFREE 128

unsigned char ujhdr[512]={0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, //signature
			  0,0,0,0,  0,0,0,0, 0,0,0,0,  0,0,0,0,           //CLSID=0
			  0x3E,0, 0x03,0, 0xFE,0xFF,    // version, byteorder
			  9,0,  6,0,      // sector sizes
			  0,0,0,0,0,0,   // reserved
			  0,0,0,0,	 // csectDir
			  2,0,0,0,       // p[0] FAT length!!!
			  0xA3,0,0,0,    // p[1] RootDir start!!!
			  0,0,0,0,       // p[2] signature = 0
			  0,0x10,0,0,    // p[3] ulMiniSectorCutoff=4096
			  0x94,0,0,0,    // p[4] MiniFat Start!!!
			  1,0,0,0,       // p[5] csectMiniFat number of SECTs in the MiniFAT chain
			  0xFE,0xFF,0xFF,0xFF, // first SECT in the DIFAT chain
			  0,0,0,0,       // number of SECTs in the DIFAT chain
			  0xFF,0xFF,0xFF,0xFF,  // FAT table
			  };
int* fatlist=ujhdr+0x4C;
int* ujhdrp=ujhdr+0x2C; // params! 
memset(fatlist,0xff,4*109); // del fat table
int fatlistlen=0;
int minifat=-2;

if(argc>2) minifat=atoi(argv[2]);
if(argc>3){
    // FAT lista megadva parancssorban!
    // secttype felulirasa!!!
    char* p=argv[3];
    while(p && *p){
	char* q=strchr(p,',');
	if(q){ *q=0; q++; }
	fatlist[fatlistlen]=atoi(p);
	printf("defined FAT@%d = %d\n",fatlistlen,fatlist[fatlistlen]);
	++fatlistlen;
	p=q;
    }
    javitanikell=1;
//    for(i=2;i<argc;i++) fatlist[fatlistlen++]=atoi(argv[i]);
}


int i=0;
fseek(f,512,0);
while(1){
//    if(fread(hdr,20,1,f)<=0) break;
    if(fread(fat,512,1,f)<=0) break;
    if((memcmp(rootentry,fat,20)==0) || (memcmp(rootentry2,fat,0x4C)==0) || (memcmp(rootentry3,fat,0x4C)==0) ){
	secttype[i]|=SECT_ROOT;
	printf("RootEntry @ %d  created: %08X %08X modify: %08X %08X\n",i,fat[0x64/4],fat[0x64/4+1],fat[0x64/4+2],fat[0x64/4+3]);
	time_t t1=convtime(&fat[0x64/4]);
	time_t t2=convtime(&fat[0x64/4+2]);
//	printf("  unix times: %d %d\n",t1,t2);
	printf("  create: %s",ctime(&t1));
	printf("  modify: %s",ctime(&t2));
	printf("  start sector: %d   size: %d\n",fat[0x74/4],fat[0x78/4]);
    }
    if(memcmp(docsumm,fat,16)==0) printf("DocumentSymmary @ %d\n",i);
    
    int j;

  if(fatlistlen>0){
	// van fat-listank!!!!!!! hasznaljuk.
	for(j=0;j<fatlistlen;j++)
	    if(i==fatlist[j]){
		// megvan!
		printf("FAT Entry @ %d\n",i);
		fatpos[i]=j;
		secttype[i]|=SECT_FAT;
		j*=128;
		{	printf("  fat sectors included: ");
			int k;
			for(k=0;k<128;k++){
			    if(fat[k]==0xFFFFFFFD) printf("%d,",j+k);
			    if(fat[k]==0xFFFFFFFC) secttype[j+k]|=SECT_MARKEDDIFAT;
			    if(fat[k]==0xFFFFFFFD) secttype[j+k]|=SECT_MARKEDFAT;
			    if(fat[k]==0xFFFFFFFF) secttype[j+k]|=SECT_MARKEDFREE;
			    if(fat[k]==0xFFFFFFFE) secttype[j+k]|=SECT_MARKEDDATA|SECT_MARKEDEND;
			    if(fat[k]<=fatsize){
				secttype[j+k]|=SECT_MARKEDDATA;
//				printf("  data @ %d\n",j+k);
			    }
			}
			printf("\n");
//			break;
		}
		break;
	    }
  } else {
    // no fat list -> try to detect!
    
    int ff=0;
    for(j=0;j<128;j++){
	if(fat[j]<0xFFFFFFFD)
	  if(fat[j]>=fatsize) break;
//	  if(!fat[j] || fat[j]>=fatsize) break;
    }
//maybe FAT @ 46 (120) 130
//maybe FAT @ 117 (128) -1208797620
//    printf("maybe FAT @ %d (%d) %d\n",i,j,fat[j]);
    if(j==128){
	// maybe FAT sector... verify deeper
	memset(fattable,0,fatsize);
	int fat00=0;
	int fatXX=0;
	int fatFC=0;
	int fatFD=0;
	int fatFE=0;
	int fatFF=0;
	for(j=0;j<128;j++){
//	    printf("  j=%d  %d\n",j,fat[j]);
	    if(fat[j]<0xFFFFFFFC){
//		if(!fat[j] || fat[j]>=fatsize) break;
		if(fat[j]>=fatsize) break;
		if((++fattable[fat[j]])!=1) break;
		if(!fat[j]){
		    if(fat00) break; // tobb mint egy db nulla
		    ++fat00;
		}
		++fatXX;
	    } else
	    if(fat[j]==0xFFFFFFFC) ++fatFC; else
	    if(fat[j]==0xFFFFFFFD) ++fatFD; else
	    if(fat[j]==0xFFFFFFFE) ++fatFE; else
	    if(fat[j]==0xFFFFFFFF) ++fatFF;
	}
	if(j==128 && fatFF<128){
	    printf("FAT Entry @ %d  %d/%d end=%d fat=%d di=%d  (%d,%d,%d,%d,%d,%d,%d,%d...%d,%d)\n",
		i, fatXX,fatFF,  fatFE, fatFD, fatFC,
		fat[0],fat[1],fat[2],fat[3],fat[4],fat[5],fat[6],fat[7], fat[126],fat[127]);
	    memset(fattable,0,fatsize);
	    fatmax2=0;
	    for(j=0;j<128;j++){
		int c=fat[j]-j-1;
		if(c>=0 && c<fatsize) fattable[c]++;
		if((j&7)==0) putchar(' ');
		if((j&15)==0) putchar(' ');
		if(fat[j]==0xFFFFFFFF) putchar('.'); else
		if(fat[j]==0xFFFFFFFE) putchar('e'); else
		if(fat[j]==0xFFFFFFFD) putchar('F'); else
		if(fat[j]==0xFFFFFFFC) putchar('D'); else
		putchar('*');
		if((j&63)==63) printf("\n");
		if(fat[j]!=0xFFFFFFFF) fatmax2=j;
	    }
	    secttype[i]|=SECT_FAT;
//FAT Entry @ 129  4/121 end=1 fat=2 di=0  (-3,-3,131,-2,133...-1,-1)
//
	    int jmax=0;
	    for(j=1;j<fatsize;j++) if(fattable[j]>fattable[jmax]) jmax=j;
	    printf("  best diff match: %dx %d\n",fattable[jmax],jmax);
	    if( ((jmax&127)==0) && fattable[jmax]>=fatXX/2 && fattable[jmax]>1){
		    j=jmax;
		    printf("  fat entry for sectors %d .. %d\n",j,j+127);
		    fatmax=j+128;
		    //if((j&127)==0) 
		    fatpos[i]=j/128;
		    //if(fatFD>0)
		    {	printf("  fat sectors included: ");
			int k;
			for(k=0;k<128;k++){
			    if(fat[k]==0xFFFFFFFD) printf("%d,",j+k);
			    if(fat[k]==0xFFFFFFFC) secttype[j+k]|=SECT_MARKEDDIFAT;
			    if(fat[k]==0xFFFFFFFD) secttype[j+k]|=SECT_MARKEDFAT;
			    if(fat[k]==0xFFFFFFFF) secttype[j+k]|=SECT_MARKEDFREE;
			    if(fat[k]==0xFFFFFFFE) secttype[j+k]|=SECT_MARKEDDATA|SECT_MARKEDEND;
			    if(fat[k]<=fatsize){
				secttype[j+k]|=SECT_MARKEDDATA;
//				printf("  data @ %d\n",j+k);
			    }
			}
			printf("\n");
//			break;
		    }
	    } else

//FAT Entry @ 129  1/122 end=3 fat=2 di=0  (-3,-3,131,-2,-2,-2,-1,-1...-1,-1)
// FF*eee.. ........  ........ ........  ........ ........  ........ ........

	    //
//	    if(fatpos[i]<0 && fatXX==0 && i>=fatmax && i<fatmax+128 && fat[i-fatmax]==0xFFFFFFFD){
	    if(fatpos[i]<0 && i>=fatmax && i<fatmax+128 && fat[i-fatmax]==0xFFFFFFFD){
		int fs2=((fs-512)+511)/512;
		printf("  MAYBE fat entry for sectors %d .. %d\n",fatmax,fatmax+127);
		printf("   file is %d sectors, fatmax2=%d\n",fs2,fatmax+fatmax2);
		if(fs2>=fatmax && fs2<fatmax+130)
		    {	int j=fatmax;
			fatpos[i]=j/128;
			printf("  fat sectors included: ");
			int k;
			for(k=0;k<128;k++){
			    if(fat[k]==0xFFFFFFFD) printf("%d,",j+k);
			    if(fat[k]==0xFFFFFFFC) secttype[j+k]|=SECT_MARKEDDIFAT;
			    if(fat[k]==0xFFFFFFFD) secttype[j+k]|=SECT_MARKEDFAT;
			    if(fat[k]==0xFFFFFFFF) secttype[j+k]|=SECT_MARKEDFREE;
			    if(fat[k]==0xFFFFFFFE) secttype[j+k]|=SECT_MARKEDDATA|SECT_MARKEDEND;
			    if(fat[k]<=fatsize){
				secttype[j+k]|=SECT_MARKEDDATA;
//				printf("  data @ %d\n",j+k);
			    }
			}
			printf("\n");
//			break;
		    }
	    }
	    
	}
//	else printf("maybe FAT @ %d (%d) %d\n",i,j,fat[j]);

    }

  }    
  ++i;
}

printf("=====================================================================\n");
printf("                          Starting recovery...\n");
printf("=====================================================================\n");

//00000000 D0 CF 11 E0 ? A1 B1 1A E1 ? 00 00 00 00 ? 00 00 00 00  ÐÏ.à¡±.á........  
//00000010 00 00 00 00 ? 00 00 00 00 ? 3E 00 03 00 ? FE FF 09 00  ........>...þÿ..  
//00000020 06 00 00 00 ? 00 00 00 00 ? 00 00 00 00 ? 02 00 00 00  ................  
//00000030 A3 00 00 00 ? 00 00 00 00 ? 00 10 00 00 ? 94 00 00 00  £...............  
//00000040 01 00 00 00 ? FE FF FF FF ? 00 00 00 00 ? A5 00 00 00  ....þÿÿÿ....¥...  
//00000050 A4 00 00 00 ? FF FF FF FF ? FF FF FF FF ? FF FF FF FF  ¤...ÿÿÿÿÿÿÿÿÿÿÿÿ  



int rootdir=-2;
int rootdirstart=-2;
long long rootdirtime=0;
int minifatsize=0;

int prob_sokfat=0;
int prob_sokmini=0;

// find rootdir
for(i=0;i<fatsize;i++){
    unsigned char t=secttype[i];
    if(t&15){
	if( (t&SECT_ROOT) ){
	    if(t&SECT_MARKEDDATA){
		fseek(f,512*(i+1),0);
		if(fread(fat,512,1,f)<=0) break;
//		time_t t1=convtime(&fat[0x64/4]);
		time_t t2=convtime(&fat[0x64/4+2]);
		long long tl=gettime(&fat[0x64/4+2]);
		printf("RootDir sector:%4d  modify:%s",i,ctime(&t2));
		printf("  start sector:%4d  size: %d\n",fat[0x74/4],fat[0x78/4]);
		if(rootdir<0 || tl>=rootdirtime){
		    rootdir=i; rootdirtime=tl;
		    rootdirstart=fat[0x74/4];
		}
	    }
	}
    }
}


for(i=0;i<fatsize;i++){
    unsigned char t=secttype[i];
    if(t&15){
	printf("sector %3d: 0x%02X  ",i,t);
	if( (t&SECT_ROOT) ){
	    if(t&SECT_MARKEDDATA){
		if(i==rootdir)
		    printf("RootDir");
		else
		    printf("old RootDir");
	    } else
		printf("deleted RootDir");
	} else
	if( (t&(SECT_FAT|SECT_MARKEDFAT|SECT_MARKEDDATA)) == (SECT_FAT|SECT_MARKEDDATA) ){
	    printf("MiniFAT @ %d",fatpos[i]);
//	    if(fatpos[i]==0) minifat=i;
	} else
	if( (t&(SECT_FAT|SECT_MARKEDFAT)) == (SECT_FAT|SECT_MARKEDFAT) ){
	    fseek(f,512*(i+1),0);
	    if(fread(fat,512,1,f)<=0) break;
	    int k;
	    k=128*fatpos[i];
	    int old=0;
	    if(rootdir>=k && rootdir<k+128)
		if(fat[rootdir-k]!=0xFFFFFFFE && fat[rootdir-k]>fatsize) old++;
//	    if(rootdirstart>=k && rootdirstart<k+128)
//		if(fat[rootdirstart-k]!=0xFFFFFFFE && fat[rootdirstart-k]>fatsize) old++;
	    printf("%sFAT @ %d   includes: ",old?"old ":"",fatpos[i]);
	    if(old) secttype[i]|=SECT_OLD;
	    for(k=0;k<128;k++){
	        if(fat[k]==0xFFFFFFFD)
	    	    printf("%d,",128*fatpos[i]+k); else
	    	if((secttype[128*fatpos[i]+k]&(SECT_FAT|SECT_MARKEDFAT|SECT_MARKEDDATA)) == (SECT_FAT|SECT_MARKEDDATA)){
	    	    printf("(%d),",128*fatpos[i]+k);
	    	}
	    	if((fat[k]>=0 && fat[k]<fatsize) || fat[k]==0xFFFFFFFE){
	    	    if(rootdir==128*fatpos[i]+k)  printf("Root,");
	    	    if(rootdirstart==128*fatpos[i]+k) printf("Stream,");
	    	}
	    }
	    if(fatlist[fatpos[i]]<0 || !old){
		if(fatlist[fatpos[i]]>=0)
		    if(!(secttype[fatlist[fatpos[i]]]&SECT_OLD)) ++prob_sokfat;
		fatlist[fatpos[i]]=i;
		if(fatpos[i]+1>fatlistlen) fatlistlen=fatpos[i]+1;
	    }
	} else
	    printf("???");
	printf("\n");
    }
}

if(minifat>=0){
    // minifat given
    printf("MiniFAT sector defined: %d\n",minifat);
    int i=minifat;
    while(i>=0 && i<fatsize && minifatsize<32){
	    // verify in FAT
	    int j=fatlist[i/128];
	    if(j>=0 && j<fatsize){
		fseek(f,512*(j+1),0);
		if(fread(fat,512,1,f)<=0) break;
		if(fat[i&127]==0xFFFFFFFE || fat[i&127]<fatsize){
		    printf("MiniFAT @ %d   sector: %d  (next: %d)\n",minifatsize,i,fat[i&127]);
		    i=fat[i&127];++minifatsize;continue;
		}
	    }
	    break;
    }
} else
  for(i=0;i<fatsize;i++){
    // find minifat
    unsigned char t=secttype[i];
    if(t&15){
	if( (t&(SECT_FAT|SECT_MARKEDFAT|SECT_MARKEDDATA)) == (SECT_FAT|SECT_MARKEDDATA) ){
	    // verify in FAT
	    int j=fatlist[i/128];
	    if(j>=0 && j<fatsize){
		fseek(f,512*(j+1),0);
		if(fread(fat,512,1,f)<=0) break;
		if(fat[i&127]==0xFFFFFFFE || fat[i&127]<fatsize){
		    printf("MiniFAT @ %d   sector: %d  (next: %d)\n",fatpos[i],i,fat[i&127]);
		    if(fatpos[i]==0 && minifat>=0) ++prob_sokmini;
		    if((fatpos[i]<=0 && minifat<0)||(fatpos[i]==0)){
			minifat=i;
			minifatsize = (fat[i&127]==0xFFFFFFFE) ? 1 : 2;
		    } else
		    if(fatpos[i]>0)
			minifatsize = fatpos[i]+1;
		}
	    }
//	    printf("MiniFAT @ %d",fatpos[i]);
//	    if(fatpos[i]==0) minifat=i;
	}
    }
}


printf("NEW hdr:  root=%d  mini=%d(%d)  FAT(%d):",rootdir,minifat,minifatsize,fatlistlen);
for(i=0;i<fatlistlen;i++) printf("%d,",fatlist[i]);
printf("\n");

int chkfat(int x){
    if(x>=i*128 && x<i*128+128){
        if(fat[x-i*128]==0xFFFFFFFE) return 1; // end
        if(fat[x-i*128]>=0 && fat[x-i*128]<fatsize) return 1;
    }
    return 0;
}


// detect possible problems
// check FAT size, content:
int fs2=((fs-512)+511)/512;
int fs3=(fs2+127)/128; // FAT sectorok szama
int prob_fat=0;
int prob_fathasroot=0;
int prob_fathasmini=0;
int prob_fathasfat=0;
int prob_fathasstream=0;
int prob_fatcount=0;
for(i=0;i<fs3;i++){
    if(fatlist[i]>=0){
	fseek(f,512*(fatlist[i]+1),0);
	if(fread(fat,512,1,f)>0){
	    prob_fathasroot+=chkfat(rootdir);
	    prob_fathasmini+=chkfat(minifat);
	    prob_fathasstream+=chkfat(rootdirstart);
	    int j;
	    for(j=0;j<fs3;j++){
		int x=fatlist[j];
		if(x>=i*128 && x<i*128+128){
//		    printf("FF(%d): %d in %d = %d\n",j,x,fatlist[i],fat[x-i*128]);
    		    if(fat[x-i*128]==0xFFFFFFFD)
			prob_fathasfat++;
		}
	    }
	    for(j=0;j<128;j++)
		if(fat[j]==0xFFFFFFFD)
		    ++prob_fatcount;
	}
    } else {
	printf("WARNING: missing FAT sector @ %d\n",i);
	++prob_fat;
    }
}

printf("PROBLEMS:");
if(rootdir<0) printf(",nincs ROOT!"); else
if(prob_fathasroot!=1) printf(",nincs ROOT a FATban");
if(rootdirstart>=0 && prob_fathasstream!=1) printf(",nincs stream a FATban");
if(prob_fathasfat!=fs3) printf(",nincs FAT a FATban (%d/%d)",prob_fathasfat,fs3); else
if(prob_fatcount!=fs3) printf(",tobb FAT a FATban! (%d/%d)",prob_fatcount,fs3);
if(prob_fat) printf(",hianyzo FAT sector (%d)",prob_fat);
if(prob_sokfat) printf(",tobb FAT verzio"); // ez csak warning
if(prob_sokmini) printf(",tobb MiniFAT verzio");
if(minifat>=0 && prob_fathasmini!=1) printf(",nincs Mini a FATban");
printf("  [%s]\n",argv[1]);
printf("  multi-fat: %d  multi-mini: %d FAT: root=%d stream=%d mini=%d fat=%d/%d/%d missing=%d\n",
    prob_sokfat,prob_sokmini, prob_fathasroot, prob_fathasstream,prob_fathasmini, prob_fathasfat, prob_fatcount,fs3, prob_fat);

ujhdrp[0]=fatlistlen;
ujhdrp[1]=rootdir;
ujhdrp[4]=minifat;
ujhdrp[5]=minifatsize; //(minifat<0)?0:( (secttype[minifat]&SECT_MARKEDEND) ? 1 : 2 );


//if(hdr[0]!=0xd0 || hdr[7]!=0xe1) return 1;
unsigned int* data=hdr+0x2C;

if(hdr[0]==0xd0 && hdr[7]==0xe1){
    printf("%d/%d FATlen:%3d root:%3d mini:%3d(%d)[%d] difat:%d(%d) FAT:",
	hdr[0x1E],hdr[0x20],
	        data[0],  data[1], data[4],data[5],data[4]-data[1], data[6],data[7]);
    for(i=0;i<data[0];i++) printf("%d,",data[8+i]);
    printf(" [%d] %s\n",fs,argv[1]);
  if(memcmp(ujhdr,hdr,512)){
    printf("HDR mismatch!!!  file:%s\n",argv[1]);
    for(i=0;i<512;i++)
	if(hdr[i]!=ujhdr[i])
	    printf("at 0x%02X:  old=0x%02X  new=0x%02X\n",i,hdr[i],ujhdr[i]);
  } else
    printf("HDR OKAY!!!!!    file:%s\n",argv[1]);
}

if(javitanikell){
    // recover file!!!
    printf("HDR rewrite!!!   file:%s\n",argv[1]);
    fseek(f,0,0);
    fwrite(ujhdr,512,1,f);
    fclose(f);
}


}
