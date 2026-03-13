# Style Regression Checklist

Use this checklist after changing shared style tokens or QSS generation.

## Main App (larix_nexus)

- Start app in light theme.
- Verify primary/secondary buttons states: normal, hover, pressed, disabled.
- Verify chip buttons (`chip`, `chipSmall`) states and rounded corners.
- Verify menus (`popupMenu`, `downloadMenu`, `columnsMenu`, `nikHeaderMenu`) hover/pressed colors.
- Verify comboboxes (`projectsCombo`, workspace combo) popup borders and selected rows.
- Verify scrollbars (horizontal/vertical) in main views and inside menus.
- Verify calendar arrows, date hover/selection, and header text.

## Dark Theme

- Toggle dark theme and repeat checks above.
- Verify icon tinting (white arrows/check marks where expected).
- Verify no unresolved placeholders in QSS-driven image URLs.

## PDF Compare

- Open PDF Compare in light theme and verify button/menu/scrollbar behavior.
- Toggle dark theme and verify PDF Compare keeps expected local overrides.
- Verify navigation arrows and combobox arrows are visible in both themes.

## Quick Smoke Actions

- Open header filter menu and toggle checkbox items.
- Open user menu and columns menu.
- Trigger progress UI and cancel buttons.
- Run one file upload/download cycle to ensure no style-related runtime errors.
