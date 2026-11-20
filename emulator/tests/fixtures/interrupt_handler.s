/* An interrupt handler for tests/compiled_c.py --interrupts, linked on its own at 0xC8000000 and used as the
   vector table of interrupt 4 (ISTP + 4 * 32). It behaves as a compiled handler does: it pushes the registers
   it uses onto the interrupted code's stack, does some work with them (a load, a store, a multiply, a compare,
   a short branch), pops them and returns through IRP. Its only lasting effect is the call count.
   Assembled with --defsym GAP=n (n > 0), it first moves the stack pointer n bytes down and puts it back as it
   returns, so that nothing within n bytes below the interrupted stack pointer is written. */
    .text
    .global _start, handler
_start:
    .space 128
handler:
    .if GAP
    addk .S2 -GAP,b15
    .endif
    stw .D2T2 b4,*b15--[1]
    stw .D2T2 b5,*b15--[1]
    stw .D2T1 a4,*b15--[1]
    stw .D2T1 a3,*b15--[1]
    stw .D2T2 b0,*b15--[1]
    stw .D2T2 b3,*b15--[1]
    mvkl .S2 count,b4
    mvkh .S2 count,b4
    ldw .D2T2 *b4,b5
    mvk .S1 77,a4
    mvk .S1 -3,a3
    mpy .M1 a4,a3,a4
    mvk .S2 1,b0
    mvk .S2 0,b3
    add .L2 1,b5,b5
    [b0] b .S1 handler_store
    cmplt .L1 a4,a3,a3
    nop 4
    mvk .S2 0,b5
handler_store:
    stw .D2T2 b5,*b4
    ldw .D2T2 *++b15[1],b3
    ldw .D2T2 *++b15[1],b0
    ldw .D2T1 *++b15[1],a3
    ldw .D2T1 *++b15[1],a4
    ldw .D2T2 *++b15[1],b5
    b .S2 irp
    ldw .D2T2 *++b15[1],b4
    .if GAP
    addk .S2 GAP,b15
    nop 3
    .else
    nop 4
    .endif
    .balign 32
count:
    .word 0
