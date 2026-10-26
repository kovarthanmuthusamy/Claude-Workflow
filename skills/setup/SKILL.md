---
name: setup
description: Set up the current project for the archspec workflow (architecture.yaml + CLAUDE.md rules).
disable-model-invocation: true
---

# Set up archspec in this project

Run this in the project root and show the user its output:

```
python "${CLAUDE_PLUGIN_ROOT}/run.py" init
```

`python` stands for whichever Python 3.8+ command this machine has: try `python3`, then
`python`, then `py -3` (Windows), and keep using the first one that works.

If it says a Python library is missing, run the install command it prints (it names the
exact Python to install into), then run init again.

Then tell the user, briefly:

1. Turn on the plan/recap style once for this project: `/output-style` and pick
   **archspec:Explain as you go**.
2. Open the diagram any time with `/archspec:view`.
3. Each feature: ask -> review the plan in the diagram -> "go ahead" -> read the recap ->
   `/archspec:walkthrough` when they want to understand it in depth.

If the project already has Python code and `architecture.yaml` has no scripts yet, offer to
map the existing code into it, following the rules that were just added to CLAUDE.md. Do not
start mapping until the user agrees.
