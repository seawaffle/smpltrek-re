/* ASCII-only stand-ins for the three conversion routines FatFs needs when long file names are
 * enabled (its own ffunicode.c is not part of this tree). A name with any other character is
 * rejected by FatFs as invalid, so nothing is silently renamed. Host card builder only. */
#include "ff.h"

WCHAR ff_uni2oem(DWORD uni, WORD cp) { (void)cp; return uni < 0x80 ? (WCHAR)uni : 0; }
WCHAR ff_oem2uni(WCHAR oem, WORD cp) { (void)cp; return oem < 0x80 ? oem : 0; }
DWORD ff_wtoupper(DWORD uni) { return uni >= 'a' && uni <= 'z' ? uni - 32 : uni; }
