# archspec

**Understand what Claude builds in your Python/ML projects**, without reading all the code.

A Claude Code plugin for people who know the math but don't want to trace code. It adds:

- **A live, editable diagram** of your project's functions and how data flows between
  them, written in plain language. Claude plans new work into the diagram first, and you
  review and edit it before any code is written. While Claude works, the cards it is
  reading or editing light up.
- **An output style, "Explain as you go"**: a short plan with the real decisions before a
  task, and a recap after it (what changed, how data flows now, what was tested and what
  wasn't, what to watch out for).
- **`/archspec:walkthrough`**: after a change, a short document built around one worked
  example with real numbers from your code, ending with questions to check your
  understanding.

The approach is based on research showing that understanding AI-written code comes from
actively questioning it, not from reading more output
([Anthropic, 2026](https://www.anthropic.com/research/AI-assistance-coding-skills)).

![The diagram while reviewing a plan](demo/house-prices/docs/demo/1-plan-review.png)

## Install (once per computer)

**You need:** [Claude Code](https://docs.claude.com/en/docs/claude-code), Python 3.10 or
newer available as `python`, and git.

1. Install the one Python library the tool uses:

   ```
   python -m pip install ruamel.yaml
   ```

2. Start Claude Code (`claude`) in any folder and type:

   ```
   /plugin marketplace add kovarthanmuthusamy/Claude-Workflow
   /plugin install archspec@archspec
   ```

   The first line tells Claude Code where to find the plugin (this GitHub repo); the
   second installs it. You can also do both from a normal terminal:

   ```
   claude plugin marketplace add kovarthanmuthusamy/Claude-Workflow
   claude plugin install archspec@archspec
   ```

3. Restart Claude Code. Type `/archspec` and you should see `setup`, `view`, `check` and
   `walkthrough` in the list.

The plugin is installed for your user, so it is available in every project. Nothing is
copied into a project until you run `/archspec:setup` there.

## Set up a project (once per project)

Open Claude Code in the project folder and:

1. Run **`/archspec:setup`**. It creates `architecture.yaml` (the diagram, empty at first)
   and adds the workflow rules to the project's `CLAUDE.md`, so Claude knows to plan into
   the diagram and keep it up to date. If the project already has code, Claude offers to
   map it into the diagram; say yes or no.
2. Run **`/output-style`** and pick **archspec:Explain as you go**. From now on Claude
   writes a short plan before a task and a recap after it. (The name includes the
   `archspec:` prefix.)
3. Run **`/archspec:view`**. Claude starts the viewer and gives you a link such as
   `http://127.0.0.1:8765`. Keep that browser tab open while you work.

## Everyday use

1. **Ask** for a feature in your own words, e.g. *"Add ridge regularisation and choose the
   penalty on apartments the model didn't train on."* Claude replies with a plan (goal,
   approach, the decisions it needs from you) and adds the planned steps to the diagram.
   It doesn't write code yet.
2. **Review** in the browser tab. Planned steps have a dashed outline, changed steps are
   amber. Click a card or arrow to edit it if you want something different; your edits
   are saved to `architecture.yaml` and Claude follows them.
3. **Approve** ("go ahead", or tell it what to change). Claude builds it, checks the
   diagram against the code, and ends with a recap: what changed, how data flows now,
   what was tested and what wasn't, and what to watch out for. While it works, the cards
   it is reading or editing light up in the browser.
4. **Understand** with **`/archspec:walkthrough`** when the change matters. Claude writes
   a short document in `docs/walkthroughs/` built around one worked example with real
   output from your code, and asks you a question to check your understanding.

Skip steps for small changes: a typo or a one-line fix needs none of this.

| Command | What it does |
|---|---|
| `/archspec:setup` | Add `architecture.yaml` and the workflow rules (in `CLAUDE.md`) to the project |
| `/archspec:view` | Open the diagram in the browser (editable, with Claude's live activity) |
| `/archspec:check` | Compare the diagram with the code; Claude also runs this after building |
| `/archspec:walkthrough` | Explain the latest change with a worked example |

## Update or remove

```
claude plugin marketplace update archspec     # fetch the latest version from GitHub
claude plugin update archspec@archspec        # then restart Claude Code
claude plugin uninstall archspec@archspec     # remove it
```

Removing the plugin leaves your projects' `architecture.yaml` and `CLAUDE.md` in place.

## If something doesn't work

| Problem | Fix |
|---|---|
| `/archspec:...` commands don't appear | Restart Claude Code; check `claude plugin list` shows archspec as enabled |
| "Explain as you go" isn't in `/output-style` | Look for **archspec:Explain as you go** (with the prefix); restart after installing |
| "No module named ruamel" | `python -m pip install ruamel.yaml` |
| `python` not found | Install Python 3.10+ and make sure `python --version` works in a terminal |
| The browser shows nothing new | Reload the tab; if the viewer was stopped, run `/archspec:view` again |
| Adding the marketplace fails with "Filename too long" (Windows) | Run `git config --global core.longpaths true` and try again |

See [`demo/house-prices/DEMO.md`](demo/house-prices/DEMO.md) for a complete run: a real
plan, recap and walkthrough on a small house-price model.

## The diagram file

`architecture.yaml` sits in your project root. Claude keeps it up to date; you can edit it
in the viewer or by hand.

```yaml
scripts:
  - id: prepare
    file: src/prepare.py
    nodes:
      - id: make_features
        kind: function            # function | class | method | stage
        status: built             # planned | built | changed
        purpose: Rescale the four apartment properties so they are comparable
        explain: >-
          Each property is shifted and divided so it has mean 0 and spread 1, using the
          training apartments only. Out comes X (4 numbers per apartment) and the prices y.
        signature: "make_features(df, scaling=None) -> tuple"
edges:
  - from: prepare.make_features
    to: train.fit_linear
    data: rescaled properties and prices
    shape: "X (180, 4), y (180,)"
```

## Without Claude Code (CI, pre-commit)

The same tool is a pip package:

```
python -m pip install git+https://github.com/kovarthanmuthusamy/Claude-Workflow
python -m archspec check      # exit code 1 if the diagram and the code disagree
python -m archspec view
```

## Development

```
python -m pip install -e ".[dev]"
python -m pytest
claude --plugin-dir .          # try the plugin from this checkout
```

The viewer's browser libraries are vendored in `archspec/static/vendor/` (no Node.js
needed); `tools/fetch_vendor.py` re-downloads them.
