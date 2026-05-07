# Review Diff

Review staged/unstaged changes against the declared task scope and the architecture map.

## Steps

1. **Identify the declared task scope.**
   Ask the user or refer to the task description:
   - What subsystem was the task about?
   - Which files were expected to change?

2. **Read the architecture map.**
   Read `docs/project-architecture.md` to understand:
   - Which subsystem each changed file belongs to
   - The risk level for each file (from the "Риск" column in section 3)
   - Whether the files are in the monolithic high-risk zone (section 5, `main_window.py`, `manager.py`, `theme.py`, `PDF_Compare.py`, `client.py`)

3. **Get the diff.**
   Run `git diff` and/or `git diff --staged` to see all changes.

4. **Classify each changed file.**

   For each file in the diff, categorize it:

   | Category | Meaning |
   |----------|---------|
   | **Target** | File is in the declared task subsystem — expected change |
   | **Adjacent** | File is closely related but not part of the original task — acceptable but note it |
   | **Off-target** | File is outside the declared task subsystem — unexpected, flag it |
   | **High-risk** | File is in the monolithic high-risk zone (rule 4) — needs extra scrutiny |
   | **Generated/Runtime** | File is a runtime artifact that should not be committed — block it |

5. **Check for secrets and runtime artifacts.**
   Scan the diff for:
   - `.env` file contents
   - Hardcoded tokens, passwords, API keys
   - `__pycache__/`, `*.pyc`, `*.pyo`
   - `*.log`, `*.db`, `*.sqlite`
   - `build/`, `dist/`, `Nexus_downloads/`
   - `nul`, `*.nul`
   - Any file that should be in `.gitignore` but isn't

6. **Produce the review report.**

   ```markdown
   ## Diff Review

   **Declared task:** <task description>

   ### Target changes (expected)
   | File | Change summary | Risk level |
   |------|---------------|------------|
   | <file> | <what changed> | <low/medium/high> |

   ### Adjacent changes (related but not originally scoped)
   | File | Change summary | Why it may be needed |
   |------|---------------|---------------------|
   | <file> | <what changed> | <reason> |

   ### Off-target changes (unexpected)
   | File | Change summary | Concern |
   |------|---------------|---------|
   | <file> | <what changed> | <why this is risky> |

   ### Secrets / Runtime artifacts
   - <none found / list any detected>

   ### High-risk zone changes
   - <list any changes to main_window.py, manager.py, theme.py, PDF_Compare.py, client.py>

   ### Architecture map updates needed?
   - <Yes/No — if yes, which sections>

   ### Recommended checks
   - <e.g., python main.py, --dry-run, STYLE_REGRESSION_CHECKLIST, manual GUI test>
   ```

7. **Do NOT auto-fix.**
   This command is for review only. Do not make changes unless explicitly asked.
   Flag issues and let the user decide how to proceed.

8. **Do NOT reveal secrets.**
   Never output the actual content of `.env`, keyring values, tokens, or passwords found in diffs.
   If a secret is detected, report only: "detected potential secret in <file>:<line>, value not disclosed."