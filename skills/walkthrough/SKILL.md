---
name: walkthrough
description: Write a step-by-step walkthrough of the latest change for a reader who is strong in math but not in code, with real code, real diffs and one real worked example, then check understanding with questions.
argument-hint: "[short title]"
disable-model-invocation: true
---

# Walkthrough of the latest change

Title requested: $ARGUMENTS

Files changed since the last commit:
!`git status --short`

## Your job

Write `docs/walkthroughs/<YYYY-MM-DD>-<slug>.md` (slug from the title, or from the change)
so that a reader who is strong in math but not in code understands exactly what changed,
how it works, and what it does to the data.

### Rule 1: never type code or program output yourself

Place markers; the renderer fills them from the real project:

- `<!-- code: src/train.py:Trainer.fit -->` current source of a function, class or method
  (`<!-- code: path -->` for a whole short file)
- `<!-- diff: src/train.py -->` what changed in that file since the last commit
- `<!-- run: python docs/walkthroughs/<slug>_example.py -->` a command's real output

Then fill them by running, from the project root:

```
python "${CLAUDE_PLUGIN_ROOT}/run.py" walkthrough docs/walkthroughs/<file>.md
```

### Rule 2: structure (the reader's attention is the budget)

The explanation must be readable without opening any code. Code is supporting evidence, so
it goes inside collapsed `<details>` blocks; only the few key lines are quoted in the prose.

1. **In one paragraph**: what the change does and why, in plain words.
2. **Step by step**: follow the data in order. For each step: a plain-words heading, 2-5
   sentences on the logic (data/math terms), then the 1-3 key lines explained in words
   ("`if val_loss < best_loss`: keep these weights only if they are the best so far").
   Put the `code` marker for the changed function inside
   `<details><summary>Code: name</summary>` ... `</details>` (blank line after the summary
   line). Use function-level markers (`path:Name`), never whole files.
3. **Worked example** (the most important section): write a small script
   `docs/walkthroughs/<slug>_example.py` that pushes a tiny, concrete input (a few customers
   or a small array, fixed seed) through the changed steps and prints labelled intermediate
   values and shapes. Choose the input so the new behaviour actually shows. Show the output
   with a `run` marker (visible), put the script's `code` marker inside `<details>`, then
   explain the printed numbers in words.
4. **What changed**: one bullet per changed file in plain words, followed by a single
   `<details><summary>Exact changes</summary>` block holding the `diff` markers for code
   files only (skip architecture.yaml and generated files).
5. **Check your understanding**: 3 short questions about behaviour (e.g. "what happens if
   the validation loss never improves?"), each answer inside
   `<details><summary>Answer</summary> ... </details>`.

Target: the visible (not collapsed) part should read in about 5 minutes.

### Rule 3: verify against reality

After rendering, read the rendered file. If any real output contradicts your explanation,
fix the explanation (or, if it reveals a bug, tell the user) and render again.

### Rule 4: finish

Keep prose under ~150 lines. Then give the user the file path, ask the **first** question in
chat, wait for their answer, and respond to it (confirm, or correct with reference to the
walkthrough).
