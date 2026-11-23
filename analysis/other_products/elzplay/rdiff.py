import os
import sys
sys.path.insert(0,'analysis')
import region_diff as R
from pathlib import Path
S=Path(os.environ.get('OTHER_OUT', 'work/other/elzplay'))
W=Path('work')
B=Path('firmware/other')
R.PRODUCTS[:]=[("ELZ_1 play 3.1.149", S/"ELZ_1_play_V3_1_149.elf", W/"match-3.2.174-ELZ_1_play_V3_1_149.json"),
               ("MINIMAL 1.0.58", S/"MINIMAL_v1.0.58.elf", W/"match-3.2.174-MINIMAL_v1.0.58.json")]
R.IMAGES[:]=[B/"ELZ_1_play_V3_1_149.zip", B/"MINIMAL_v1.0.58.zip"]
R.main()
