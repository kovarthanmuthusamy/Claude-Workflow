---
name: view
description: Open the architecture diagram of this project in the browser (editable, with a live view of Claude's activity).
disable-model-invocation: true
---

# Open the architecture diagram

Start the viewer as a **background** command (it keeps running while you work), from the
project root:

```
python "${CLAUDE_PLUGIN_ROOT}/run.py" view
```

It opens the browser itself and prints the address (`http://127.0.0.1:<port>/`). Give the
user that address in one line, and mention: cards glow while you read or edit them; edits
made in the diagram are saved back to architecture.yaml, and you build against them.

If it reports that architecture.yaml is missing, suggest `/archspec:setup` first. If a
Python library is missing, run the install command it prints and start it again.
