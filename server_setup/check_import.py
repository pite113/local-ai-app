# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"C:\local-ai-app")
try:
    import app.main
    print("IMPORT_OK")
except Exception:
    import traceback
    traceback.print_exc()
