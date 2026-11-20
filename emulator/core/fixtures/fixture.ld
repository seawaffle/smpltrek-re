OUTPUT_FORMAT("elf32-tic6x-le")
OUTPUT_ARCH(tic6x)
ENTRY(_start)
SECTIONS {
    . = 0xC2000000;
    .text : { *(.text .text.*) . = ALIGN(32); }
    .const : { *(.rodata .rodata.* .const .const.* .switch .switch.*) }
    .data : { *(.data .data.* .fardata .fardata.*) }
    .bss (NOLOAD) : { *(.bss .bss.* .far .far.*) }
    /DISCARD/ : { *(.c6xabi.attributes) *(.c6xabi.exidx*) *(.comment) *(.note*) }
}
