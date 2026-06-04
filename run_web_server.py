# -*- coding: utf-8 -*-
"""Start the travel planner web server without opening a browser window."""
from pathlib import Path
import sys
import traceback

PROJECT_DIR = Path(__file__).resolve().parent
LOG_FILE = PROJECT_DIR / "web_server_runtime.log"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import web_app


if __name__ == "__main__":
    try:
        LOG_FILE.write_text("Starting web server on http://127.0.0.1:7860\n", encoding="utf-8")
        web_app.run(open_browser=False)
    except BaseException:
        LOG_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        raise
