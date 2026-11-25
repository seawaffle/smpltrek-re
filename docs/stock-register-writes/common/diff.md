# Register sequences compared with smpltrek-3.2.174

## lofi-12xt-1.5.205

### usb0.csv: identical

- `boot`: identical (36 rows)
- `bus_reset`: identical (5 rows)
- `enumeration`: identical (61 rows)
- `bulk_out`: identical (23 rows)
- `interface_on`: identical (32 rows)
- `interface_off`: identical (22 rows)
- `suspend`: identical (10 rows)
- `detach`: identical (5 rows)

### i2c0.csv: identical

- `boot`: identical (99 rows)
- `interface_off`: identical (19 rows)
- `power_off`: identical (17 rows)

### codec.csv: identical

- `boot`: identical (49 rows)
- `interface_off`: identical (3 rows)
- `power_off`: identical (2 rows)

### mcasp-edma.csv: differs

- `boot`: 235 rows in smpltrek-3.2.174, 235 in lofi-12xt-1.5.205; 9 difference(s), 17 rows
  - replace at row 85: smpltrek-3.2.174 `write PaRAM0.A_B_CNT 0xff0004; write PaRAM0.DST 0x11f00800` / lofi-12xt-1.5.205 `write PaRAM0.A_B_CNT 0xbf0004; write PaRAM0.DST 0x11f024c8`
  - replace at row 88: smpltrek-3.2.174 `write PaRAM0.LINK_BCNTRLD 0xff4820` / lofi-12xt-1.5.205 `write PaRAM0.LINK_BCNTRLD 0xbf4820`
  - replace at row 93: smpltrek-3.2.174 `write PaRAM65.A_B_CNT 0x1000004; write PaRAM65.DST 0x11f00c00` / lofi-12xt-1.5.205 `write PaRAM65.A_B_CNT 0xc00004; write PaRAM65.DST 0x11f027c8`
  - replace at row 96: smpltrek-3.2.174 `write PaRAM65.LINK_BCNTRLD 0x1004800` / lofi-12xt-1.5.205 `write PaRAM65.LINK_BCNTRLD 0xc04800`
  - replace at row 100: smpltrek-3.2.174 `write PaRAM1.SRC 0x11f00000; write PaRAM1.A_B_CNT 0xff0004` / lofi-12xt-1.5.205 `write PaRAM1.SRC 0x11f01ec8; write PaRAM1.A_B_CNT 0xbf0004`
  - replace at row 104: smpltrek-3.2.174 `write PaRAM1.LINK_BCNTRLD 0xff4860` / lofi-12xt-1.5.205 `write PaRAM1.LINK_BCNTRLD 0xbf4860`
  - replace at row 108: smpltrek-3.2.174 `write PaRAM67.SRC 0x11f00400; write PaRAM67.A_B_CNT 0x1000004` / lofi-12xt-1.5.205 `write PaRAM67.SRC 0x11f021c8; write PaRAM67.A_B_CNT 0xc00004`
  - replace at row 112: smpltrek-3.2.174 `write PaRAM67.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `write PaRAM67.LINK_BCNTRLD 0xc04840`
  - replace at row 229: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM1.LINK_BCNTRLD 0x1004860` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860`
- `attach`: 18 rows in smpltrek-3.2.174, 19 in lofi-12xt-1.5.205; 3 difference(s), 9 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `read PaRAM1.LINK_BCNTRLD 0xc04860`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read IPR 0x80000; write ICR 0x80000` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM0.LINK_BCNTRLD 0xc04820`
  - replace at row 18: smpltrek-3.2.174 `write EESR 0x40000` / lofi-12xt-1.5.205 `read IPR 0x80000; write ICR 0x80000; write ICR 0x80000`
- `bus_reset`: 8 rows in smpltrek-3.2.174, 10 in lofi-12xt-1.5.205; 2 difference(s), 7 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `read PaRAM1.LINK_BCNTRLD 0xc04860`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM0.LINK_BCNTRLD 0x1004800` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read IPR 0x80000; write ICR 0x80000; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM0.LINK_BCNTRLD 0xc04820`
- `enumeration`: 17 rows in smpltrek-3.2.174, 8 in lofi-12xt-1.5.205; 2 difference(s), 14 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `read PaRAM1.LINK_BCNTRLD 0xc04840`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; write SECR 0x80000; read EMCR 0x0; write EMCR 0x80000 ...` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM0.LINK_BCNTRLD 0xc04800`
- `bulk_out`: 19 rows in smpltrek-3.2.174, 19 in lofi-12xt-1.5.205; 2 difference(s), 8 rows
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840`
  - insert at row 17: smpltrek-3.2.174 `(none)` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860`
- `interface_on`: 10 rows in smpltrek-3.2.174, 18 in lofi-12xt-1.5.205; 2 difference(s), 16 rows
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM1.LINK_BCNTRLD 0xc04840; write SECR 0x80000 ...`
  - delete at row 8: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM1.LINK_BCNTRLD 0x1004860` / lofi-12xt-1.5.205 `(none)`
- `interface_off`: 16 rows in smpltrek-3.2.174, 8 in lofi-12xt-1.5.205; 2 difference(s), 14 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / lofi-12xt-1.5.205 `read PaRAM1.LINK_BCNTRLD 0xc04860`
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM1.LINK_BCNTRLD 0x1004860; write SECR 0x80000 ...` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM0.LINK_BCNTRLD 0xc04820`
- `suspend`: 10 rows in smpltrek-3.2.174, 18 in lofi-12xt-1.5.205; 3 difference(s), 16 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / lofi-12xt-1.5.205 `read PaRAM1.LINK_BCNTRLD 0xc04860`
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM0.LINK_BCNTRLD 0xc04820; write SECR 0x80000; read EMCR 0x0 ...`
  - delete at row 8: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `(none)`
- `detach`: 18 rows in smpltrek-3.2.174, 18 in lofi-12xt-1.5.205; 2 difference(s), 5 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `read PaRAM1.LINK_BCNTRLD 0xc04860`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM0.LINK_BCNTRLD 0x1004800` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM0.LINK_BCNTRLD 0xc04820`
- `power_off`: 28 rows in smpltrek-3.2.174, 40 in lofi-12xt-1.5.205; 4 difference(s), 19 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004860` / lofi-12xt-1.5.205 `read PaRAM1.LINK_BCNTRLD 0xc04840`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840` / lofi-12xt-1.5.205 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM0.LINK_BCNTRLD 0xc04800`
  - delete at row 15: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM0.LINK_BCNTRLD 0x1004820` / lofi-12xt-1.5.205 `(none)`
  - insert at row 29: smpltrek-3.2.174 `(none)` / lofi-12xt-1.5.205 `write SECR 0x8000; write EMCR 0x8000; write EESR 0x8000; write SECR 0x4000; write EMCR 0x4000; write EESR 0x4000 ...`

### mmcsd.csv: differs

- `boot`: 177 rows in smpltrek-3.2.174, 177 in lofi-12xt-1.5.205; 4 difference(s), 5 rows
  - replace at row 100: smpltrek-3.2.174 `write PaRAM16.DST 0xc1502080` / lofi-12xt-1.5.205 `write PaRAM16.DST 0xc2b7d900`
  - replace at row 104: smpltrek-3.2.174 `write PaRAM16.CCNT 0xc1640001` / lofi-12xt-1.5.205 `write PaRAM16.CCNT 0xc2c70001`
  - replace at row 159: smpltrek-3.2.174 `write PaRAM16.DST 0xc14f6600; write PaRAM16.CCNT 0xc14b0008` / lofi-12xt-1.5.205 `write PaRAM16.DST 0xc2b72800; write PaRAM16.CCNT 0xc2b70008`
  - replace at row 177: smpltrek-3.2.174 `summary (the remaining 268 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) ` / lofi-12xt-1.5.205 `summary (the remaining 29154 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `power_off`: 0 rows in smpltrek-3.2.174, 1 in lofi-12xt-1.5.205; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / lofi-12xt-1.5.205 `summary (the 91 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `

### sd-commands.csv: differs

- `boot`: 18 rows in smpltrek-3.2.174, 18 in lofi-12xt-1.5.205; 1 difference(s), 1 rows
  - replace at row 18: smpltrek-3.2.174 `data: CMD12 x2, CMD13 x99, CMD17 x72, CMD24 x96, CMD25 x2 0x00000000..0x00013200 ` / lofi-12xt-1.5.205 `data: CMD12 x6960, CMD13 x4278, CMD17 x10162, CMD18 x3480, CMD24 x797, CMD25 x3480 0x00000000..0x00e2b200 `
- `power_off`: 0 rows in smpltrek-3.2.174, 1 in lofi-12xt-1.5.205; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / lofi-12xt-1.5.205 `data: CMD12 x24, CMD13 x32, CMD17 x11, CMD24 x8, CMD25 x24 0x00000000..0x00e43400 `

## cydrums-1.1.84

### usb0.csv: differs

- `boot`: identical (36 rows)
- `bus_reset`: identical (5 rows)
- `enumeration`: identical (61 rows)
- `bulk_out`: identical (23 rows)
- `interface_on`: identical (32 rows)
- `interface_off`: 22 rows in smpltrek-3.2.174, 23 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 14: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `read FIFO0 data`
- `suspend`: identical (10 rows)
- `detach`: identical (5 rows)

### i2c0.csv: identical

- `boot`: identical (99 rows)
- `interface_off`: identical (19 rows)
- `power_off`: identical (17 rows)

### codec.csv: identical

- `boot`: identical (49 rows)
- `interface_off`: identical (3 rows)
- `power_off`: identical (2 rows)

### mcasp-edma.csv: differs

- `boot`: 235 rows in smpltrek-3.2.174, 235 in cydrums-1.1.84; 9 difference(s), 17 rows
  - replace at row 85: smpltrek-3.2.174 `write PaRAM0.A_B_CNT 0xff0004; write PaRAM0.DST 0x11f00800` / cydrums-1.1.84 `write PaRAM0.A_B_CNT 0xbf0004; write PaRAM0.DST 0x11f02930`
  - replace at row 88: smpltrek-3.2.174 `write PaRAM0.LINK_BCNTRLD 0xff4820` / cydrums-1.1.84 `write PaRAM0.LINK_BCNTRLD 0xbf4820`
  - replace at row 93: smpltrek-3.2.174 `write PaRAM65.A_B_CNT 0x1000004; write PaRAM65.DST 0x11f00c00` / cydrums-1.1.84 `write PaRAM65.A_B_CNT 0xc00004; write PaRAM65.DST 0x11f02c30`
  - replace at row 96: smpltrek-3.2.174 `write PaRAM65.LINK_BCNTRLD 0x1004800` / cydrums-1.1.84 `write PaRAM65.LINK_BCNTRLD 0xc04800`
  - replace at row 100: smpltrek-3.2.174 `write PaRAM1.SRC 0x11f00000; write PaRAM1.A_B_CNT 0xff0004` / cydrums-1.1.84 `write PaRAM1.SRC 0x11f02330; write PaRAM1.A_B_CNT 0xbf0004`
  - replace at row 104: smpltrek-3.2.174 `write PaRAM1.LINK_BCNTRLD 0xff4860` / cydrums-1.1.84 `write PaRAM1.LINK_BCNTRLD 0xbf4860`
  - replace at row 108: smpltrek-3.2.174 `write PaRAM67.SRC 0x11f00400; write PaRAM67.A_B_CNT 0x1000004` / cydrums-1.1.84 `write PaRAM67.SRC 0x11f02630; write PaRAM67.A_B_CNT 0xc00004`
  - replace at row 112: smpltrek-3.2.174 `write PaRAM67.LINK_BCNTRLD 0x1004840` / cydrums-1.1.84 `write PaRAM67.LINK_BCNTRLD 0xc04840`
  - replace at row 229: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM1.LINK_BCNTRLD 0x1004860` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860`
- `attach`: 18 rows in smpltrek-3.2.174, 20 in cydrums-1.1.84; 5 difference(s), 13 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / cydrums-1.1.84 `read EMCR 0x0; read EECR 0x0; read EESR 0x0`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read IPR 0x80000; write ICR 0x80000` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM1.LINK_BCNTRLD 0xc04840`
  - delete at row 11: smpltrek-3.2.174 `read EMCR 0x0` / cydrums-1.1.84 `(none)`
  - delete at row 13: smpltrek-3.2.174 `read EESR 0x0` / cydrums-1.1.84 `(none)`
  - replace at row 18: smpltrek-3.2.174 `write EESR 0x40000` / cydrums-1.1.84 `read IPR 0x80000; write ICR 0x80000; write ICR 0x80000`
- `bus_reset`: 8 rows in smpltrek-3.2.174, 16 in cydrums-1.1.84; 2 difference(s), 13 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / cydrums-1.1.84 `read EMCR 0x0; read EECR 0x0; read EESR 0x0`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM0.LINK_BCNTRLD 0x1004800` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; write SECR 0x80000; write EMCR 0x80000 ...`
- `enumeration`: 17 rows in smpltrek-3.2.174, 13 in cydrums-1.1.84; 3 difference(s), 17 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / cydrums-1.1.84 `read EMCR 0x0; read EECR 0x0; read EESR 0x0`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; write SECR 0x80000; read EMCR 0x0; write EMCR 0x80000 ...` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840`
  - insert at row 18: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860`
- `bulk_out`: 19 rows in smpltrek-3.2.174, 21 in cydrums-1.1.84; 3 difference(s), 11 rows
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read PaRAM1.LINK_BCNTRLD 0x1004840` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read EMCR 0x0; read EECR 0x0; read EESR 0x0; read EESR 0x0 ...`
  - delete at row 10: smpltrek-3.2.174 `read EMCR 0x0` / cydrums-1.1.84 `(none)`
  - delete at row 12: smpltrek-3.2.174 `read EESR 0x0` / cydrums-1.1.84 `(none)`
- `interface_on`: 10 rows in smpltrek-3.2.174, 11 in cydrums-1.1.84; 2 difference(s), 10 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `read EMCR 0x0; read EECR 0x0; read EESR 0x0`
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read IPR 0x80000; write ICR 0x80000; read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860 ...` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860`
- `interface_off`: 16 rows in smpltrek-3.2.174, 19 in cydrums-1.1.84; 4 difference(s), 12 rows
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840; read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM1.LINK_BCNTRLD 0x1004860` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read EMCR 0x0; read EECR 0x0; read EESR 0x0`
  - delete at row 10: smpltrek-3.2.174 `read EMCR 0x0` / cydrums-1.1.84 `(none)`
  - delete at row 12: smpltrek-3.2.174 `read EESR 0x0` / cydrums-1.1.84 `(none)`
  - insert at row 17: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860; read IPR 0x80000; write ICR 0x80000`
- `suspend`: 10 rows in smpltrek-3.2.174, 12 in cydrums-1.1.84; 1 difference(s), 9 rows
  - replace at row 4: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read IPR 0x80000; write ICR 0x80000; read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840 ...` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840; read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860; read EMCR 0x0 ...`
- `detach`: 18 rows in smpltrek-3.2.174, 20 in cydrums-1.1.84; 6 difference(s), 13 rows
  - replace at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004840` / cydrums-1.1.84 `read EMCR 0x0; read EECR 0x0; read EESR 0x0`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM1.LINK_BCNTRLD 0x1004860; read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM0.LINK_BCNTRLD 0x1004800` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04800; read PaRAM1.LINK_BCNTRLD 0xc04840`
  - delete at row 10: smpltrek-3.2.174 `read EMCR 0x0` / cydrums-1.1.84 `(none)`
  - delete at row 12: smpltrek-3.2.174 `read EESR 0x0` / cydrums-1.1.84 `(none)`
  - insert at row 17: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read PaRAM1.LINK_BCNTRLD 0xc04860`
  - insert at row 19: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `write ICR 0x80000`
- `power_off`: 28 rows in smpltrek-3.2.174, 41 in cydrums-1.1.84; 7 difference(s), 27 rows
  - delete at row 1: smpltrek-3.2.174 `read PaRAM1.LINK_BCNTRLD 0x1004860` / cydrums-1.1.84 `(none)`
  - replace at row 5: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004800; read PaRAM1.LINK_BCNTRLD 0x1004840` / cydrums-1.1.84 `read PaRAM0.LINK_BCNTRLD 0xc04820; read PaRAM1.LINK_BCNTRLD 0xc04860; read EMCR 0x0; read EECR 0x0; read EESR 0x0; read EESR 0x0 ...`
  - delete at row 8: smpltrek-3.2.174 `read EMCR 0x0` / cydrums-1.1.84 `(none)`
  - delete at row 10: smpltrek-3.2.174 `read EESR 0x0` / cydrums-1.1.84 `(none)`
  - delete at row 15: smpltrek-3.2.174 `read PaRAM0.LINK_BCNTRLD 0x1004820; read PaRAM0.LINK_BCNTRLD 0x1004820` / cydrums-1.1.84 `(none)`
  - delete at row 24: smpltrek-3.2.174 `read EECR 0x0` / cydrums-1.1.84 `(none)`
  - insert at row 29: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `write SECR 0x8000; write EMCR 0x8000; write EESR 0x8000; write SECR 0x4000; write EMCR 0x4000; write EESR 0x4000 ...`

### mmcsd.csv: differs

- `boot`: 177 rows in smpltrek-3.2.174, 177 in cydrums-1.1.84; 5 difference(s), 8 rows
  - replace at row 84: smpltrek-3.2.174 `read MMCRSP01 0xa4000cf; read MMCRSP23 0xc0017f80` / cydrums-1.1.84 `read MMCRSP01 0xa400053; read MMCRSP23 0xc0027f80`
  - replace at row 100: smpltrek-3.2.174 `write PaRAM16.DST 0xc1502080` / cydrums-1.1.84 `write PaRAM16.DST 0xc242ea00`
  - replace at row 104: smpltrek-3.2.174 `write PaRAM16.CCNT 0xc1640001` / cydrums-1.1.84 `write PaRAM16.CCNT 0xc2590001`
  - replace at row 159: smpltrek-3.2.174 `write PaRAM16.DST 0xc14f6600; write PaRAM16.CCNT 0xc14b0008` / cydrums-1.1.84 `write PaRAM16.DST 0xc2424680; write PaRAM16.CCNT 0xc2420008`
  - replace at row 176: smpltrek-3.2.174 `write MMCARGHL 0x4400; summary (the remaining 268 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) ` / cydrums-1.1.84 `write MMCARGHL 0x8400; summary (the remaining 16476 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `attach`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 211 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `bus_reset`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 26 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `enumeration`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 54 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `bulk_out`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 751 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `interface_on`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 50 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `interface_off`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 31 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `suspend`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 30 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `detach`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 122 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `
- `power_off`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `summary (the 3886 SD commands of this phase: file reads and writes, in sd-commands.csv; their register sequence repeats the first block read's) `

### sd-commands.csv: differs

- `boot`: 18 rows in smpltrek-3.2.174, 18 in cydrums-1.1.84; 1 difference(s), 1 rows
  - replace at row 18: smpltrek-3.2.174 `data: CMD12 x2, CMD13 x99, CMD17 x72, CMD24 x96, CMD25 x2 0x00000000..0x00013200 ` / cydrums-1.1.84 `data: CMD12 x5904, CMD13 x1, CMD17 x4669, CMD18 x5905 0x00000000..0x05676600 `
- `attach`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x105, CMD17 x1, CMD18 x105 0x00000000..0x028de400 `
- `bus_reset`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x13, CMD18 x13 0x00000000..0x028f8400 `
- `enumeration`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x27, CMD18 x27 0x00000000..0x0292e400 `
- `bulk_out`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x373, CMD17 x5, CMD18 x373 0x00000000..0x02c18400 `
- `interface_on`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x25, CMD18 x25 0x00000000..0x02c4a400 `
- `interface_off`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x16, CMD18 x15 0x00000000..0x02c68400 `
- `suspend`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x14, CMD17 x1, CMD18 x15 0x00000000..0x02c86400 `
- `detach`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x61, CMD18 x61 0x00000000..0x02d00400 `
- `power_off`: 0 rows in smpltrek-3.2.174, 1 in cydrums-1.1.84; 1 difference(s), 1 rows
  - insert at row 1: smpltrek-3.2.174 `(none)` / cydrums-1.1.84 `data: CMD12 x3129, CMD13 x9, CMD17 x47, CMD18 x3124, CMD24 x5, CMD25 x4 0x00000000..0x04c74000 `
