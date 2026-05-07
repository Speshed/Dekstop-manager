# Start Task

Start a new task by reading the architecture map and producing a focused plan.

## Steps

1. **Read the architecture map.**
   Read `docs/project-architecture.md` in full. This is the primary navigation file for the entire project.

2. **Determine the subsystem.**
   Based on the task description, identify which subsystem(s) the task touches:

   | Subsystem keyword | Section in architecture map |
   |-------------------|-----------------------------|
   | login, auth, token, API, credentials | Section 4 — Backend / API |
   | project, folder, tree, navigate | Section 5 — Frontend / UI |
   | table, file list, columns, sort, filter | Section 5 — Frontend / UI |
   | upload, download, drag, drop | Section 5 + Section 4 |
   | sync, conflict, tombstone, delete | Section 6 — Agent / Executor |
   | notification, alarm, subscribe | Section 2 navigation row |
   | theme, dark, light, style, QSS | Section 5 — Frontend / UI |
   | PDF, compare, diff | Section 2 navigation row |
   | telegram, bot | Section 2 navigation row |
   | build, package, EXE, PyInstaller | Section 2 navigation row |
   | docs, architecture, memory | Section 10 — Cursor / LLM Memory |
   | config, env, settings, keyring | Section 9 — Config / Environment |

3. **Select the navigation route.**
   From section 2 ("Быстрая навигация") and section 11 ("Типовые маршруты работы"), get:
   - Which file(s) to read first
   - Which file(s) are likely to be modified
   - What tests/checks to run

4. **Read only relevant files.**
   Do NOT scan the entire repository. Read only:
   - The navigation anchor files from the route
   - Files directly mentioned in the task
   - Files imported by those files (one level deep)

   Skip: `__pycache__/`, `*.pyc`, `*.log`, `*.db`, `build/`, `dist/`, `icon/` (unless task is about icons).

5. **Produce a start-task report.**

   Output the following concise report:

   ```
   ## Task Analysis

   **Project:** Larix Nexus Desktop (Python/PySide6 desktop app for Larix Platform)

   **Subsystem:** <identified subsystem>

   **Files to read first:**
   1. <file1> — <reason>
   2. <file2> — <reason>

   **Files likely to modify:**
   1. <file1> — <reason>
   2. <file2> — <reason>

   **Risks:**
   - <list each risk from architecture map section 3 "Риск" column>
   - <any additional risk specific to this task>

   **Checks to run after changes:**
   - <e.g., python main.py, --dry-run, STYLE_REGRESSION_CHECKLIST, manual test>
   ```

6. **Do NOT modify code at this stage.**
   The start-task command is for orientation only. Wait for explicit instruction to edit files.

7. **Do NOT reveal secrets.**
   Never output contents of `.env`, keyring values, tokens, passwords, or auth files.