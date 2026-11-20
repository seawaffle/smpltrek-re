/* Start-up support for app.c (tests/test_app.py): the interrupt vector table and the stub that lets a C
   function serve interrupt 4. GCC for this CPU has no interrupt attribute, so the stub does what one would:
   it saves every register the C calling convention lets a function change (A0-A9, A16-A31, B0-B9, B16-B31)
   and the loop counters ILC and RILC on the interrupted stack, calls app_block, restores them and returns
   through IRP. ISTP is set to `vectors` by whoever starts the program. */
    .text
    .global vectors, tick_entry
    .balign 1024
vectors:
    .space 128
    stw .D2T2 b0,*b15--[2]
    mvkl .S2 tick_entry,b0
    mvkh .S2 tick_entry,b0
    b .S2 b0
    ldw .D2T2 *++b15[2],b0
    nop 4
    .balign 32
tick_entry:
    addk .S2 -224,b15
    stw .D2T1 a0,*+b15(8)
    stw .D2T1 a1,*+b15(12)
    stw .D2T1 a2,*+b15(16)
    stw .D2T1 a3,*+b15(20)
    stw .D2T1 a4,*+b15(24)
    stw .D2T1 a5,*+b15(28)
    stw .D2T1 a6,*+b15(32)
    stw .D2T1 a7,*+b15(36)
    stw .D2T1 a8,*+b15(40)
    stw .D2T1 a9,*+b15(44)
    stw .D2T1 a16,*+b15(48)
    stw .D2T1 a17,*+b15(52)
    stw .D2T1 a18,*+b15(56)
    stw .D2T1 a19,*+b15(60)
    stw .D2T1 a20,*+b15(64)
    stw .D2T1 a21,*+b15(68)
    stw .D2T1 a22,*+b15(72)
    stw .D2T1 a23,*+b15(76)
    stw .D2T1 a24,*+b15(80)
    stw .D2T1 a25,*+b15(84)
    stw .D2T1 a26,*+b15(88)
    stw .D2T1 a27,*+b15(92)
    stw .D2T1 a28,*+b15(96)
    stw .D2T1 a29,*+b15(100)
    stw .D2T1 a30,*+b15(104)
    stw .D2T1 a31,*+b15(108)
    stw .D2T2 b0,*+b15(112)
    stw .D2T2 b1,*+b15(116)
    stw .D2T2 b2,*+b15(120)
    stw .D2T2 b3,*+b15(124)
    stw .D2T2 b4,*+b15(128)
    stw .D2T2 b5,*+b15(132)
    stw .D2T2 b6,*+b15(136)
    stw .D2T2 b7,*+b15(140)
    stw .D2T2 b8,*+b15(144)
    stw .D2T2 b9,*+b15(148)
    stw .D2T2 b16,*+b15(152)
    stw .D2T2 b17,*+b15(156)
    stw .D2T2 b18,*+b15(160)
    stw .D2T2 b19,*+b15(164)
    stw .D2T2 b20,*+b15(168)
    stw .D2T2 b21,*+b15(172)
    stw .D2T2 b22,*+b15(176)
    stw .D2T2 b23,*+b15(180)
    stw .D2T2 b24,*+b15(184)
    stw .D2T2 b25,*+b15(188)
    stw .D2T2 b26,*+b15(192)
    stw .D2T2 b27,*+b15(196)
    stw .D2T2 b28,*+b15(200)
    stw .D2T2 b29,*+b15(204)
    stw .D2T2 b30,*+b15(208)
    stw .D2T2 b31,*+b15(212)
    mvc .S2 ilc,b0
    mvc .S2 rilc,b1
    stw .D2T2 b0,*+b15(216)
    stw .D2T2 b1,*+b15(220)
    callp .S2 app_block,b3
    ldw .D2T2 *+b15(216),b0
    ldw .D2T2 *+b15(220),b1
    nop 3
    mvc .S2 b0,ilc
    mvc .S2 b1,rilc
    ldw .D2T1 *+b15(8),a0
    ldw .D2T1 *+b15(12),a1
    ldw .D2T1 *+b15(16),a2
    ldw .D2T1 *+b15(20),a3
    ldw .D2T1 *+b15(24),a4
    ldw .D2T1 *+b15(28),a5
    ldw .D2T1 *+b15(32),a6
    ldw .D2T1 *+b15(36),a7
    ldw .D2T1 *+b15(40),a8
    ldw .D2T1 *+b15(44),a9
    ldw .D2T1 *+b15(48),a16
    ldw .D2T1 *+b15(52),a17
    ldw .D2T1 *+b15(56),a18
    ldw .D2T1 *+b15(60),a19
    ldw .D2T1 *+b15(64),a20
    ldw .D2T1 *+b15(68),a21
    ldw .D2T1 *+b15(72),a22
    ldw .D2T1 *+b15(76),a23
    ldw .D2T1 *+b15(80),a24
    ldw .D2T1 *+b15(84),a25
    ldw .D2T1 *+b15(88),a26
    ldw .D2T1 *+b15(92),a27
    ldw .D2T1 *+b15(96),a28
    ldw .D2T1 *+b15(100),a29
    ldw .D2T1 *+b15(104),a30
    ldw .D2T1 *+b15(108),a31
    ldw .D2T2 *+b15(112),b0
    ldw .D2T2 *+b15(116),b1
    ldw .D2T2 *+b15(120),b2
    ldw .D2T2 *+b15(124),b3
    ldw .D2T2 *+b15(128),b4
    ldw .D2T2 *+b15(132),b5
    ldw .D2T2 *+b15(136),b6
    ldw .D2T2 *+b15(140),b7
    ldw .D2T2 *+b15(144),b8
    ldw .D2T2 *+b15(148),b9
    ldw .D2T2 *+b15(152),b16
    ldw .D2T2 *+b15(156),b17
    ldw .D2T2 *+b15(160),b18
    ldw .D2T2 *+b15(164),b19
    ldw .D2T2 *+b15(168),b20
    ldw .D2T2 *+b15(172),b21
    ldw .D2T2 *+b15(176),b22
    ldw .D2T2 *+b15(180),b23
    ldw .D2T2 *+b15(184),b24
    ldw .D2T2 *+b15(188),b25
    ldw .D2T2 *+b15(192),b26
    ldw .D2T2 *+b15(196),b27
    ldw .D2T2 *+b15(200),b28
    ldw .D2T2 *+b15(204),b29
    ldw .D2T2 *+b15(208),b30
    ldw .D2T2 *+b15(212),b31
    b .S2 irp
    nop 4
    addk .S2 224,b15
