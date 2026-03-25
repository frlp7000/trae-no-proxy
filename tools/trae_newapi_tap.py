#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trae_custom_endpoint_patch.relay import main

if __name__ == '__main__':
    raise SystemExit(main())
