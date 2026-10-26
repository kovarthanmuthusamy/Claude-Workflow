---
name: check
description: Compare architecture.yaml with the code and report drift (missing functions, changed signatures, broken arrows). Use after building or changing code that has nodes in architecture.yaml.
---

# Check the architecture spec against the code

Run from the project root:

```
python "${CLAUDE_PLUGIN_ROOT}/run.py" check
```

Exit code 1 means errors. For each error, fix the code or update the spec entry (status,
signature, purpose/explain), then run the check again until it reports `archcheck: OK`.
Warnings are suggestions (e.g. a function used from another script has no node).

When reporting to the user, describe each problem in plain words ("the spec says
`fit` takes the penalty, but the code doesn't yet"), not as raw checker output.
