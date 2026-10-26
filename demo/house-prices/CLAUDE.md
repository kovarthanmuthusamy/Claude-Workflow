<!-- archspec:start (managed by `archview init`; rerun it to update this section) -->
## Architecture spec (architecture.yaml)

`architecture.yaml` is the contract for this project's structure. The user reviews it as a
diagram (`/archspec:view`) before code is written, and may edit it there.

### Workflow
1. **Plan.** Before implementing a feature, add or update its spec entries with
   `status: planned`. Then stop and tell the user it is ready to review in the viewer.
   Do not write code until the user says to go ahead.
2. **Build.** Re-read architecture.yaml first (the user may have edited it) and build
   against it as it is now.
3. **Keep it in step.** When you create or change code that has a node, update that node
   in the same step: `status: built`, `signature`, and `purpose`/`explain` if the logic
   changed. A built node whose spec changed but whose code is not updated yet is `changed`.
4. **Check.** Run the spec check (the `archspec:check` skill, or `python -m archspec check`
   where the package is pip-installed) and fix every error it reports.
5. **Patch, don't rewrite.** Edit only the affected entries; keep comments and unknown fields.

### What gets a node
- A function, class or method gets a node only if it is an entry point, is used from
  another script, or is on the main data path. Everything else goes in its parent's
  `helpers` list. Aim for at most ~6 nodes per script.
- One script = one pipeline stage. Write modular, one-stage-per-script code.
- A method gets its own node (id `Class.method`) only if data flows into or out of it;
  other methods go in the class's `methods` list.
- No variables, no implementation detail.

### Arrows
- `edges` are data flow, not calls. `from`/`to` use `script_id.node_id`.
- `data`: a short plain label of what travels ("raw customer table").
- `shape`: optional, for arrays ("X (N, 32) float32").

### Writing for the reader
The user is strong in math and statistics but not in programming.
- `purpose`: one plain line saying what the step achieves.
- `explain`: 2-4 sentences: what comes in, what is done to it, what goes out, and why the
  next step needs it. Describe the logic in data terms ("one row per customer",
  "rescaled so features are comparable"), never code terms (DataFrame, tensor, dict,
  kwargs, instance). No formulas.

### Format
```yaml
scripts:
  - id: preprocess                 # one script = one stage
    file: src/preprocess.py
    purpose: Turn raw exports into a clean feature table
    nodes:
      - id: build_features
        kind: function             # function | class | method | stage
        status: planned            # planned | built | changed
        purpose: Turn customer records into numbers the model can learn from
        explain: >-
          Takes the customer table and separates the answer column from the rest.
          Text categories become yes/no columns and numbers are rescaled so all
          features are comparable. Out comes one row of numbers per customer.
        signature: "build_features(df: pd.DataFrame) -> pd.DataFrame"  # required once built
        helpers: [_one_hot]
edges:
  - from: preprocess.build_features
    to: train.Trainer.fit
    data: features X and labels y
    shape: "X (N, 32) float32, y (N,)"
```
<!-- archspec:end -->
