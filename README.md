# Larix Nexus Desktop

Larix Nexus Desktop is a Windows desktop client for working with Larix Nexus
projects, folders, documents and document versions.

## Features

- browse projects, folders and documents;
- upload, download, copy and move files;
- work with document versions;
- compare PDF versions;
- synchronize local folders and receive notifications where configured.

## Requirements

- Windows;
- Python 3.13 or newer (the current test environment uses Python 3.13);
- the Python packages imported by the application and test suite.

The repository does not currently contain a `requirements.txt` or
`pyproject.toml`; a dependency manifest should be added before publishing a
reproducible installation workflow.

## Installation and launch

Create and activate a virtual environment, install the project's dependencies,
then run:

```powershell
python main.py
```

## Testing

```powershell
pytest -q larix_nexus/tests
```

## Building

The Windows build is configured by `Larix_Nexus.spec` and started with:

```powershell
.\build.bat
```

PyInstaller output is written to `dist/` and is intentionally not committed.

## Project structure

- `larix_nexus/` — application source code;
- `larix_nexus/tests/` — automated tests;
- `icon/` — interface resources;
- `telegram_bot/` — the supported Telegram integration;
- `main.py` — application entry point;
- `Larix_Nexus.spec` — PyInstaller configuration.

## Local materials

Documentation, screenshots, HAR traces, downloads, logs, test data and build
results are local working materials and are ignored by Git. Keep such files
outside the repository when possible; generated artifacts belong in local
`artifacts/` subdirectories and test fixtures in local `test-data/`.
