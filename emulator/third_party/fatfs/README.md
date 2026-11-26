FatFs R0.15a by ChaN, from http://elm-chan.org/fsw/ff/ (ff15a.zip). The configuration used by the emulator's host
card tool is emulator/native/ffconf.h. Licence: LICENSE.txt (BSD-style, one clause). Not Sonicware code.

One local change (2026-11-26): ff.c `FSI_TrailSig` is 508, not 498. Microsoft's FAT specification ("FSInfo Sector
Structure") puts the FSInfo trailing signature 0xAA550000 at offset 508; f_mkfs already writes it there (0xAA55 at
510). With 498, mount rejected every correct FSInfo sector, its own included. The free-cluster count then stayed
unknown and FSInfo was never rewritten, so a FAT32 volume kept f_mkfs's free count after files were written
(fsck.fat: "Free cluster summary wrong"). After f_getfree, sync_fs would also have written the signature at 498.
The card tool formats FAT12/16 only (FM_FAT), so its images are unaffected: a 128 MiB card is byte-identical
before and after. Enaga carries the same fix.

Upstream: R0.15 and earlier wrote and checked 0xAA55 at offset 510 (`BS_55AA`), which is correct. ChaN's release
notes for R0.15b (Jun 21, 2025, http://elm-chan.org/fsw/ff/updates.html) say "Fixed FatFs fails to load the FsInfo
in FAT32 volumes" and that the bug appeared at R0.15a. This file is ff15a.zip's source/ff.c with only that line
changed.
