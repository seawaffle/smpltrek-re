/* Independent SPLOOP fixtures based on TI's documented pipeline pattern. */
    .section .text,"ax",@progbits
    .balign 32
    .balign 4096
    .space 4084
    .global crossing_loop
crossing_loop:
    mvc .S2 b4,ilc
    nop 3
    sploop 1
    add .L1 1,a4,a4
    spkernel 0,0
    b .S2 b3
    nop 5
    .global copy_loop, copy_delayed, copy_overlap, masked_fill, while_count
copy_loop:
    mvk .S2 8,b0
    mvc .S2 b0,ilc
    nop 3
    sploop 1
    ldw .D1T1 *a4++[1],a1
    nop 4
    mv .L2X a1,b1
    spkernel 6,0
    || stw .D2T2 b1,*b4++[1]
    b .S2 b3
    nop 5
    .balign 32
copy_delayed:
    mvk .S2 4,b0
    sploopd 1
    || mvc .S2 b0,ilc
    ldw .D1T1 *a4++[1],a1
    nop 4
    mv .L2X a1,b1
    spkernel 6,0
    || stw .D2T2 b1,*b4++[1]
    b .S2 b3
    nop 5
    .balign 32
copy_overlap:
    mvk .S2 8,b0
    mvc .S2 b0,ilc
    nop 3
    sploop 1
    ldw .D1T1 *a4++[1],a1
    nop 4
    mv .L2X a1,b1
    spkernel 0,0
    || stw .D2T2 b1,*b4++[1]
    b .S2 b3
    nop 5
    .balign 32
masked_fill:
    mvc .S2 b4,ilc
    mvk .S2 0,b7
    nop 2
    sploop 1
    spmask L2
    || add .L2 1,b7,b7
    || stw .D1T1 a6,*a4++[1]
    spkernel 0,0
    b .S2 b3
    nop 5
    .balign 32
while_count:
    mv .L1 a4,a0
    mvk .S2 0,b4
    [a0] sploopw 1
    [a0] sub .L1 a0,1,a0
    || add .L2 1,b4,b4
    spkernel 0,0
    b .S2 b3
    nop 5
    .balign 32
    .global nested_fir, nested_rows
/* After SPRUFE8B Example 7-11 (with its product in its own register): y[j] = sum of x[i+j] * h[i], the inner loop reloaded by SPMASKR. */
nested_fir:
    mvk .S2 8,b0
    mvc .S2 b0,ilc
    mvc .S2 b0,rilc
    mv .L2 b4,b5
    mvk .S2 3,b0
    nop 1
    [b0] sploop 2
    || mvk .S1 14,a5
    || mvk .L1 0,a7
    ldh .D1T1 *a4++[1],a2
    || ldh .D2T2 *b4++[1],b2
    nop 4
    mpy .M1X a2,b2,a3
    nop 1
    spkernel 0,0
    || add .L1 a3,a7,a7
nested_fir_outer:
    sub .L1 a4,a5,a4
    || mv .L2 b5,b4
    spmaskr
    [b0] bnop .S1 nested_fir_outer,4
    || [b0] sub .L2 b0,1,b0
    sth .D1T1 a7,*a6++[1]
    || mvk .S1 0,a7
    b .S2 b3
    nop 5
    .balign 32
/* Three rows of six words, dst = src + row: SPLOOPD first, the outer branch issued before the
   SPMASKR, and a masked instruction that must run once only. */
nested_rows:
    mvk .S2 6,b0
    mvc .S2 b0,rilc
    mvk .S2 2,b2
    mvk .S1 0,a7
    mvk .S2 4,b0
    mvk .L2 0,b7
    [b2] sploopd 3
    || mvc .S2 b0,ilc
    ldw .D1T1 *a4++[1],a1
    spmask L2
    || add .L2 1,b7,b7
    nop 3
    add .L1 a1,a7,a2
    spkernel 0,0
    || stw .D2T1 a2,*b4++[1]
nested_rows_outer:
    [b2] b .S1 nested_rows_outer
    nop 2
    add .L1 1,a7,a7
    || [b2] sub .L2 b2,1,b2
    spmaskr
    nop 1
    b .S2 b3
    nop 5
    .balign 32
    .global kernel_copy, nested_skip, loop_isr_table, loop_isr
/* After SPRUFE8B Example 7-15: b8 words from a4, then (a1 more times) b9 words from a6, to b4. The
   body ends in SPKERNELR, so the reload starts with the post-loop packet, whose SPMASK replaces the
   reloaded pass's first load. Unlike TI's listing the destination just continues, because its OR of
   B4 lands in the same cycle as the last epilog STW's update of B4. */
kernel_copy:
    mvc .S2 b8,ilc
    mvc .S2 b9,rilc
    nop 3
    [a1] sploop 1
    ldw .D1T1 *a4++[1],a0
    nop 4
    mv .L2X a0,b0
    spkernelr
    || stw .D2T2 b0,*b4++[1]
kernel_copy_outer:
    spmask D1
    || [a1] b .S2 kernel_copy_outer
    || [a1] sub .S1 a1,1,a1
    || [a1] ldw .D1T1 *a6,a0
    || [a1] add .L1 4,a6,a4
    nop 4
    nop 1
    b .S2 b3
    nop 5
    .balign 32
/* Aligned-form accesses through misaligned pointers (not a loop; here for the comparison with the
   reference simulator). a4: 16 bytes aligned to 8, b4: output words. The unit ignores the low
   address bits (M1 bench I4). */
    .global misaligned
misaligned:
    add .L1 4,a4,a5
    || add .L2 2,b4,b5
    add .L1 2,a4,a3
    || add .S1 1,a4,a2
    lddw .D1T1 *a5,a7:a6
    ldw .D1T1 *a3,a8
    ldh .D1T1 *a2,a9
    add .L2 15,b5,b5
    nop 3
    stw .D2T1 a6,*b4
    stw .D2T1 a7,*+b4(4)
    stw .D2T1 a8,*+b4(8)
    stw .D2T1 a9,*+b4(12)
    stw .D2T1 a8,*b5++[1]
    mv .L1X b5,a4
    b .S2 b3
    nop 5
    .balign 32
/* A sign wrapper around a worker, in the shape compilers' integer division helpers take (not a loop;
   here for the comparison with the reference simulator). For a4 >= 0 the ADDKPC is skipped and its
   three NOP cycles are the last delay slots of the branch, so the worker returns straight to the
   caller; for a4 < 0 it sets the worker's return to sign_back, which negates the result. Returns
   a4 / 2 rounded towards zero. */
    .global sign_wrap
sign_wrap:
    b .S1 sign_work
    || cmpgt .L1 0,a4,a1
    [a1] neg .L1 a4,a4
    || mv .L2 b3,b5
    [a1] addkpc .S2 sign_back,b3,3
sign_back:
    neg .L1 a4,a4
    || b .S2 b5
    nop 5
sign_work:
    shru .S1 a4,1,a4
    b .S2 b3
    nop 5
    .balign 32
/* nested_fir with the reload count in b6: with 0 every reloaded pass is skipped and stores a zero sum. */
nested_skip:
    mvk .S2 8,b0
    mvc .S2 b0,ilc
    mvc .S2 b6,rilc
    mv .L2 b4,b5
    mvk .S2 3,b0
    nop 1
    [b0] sploop 2
    || mvk .S1 14,a5
    || mvk .L1 0,a7
    ldh .D1T1 *a4++[1],a2
    || ldh .D2T2 *b4++[1],b2
    nop 4
    mpy .M1X a2,b2,a3
    nop 1
    spkernel 0,0
    || add .L1 a3,a7,a7
nested_skip_outer:
    sub .L1 a4,a5,a4
    || mv .L2 b5,b4
    spmaskr
    [b0] bnop .S1 nested_skip_outer,4
    || [b0] sub .L2 b0,1,b0
    sth .D1T1 a7,*a6++[1]
    || mvk .S1 0,a7
    b .S2 b3
    nop 5
    .balign 32
    .global string_copy
/* strcpy(a4, b4) as cl6x 8.5 compiles `do { t = *s++; *d++ = t; } while (t);` at -O3: the condition
   register A1 is cleared 5 cycles before the stage boundary that must act on it (SPRUFE8B 7.10.2),
   and everything a later iteration does after that is predicated. */
string_copy:
    mvk .S1 1,a1
    [a1] sploopw 6
    nop 2
    [a1] ldb .D2T2 *b4++[1],b0
    nop 2
    spmask L1,L2
    || mv .L2X a4,b5
    || mv .L1 a1,a0
    nop 1
    [a0] stb .D2T2 b0,*b5++[1]
    || [!b0] mvk .L1 0,a1
    nop 1
    mv .L1 a1,a0
    nop 1
    spkernel 0,0
    b .S2 b3
    nop 5
    .balign 32
    .global dot_until
/* `do { sum += *x++ * *y++; n -= m; } while (n >= 0);` as cl6x 8.5 compiles it at -O3 (a5 = x, b4 = y,
   a4 = n, b6 = m; the sum is returned in a4). ii is 3 and the body 9 cycles: A2 is cleared in cycle 2
   and must end the loop at the boundary 9 cycles in, after this iteration's MPY and ADD, not at the
   boundary 3 cycles in. */
dot_until:
    mvk .S1 1,a2
    [a2] sploopw 3
    || mv .L2 b4,b8
    || mv .S1X b6,a6
    sub .L1 a4,a6,a4
    || [a2] ldh .D2T2 *b8++[1],b6
    || [a2] ldh .D1T1 *a5++[1],a7
    cmpgt .L1 0,a4,a1
    spmask L1
    || mv .L1 a2,a0
    || [a1] mvk .S1 0,a2
    nop 2
    spmask S2,L2
    || mvk .S2 0,b7
    || mvk .L2 0,b5
    || mv .D1 a2,a3
    || mpy .M2X b6,a7,b4
    nop 1
    add .L2 b4,b7,b7
    spkernel 0,0
    || [a0] mv .L2 b7,b5
    || mv .L1 a3,a0
    mv .L1X b5,a4
    b .S2 b3
    nop 5
/* No loop: a load, a long NOP and IDLE, for interrupts requested inside them (SPRUFE8B 5.5.4). It
   returns only once an interrupt has ended the IDLE. */
    .global wait_nop
wait_nop:
    ldw .D1T1 *a4,a0
    nop 9
    add .L1 1,a0,a0
    idle
    add .L1 a0,a0,a4
    b .S2 b3
    nop 5
/* Interrupt 4's service routine at ISTP + 0x80: counts its calls in the word at 0x5ff8. */
    .balign 1024
loop_isr_table:
    .space 128
loop_isr:
    mvk .S2 0x5ff8,b10
    ldw .D2T2 *b10,b11
    nop 4
    add .L2 1,b11,b11
    stw .D2T2 b11,*b10
    b .S2 irp
    nop 5
