/* A linked C674x program copies executable bytes into RAM, then runs that copy. */
    .section .text,"ax",@progbits
    .balign 32
    .global _start, payload, replacement, benchmark, protected_payload
_start:
    mvkl .S1 payload, a0
    mvkh .S1 payload, a0
    mvkl .S2 0xC2100000, b0
    mvkh .S2 0xC2100000, b0
    mvk .S2 8, b1
copy:
    ldw .D1T1 *a0++[1], a1
    nop 4
    stw .D2T1 a1, *b0++[1]
    sub .L2 b1, 1, b1
    [b1] b .S2 copy
    nop 5
    mvkl .S2 0xC2100000, b0
    mvkh .S2 0xC2100000, b0
    b .S2 b0
    nop 5
    .balign 32
payload:
    mvk .S1 42, a4
    b .S2 b3
    nop 5
    .balign 32
replacement:
    mvk .S1 99, a4
    b .S2 b3
    nop 5
    .balign 32
benchmark:
    add .L1 1, a4, a4
    b .S2 benchmark
    nop 5
    .balign 32
protected_payload:
    ldw .D1T1 *a0, a1
    mv .L1 a1, a4
    b .S2 b3
    nop 5
    .balign 32
