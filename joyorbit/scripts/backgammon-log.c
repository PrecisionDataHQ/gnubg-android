/* JoyOrbit host logger, GPL-3.0-or-later. Copyright 2026 Precision Data. */
#include <stdio.h>
#include <stdarg.h>
int __android_log_print(int priority,const char *tag,const char *format,...) {
    (void)priority;
    va_list args;
    fprintf(stderr,"[%s] ",tag);
    va_start(args,format);
    vfprintf(stderr,format,args);
    va_end(args);
    fputc('\n',stderr);
    return 0;
}
