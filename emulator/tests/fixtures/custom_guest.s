/* A minimal user-supplied program for custom.py: store a marker word, then spin. */
    .section .text,"ax",@progbits
    .global _start, main, done
_start:
    mvkl .S1 result,a4
    mvkh .S1 result,a4
    mvkl .S2 0x600df00d,b4
    mvkh .S2 0x600df00d,b4
main:
    stw .D1T2 b4,*a4
done:
    b .S1 done
    nop 5
    .section .data,"aw",@progbits
    .global result
    .balign 4
result:
    .word 0
