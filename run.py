"""Run archspec from the plugin folder, without installing the package:

    python "${CLAUDE_PLUGIN_ROOT}/run.py" {init|view|check|walkthrough} [options]
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # this copy wins over any pip-installed one
os.environ["ARCHSPEC_PLUGIN"] = "1"

try:
    import ruamel.yaml  # noqa: F401
except ImportError:
    sys.exit("archspec needs one Python library. Install it once with:\n"
             "    python -m pip install ruamel.yaml")

from archspec.__main__ import main  # noqa: E402

sys.exit(main())
