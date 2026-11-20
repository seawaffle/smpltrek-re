/* SPLOOP bodies for the compiled-loop tests: several stages, results that land one or
   more iterations after their issue, predicates, a masked instruction and stores. */
    .section .text,"ax",@progbits
    .balign 32
    .global scale_loop, float_loop, masked_loop, while_loop
scale_loop:
    mvc .S2 b5,ilc
    mvk .S2 0,b7
    nop 2
    sploop 2
    ldh .D1T1 *a4++[1],a1
    nop 4
    mpy .M1 a1,a6,a2
    nop 1
    shr .S1 a2,4,a3
    || add .L2 1,b7,b7
    spkernel 4,0
    || sth .D2T1 a3,*b4++[1]
    b .S2 b3
    nop 5
    .balign 32
float_loop:
    mvk .S2 0,b7
    sploopd 1
    || mvc .S2 b5,ilc
    ldw .D1T1 *a4++[1],a1
    nop 4
    mpysp .M1 a1,a6,a2
    || and .L2 1,b7,b0
    nop 3
    addsp .L1 a2,a7,a7
    || add .S2 1,b7,b7
    || [b0] stw .D2T1 a2,*b4++[1]
    spkernel 0,0
    || [!b0] add .L2 b8,b7,b8
    b .S2 b3
    nop 5
    .balign 32
masked_loop:
    mvc .S2 b5,ilc
    mvk .S2 0,b7
    nop 2
    sploop 3
    spmask L2
    || add .L2 1,b7,b7
    || ldbu .D1T1 *a4++[1],a1
    nop 4
    add .L1 a1,a7,a7
    spkernel 0,0
    || stb .D2T1 a7,*b4++[1]
    b .S2 b3
    nop 5
    .balign 32
while_loop:
    mv .L2 b5,b0
    mvk .S2 0,b7
    [b0] sploopw 2
    ldbu .D1T1 *a4++[1],a1
    || sub .L2 b0,1,b0
    nop 4
    add .L1 a1,a7,a7
    || add .L2 1,b7,b7
    spkernel 0,0
    || stb .D2T1 a7,*b4++[1]
    b .S2 b3
    nop 5
    .balign 32
