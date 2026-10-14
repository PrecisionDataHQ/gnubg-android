/* JoyOrbit separate-process transport for the GPL GNU Backgammon facade.
 * Copyright 2026 Precision Data. GPL-3.0-or-later; see ../LICENSE.
 * Rules, legal turns, AI and SGF records belong to the GNU engine.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include "gnubg_mobile.h"
#include "backgammon.h"
#include "output.h"

pthread_mutex_t gnubg_lock = PTHREAD_MUTEX_INITIALIZER;
#define PLAN_LIMIT 4096
static int plans[PLAN_LIMIT * 8];
static int raw_board[50];
static int plan_count;
static int local_mode;
static const char *save_path;
static FILE *channel;
#define printf(...) fprintf(channel,__VA_ARGS__)
#define putchar(value) fputc(value,channel)

static void integers(const int *values, int count) {
    putchar('[');
    for (int i=0;i<count;i++) printf("%s%d",i?",":"",values[i]);
    putchar(']');
}
static void string(const char *value) {
    putchar('"');
    for (const unsigned char *p=(const unsigned char *)value;*p;p++) {
        if (*p=='"'||*p=='\\') putchar('\\');
        if (*p>=32) putchar(*p);
    }
    putchar('"');
}
static void snapshot(int ok) {
    int board[50],state[13],result[2];
    char position[32],match[32];
    gnubg_mobile_get_board(raw_board);
    gnubg_mobile_get_board_human(board);
    gnubg_mobile_get_match_state(state);
    gnubg_mobile_get_game_result(result);
    gnubg_mobile_current_ids(position,sizeof position,match,sizeof match);
    plan_count=0;
    if (state[0]==GAME_PLAYING && !state[5] && state[3]>0 && state[4]>0 && (local_mode||state[1]==0))
        plan_count=gnubg_mobile_get_legal_moves(raw_board,state[3],state[4],0,plans,PLAN_LIMIT*8);
    printf("{\"ok\":%s,\"version\":1,\"local\":%s,\"board\":",ok?"true":"false",local_mode?"true":"false");
    integers(board,50);
    printf(",\"state\":");integers(state,13);
    printf(",\"result\":");integers(result,2);
    printf(",\"winner\":%d,\"can_double\":%s,\"resignation\":%d,\"position\":",gnubg_mobile_get_match_winner(),gnubg_mobile_can_double()?"true":"false",gnubg_mobile_get_resignation());
    string(position);printf(",\"match\":");string(match);
    printf(",\"plans\":[");
    for (int i=0;i<plan_count;i++) { if(i)putchar(',');integers(plans+i*8,8); }
    printf("],\"notation\":[");
    for (int i=0;i<plan_count;i++) {
        char notation[128];
        if(i)putchar(',');
        gnubg_mobile_format_move(raw_board,plans+i*8,notation,sizeof notation);
        string(notation);
    }
    printf("]}\n");fflush(channel);
}
static int persist(void) {
    char temporary[4096];
    char quoted[8192];
    if(snprintf(temporary,sizeof temporary,"%s.new",save_path)>=(int)sizeof temporary)return 0;
    size_t used=0;quoted[used++]='"';
    for(const char *p=temporary;*p;p++) {
        if(*p=='"'||*p=='\\')quoted[used++]='\\';
        quoted[used++]=*p;
    }
    quoted[used++]='"';quoted[used]=0;
    if(gnubg_mobile_save_match(quoted)!=1||access(temporary,R_OK))return 0;
    return rename(temporary,save_path)==0;
}
int main(int argc,char **argv) {
    if(argc!=3||strlen(argv[1])>4000||strlen(argv[2])>4000)return 2;
    channel=fdopen(dup(STDOUT_FILENO),"w");
    if(!channel||dup2(STDERR_FILENO,STDOUT_FILENO)<0)return 2;
    save_path=argv[2];
    outputoff();
    if(access(argv[1],R_OK)||gnubg_mobile_initialise(argv[1])!=1)return 3;
    const char *slash=strrchr(argv[1],'/');
    if(slash) {
        char met[4096];
        int length=snprintf(met,sizeof met,"%.*s/met/Kazaross-XG2.xml",(int)(slash-argv[1]),argv[1]);
        if(length>0 && length<(int)sizeof met && !access(met,R_OK))gnubg_mobile_set_met(met);
    }
    gnubg_mobile_set_engine_strength(1);
    /* Engine chatter must never enter the line-delimited JSON channel. */
    snapshot(1);
    char line[128];
    while(fgets(line,sizeof line,stdin)) {
        int a=0,b=0,ok=0;
        char extra;
        char identifier[64];
        if(!strchr(line,'\n'))return 4;
        if(!strcmp(line,"QUIT\n"))return 0;
        if(sscanf(line,"PREVIEW %d %d %c",&a,&b,&extra)==2 && a>=0 && a<plan_count && b>=0 && b<=4) {
            int partial[8],preview[50],state[13],fixed[50];
            memcpy(partial,plans+a*8,sizeof partial);
            for(int i=b*2;i<8;i++)partial[i]=-1;
            gnubg_mobile_apply_move(raw_board,partial,preview);
            gnubg_mobile_get_match_state(state);
            if(state[2]==1) {gnubg_mobile_swap_board(preview,fixed);memcpy(preview,fixed,sizeof preview);}
            printf("{\"ok\":true,\"preview\":");integers(preview,50);printf("}\n");fflush(channel);
            continue;
        }
        if(sscanf(line,"NEW %d %d %c",&a,&b,&extra)==2 && (a==0||a==1) && b>=1 && b<=15) {
            local_mode=a;
            ap[0].pt=PLAYER_HUMAN;
            ap[1].pt=a?PLAYER_HUMAN:PLAYER_GNU;
            ok=gnubg_mobile_start_match(b);
        } else if(!strcmp(line,"STATE\n"))ok=1;
        else if(sscanf(line,"STRENGTH %d %c",&a,&extra)==1 && a>=0 && a<=3) {gnubg_mobile_set_engine_strength(a);ok=1;}
        else if(!strcmp(line,"ROLL\n"))ok=gnubg_mobile_command_roll();
        else if(sscanf(line,"MOVE %d %c",&a,&extra)==1 && a>=0 && a<plan_count) {
            char notation[128];
            gnubg_mobile_format_move(raw_board,plans+a*8,notation,sizeof notation);
            ok=gnubg_mobile_command_move(notation);
        } else if(!strcmp(line,"PASS\n") && plan_count==0)ok=gnubg_mobile_command_move("");
        else if(!strcmp(line,"DOUBLE\n")&&gnubg_mobile_can_double())ok=gnubg_mobile_command_double();
        else if(!strcmp(line,"TAKE\n"))ok=gnubg_mobile_command_take();
        else if(!strcmp(line,"DROP\n"))ok=gnubg_mobile_command_drop();
        else if(!strcmp(line,"ACCEPT\n"))ok=gnubg_mobile_command_agree();
        else if(!strcmp(line,"DECLINE\n"))ok=gnubg_mobile_command_decline();
        else if(!strcmp(line,"NEXT\n"))ok=gnubg_mobile_next_game();
        else if(!strcmp(line,"UNDO\n"))ok=gnubg_mobile_command_previous(local_mode?"1":"2");
        else if(!strcmp(line,"SAVE\n"))ok=persist();
        else if(sscanf(line,"ID %63s %c",identifier,&extra)==1 && strlen(identifier)==27 && strspn(identifier,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=:")==27) {
            int code=gnubg_mobile_set_gnubg_id(identifier);
            ok=code==0||code==2;
        }
        else if(sscanf(line,"LOAD %d %c",&a,&extra)==1 && (a==0||a==1) && !access(save_path,R_OK)) {
            local_mode=a;
            char quoted[8192];size_t used=0;quoted[used++]='"';
            for(const char *p=save_path;*p;p++) {
                if(*p=='"'||*p=='\\')quoted[used++]='\\';
                quoted[used++]=*p;
            }
            quoted[used++]='"';quoted[used]=0;
            ok=gnubg_mobile_load_match(quoted);
            gnubg_mobile_command_next("1000000");
            ap[0].pt=PLAYER_HUMAN;
            ap[1].pt=a?PLAYER_HUMAN:PLAYER_GNU;
        }
        snapshot(ok);
    }
    return 0;
}
