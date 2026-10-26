"""Run archspec from the plugin folder, without installing the package:

    python "${CLAUDE_PLUGIN_ROOT}/run.py" {init|view|check|walkthrough} [options]

Kept free of newer syntax so that any Python can at least print why it can't run.
"""

import os
import sys

if sys.version_info < (3, 8):
    sys.exit("archspec needs Python 3.8 or newer; this is Python %d.%d (%s).\n"
             "Run it with a newer Python, e.g. python3 or py -3."
             % (sys.version_info[0], sys.version_info[1], sys.executable))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # this copy wins over any pip-installed one
os.environ["ARCHSPEC_PLUGIN"] = "1"

try:
    import ruamel.yaml  # noqa: F401
except ImportError:
    # Name this exact interpreter: with several Pythons installed, a plain
    # "pip install" often lands in a different one.
    sys.exit("archspec needs one Python library. Install it once with:\n"
             '    "%s" -m pip install ruamel.yaml' % sys.executable)

from archspec.__main__ import main  # noqa: E402

sys.exit(main())
