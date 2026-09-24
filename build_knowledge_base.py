#!/usr/bin/env python3
import sys
from pathlib import Path

# Add backend to path and execute backend/build_knowledge_base.py
backend_script = Path(__file__).resolve().parent / "backend" / "build_knowledge_base.py"
exec(backend_script.read_text(encoding="utf-8"))
