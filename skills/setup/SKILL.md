---
name: setup
description: Set up the current project for the archspec workflow (architecture.yaml, CLAUDE.md rules, the plan/recap style) and open the diagram.
disable-model-invocation: true
---

# Set up archspec in this project

1. Run this in the project root:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/run.py" init
   ```

   `python` stands for whichever Python 3.8+ command this machine has: try `python3`, then
   `python`, then `py -3` (Windows), and keep using the first one that works. Nothing needs
   to be installed with pip. If no Python works at all, tell the user to install one from
   python.org and stop.

2. Start the diagram viewer as a **background** command (it keeps running while you work):

   ```
   python "${CLAUDE_PLUGIN_ROOT}/run.py" view
   ```

   It opens the browser and prints its address.

3. Tell the user in at most five short lines:
   - it's set up, and the diagram is open at <address>;
   - from now on: ask for a feature, Claude plans first, review the plan in the diagram,
     say "go ahead", get a recap; `/archspec:walkthrough` explains a change in depth;
   - if init said it turned on the output style: it starts with the next Claude Code
     session (or right away via `/output-style` → archspec:Explain as you go). If init
     said it kept another style, pass that on.

4. If the project already has Python code and `architecture.yaml` has no scripts yet, offer
   to map the existing code into the diagram, following the rules just added to CLAUDE.md.
   Don't start until the user agrees.
