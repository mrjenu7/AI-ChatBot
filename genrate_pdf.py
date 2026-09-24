#!/usr/bin/env python3
import sys
from pathlib import Path

backend_script = Path(__file__).resolve().parent / "backend" / "genrate_pdf.py"
exec(backend_script.read_text(encoding="utf-8"))
