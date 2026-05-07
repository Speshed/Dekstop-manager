# Update Memory

Check whether the project architecture has changed and update the navigation map if needed.

## Steps

1. **Check for structural changes.**
   Compare the current state of the repository against `docs/project-architecture.md`:

   - Are there new top-level folders not listed in section 3?
   - Have entrypoints changed? (new scripts, removed scripts, moved `main.py`)
   - Have API contracts changed? (new endpoints in `request_specs.py`, changed payloads)
   - Have sync architecture or state file paths changed?
   - Have new modules been added to `larix_nexus/ui/`, `larix_nexus/utils/`, `larix_nexus/sync/`?
   - Have new dependencies appeared? (new imports in key files)
   - Have tests been added or removed?
   - Have new config/env variables been introduced?
   - Has `.cursor/` structure changed?

2. **Check for stale information.**
   Verify that the following in `docs/project-architecture.md` are still accurate:
   - Endpoint list in section 4 matches `larix_nexus/api/request_specs.py`
   - UI inject-modules list in section 5 matches `larix_nexus/ui/__init__.py`
   - External libraries list in section 7 matches actual imports
   - Env variables in section 9 match `larix_nexus/constants.py` and actual usage
   - File path references are valid (files exist at stated locations)

3. **Update `docs/project-architecture.md` if needed.**
   If structural changes are found:
   - Update the specific section(s) affected
   - Keep the format: concise, navigation-first, not exhaustive tree
   - Maintain all 14 sections
   - Add new open questions to section 14
   - Do NOT turn the file into a full file tree dump
   - Do NOT remove existing content unless it is provably obsolete

4. **If no changes are needed**, output:
   ```
   Architecture map is up to date. No changes required.
   ```

5. **If changes are made**, output a brief summary:
   ```
   Updated docs/project-architecture.md:
   - Section X: <what changed>
   - Section Y: <what changed>
   - Section 14: added open question about Z
   ```

6. **Do NOT modify application source code.**
   This command is for documentation maintenance only.

7. **Do NOT reveal secrets.**
   Never output contents of `.env`, keyring values, tokens, passwords, or auth files.