/* Host tool: build a FAT card image holding files, using FatFs itself over a RAM disk.
 *   mkimage OUT.IMG SIZE_MB [/PATH/ON/CARD=local/file ...]
 * Directories are created as needed (8.3 names unless built with long names; see emulator/media.py).
 * The emulator uses it to give the simulated MMCSD controller a card holding chosen files. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ff.h"
#include "diskio.h"

static unsigned char *disk;
static DWORD sectors;

DSTATUS disk_status(BYTE d) { (void)d; return 0; }
DSTATUS disk_initialize(BYTE d) { (void)d; return 0; }
DRESULT disk_read(BYTE d, BYTE *b, LBA_t s, UINT n) { (void)d; memcpy(b, disk + s * 512, n * 512); return RES_OK; }
DRESULT disk_write(BYTE d, const BYTE *b, LBA_t s, UINT n) { (void)d; memcpy(disk + s * 512, b, n * 512); return RES_OK; }
DRESULT disk_ioctl(BYTE d, BYTE cmd, void *buff)
{
    (void)d;
    switch (cmd) {
    case CTRL_SYNC: return RES_OK;
    case GET_SECTOR_COUNT: *(LBA_t *)buff = sectors; return RES_OK;
    case GET_SECTOR_SIZE: *(WORD *)buff = 512; return RES_OK;
    case GET_BLOCK_SIZE: *(DWORD *)buff = 1; return RES_OK;
    }
    return RES_PARERR;
}

static void mkdirs(const char *path)
{
    char tmp[128]; size_t i;
    strncpy(tmp, path, sizeof tmp - 1); tmp[sizeof tmp - 1] = 0;
    for (i = 1; tmp[i]; i++)
        if (tmp[i] == '/') { tmp[i] = 0; f_mkdir(tmp); tmp[i] = '/'; }
}

int main(int argc, char **argv)
{
    static FATFS fs; static BYTE work[4096];
    MKFS_PARM opt = { FM_FAT | FM_SFD, 1, 0, 0, 0 };
    int i;
    if (argc < 3) { fprintf(stderr, "usage: mkimage OUT.IMG SIZE_MB [/CARD/PATH=file ...]\n"); return 2; }
    sectors = (DWORD)atoi(argv[2]) * 2048;
    disk = calloc(sectors, 512);
    if (f_mkfs("", &opt, work, sizeof work) != FR_OK) { fprintf(stderr, "mkfs failed\n"); return 1; }
    if (f_mount(&fs, "", 1) != FR_OK) { fprintf(stderr, "mount failed\n"); return 1; }
    for (i = 3; i < argc; i++) {
        char *eq = strchr(argv[i], '='); FIL f; FILE *in; UINT put; size_t n; static unsigned char buf[65536];
        if (!eq) { fprintf(stderr, "bad spec %s\n", argv[i]); return 2; }
        *eq = 0;
        mkdirs(argv[i]);
        if (f_open(&f, argv[i], FA_WRITE | FA_CREATE_ALWAYS) != FR_OK) { fprintf(stderr, "cannot create %s\n", argv[i]); return 1; }
        in = fopen(eq + 1, "rb");
        if (!in) { fprintf(stderr, "cannot read %s\n", eq + 1); return 1; }
        while ((n = fread(buf, 1, sizeof buf, in)) > 0)
            if (f_write(&f, buf, (UINT)n, &put) != FR_OK || put != n) { fprintf(stderr, "write failed\n"); return 1; }
        if (ferror(in)) { fprintf(stderr, "cannot read %s\n", eq + 1); return 1; }
        fclose(in);
        if (f_close(&f) != FR_OK) { fprintf(stderr, "cannot finish %s\n", argv[i]); return 1; }
    }
    if (f_unmount("") != FR_OK) { fprintf(stderr, "unmount failed\n"); return 1; }
    {
        /* Report every failure of the image write: a short write (disk full, file-size limit) must not exit 0. */
        FILE *out = fopen(argv[1], "wb");
        if (!out) { perror(argv[1]); return 1; }
        size_t written = fwrite(disk, 512, sectors, out);
        int closed = fclose(out);
        if (written != (size_t)sectors || closed != 0) {
            fprintf(stderr, "%s: short write (%zu of %lu sectors)\n", argv[1], written, (unsigned long)sectors);
            remove(argv[1]);
            return 1;
        }
    }
    return 0;
}
