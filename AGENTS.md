# AGENTS.md

## Project Overview

SecureCRT Tools is a collection of Python scripts for automating Cisco network-device workflows from SecureCRT.

The docs are the best guide to intended behavior. Read `CODEBASE_MAP.md` and the relevant files in `docs/source/` before changing scripts.

Target runtime:

- Python 3.13.4, 64-bit
- SecureCRT 9.7.2, x64 build 3858

Verify runtime behavior in that target before considering SecureCRT-facing changes production-ready.

## Repository Layout

- `README.rst`: user-facing overview and usage guide.
- `CODEBASE_MAP.md`: docs-led architecture and script map.
- `docs/source/`: authoritative Sphinx documentation source.
- `docs/`: generated HTML documentation.
- `s_*.py`: single-device scripts, run from an already-connected tab.
- `m_*.py`: multi-device scripts, run from a disconnected tab with a device CSV.
- `import_sessions_from_csv.py`: no-device saved-session import utility.
- `get_python_info.py`: SecureCRT Python version/path helper.
- `securecrt_tools/`: shared framework code.
- `textfsm-templates/`: TextFSM parser templates.
- `templates/`: starter scripts and example CSV files.
- `mac_list/`: MAC vendor CSV data.

## Main Entry Points

- Single-device workflows: `s_*.py`
- Multi-device workflows: `m_*.py`
- Session import workflow: `import_sessions_from_csv.py`
- Runtime check: `get_python_info.py`

Core modules:

- `securecrt_tools/scripts.py`: `Script`, `CRTScript`, `DebugScript`
- `securecrt_tools/sessions.py`: `Session`, `CRTSession`, `DebugSession`
- `securecrt_tools/settings.py`: `SettingsImporter`
- `securecrt_tools/utilities.py`: parsing, CSV, sorting, and naming helpers

## Build, Run, Test, Lint

Run in SecureCRT:

```text
Scripts -> Run -> select script
```

Single-device scripts:

```text
Connect to device first, then run s_*.py
```

Multi-device scripts:

```text
Start from a disconnected tab, then run m_*.py
```

Local debug mode:

```bash
python s_some_script.py
```

Docs build:

```bash
cd docs
make html
```

Tests: Unknown. No automated test suite was found.

Lint: Unknown. No lint config was found.

Dependencies: Unknown. No `requirements.txt` or `pyproject.toml` was found.

## Coding Conventions

- Preserve SecureCRT script headers:
  - `# $language = "python"`
  - `# $interface = "1.0"`
- Preserve launch patterns:
  - SecureCRT mode: `__name__ == "builtins"`
  - local debug mode: `__name__ == "__main__"`
- Treat `docs/source/` as authoritative for intended behavior.
- If docs and code disagree, call out the mismatch before changing behavior.
- Reuse `securecrt_tools/` helpers instead of duplicating framework logic.
- Reuse single-device script logic from multi-device wrappers where that pattern exists.
- Use `script.get_template()` for TextFSM template paths.
- Use `session.create_output_filename()` for output filenames.
- Keep changes narrowly scoped.
- Do not add third-party dependencies without approval.
- Keep Python 3.13.4 and SecureCRT 9.7.2 compatibility in mind.

## Known Risks

- `README.rst` says SecureCRT 9.x was unsupported when written; verify against SecureCRT 9.7.2.
- Many exception paths use `e.message`, which is not valid for normal Python 3 exceptions.
- Some code mixes binary file modes with text/CSV APIs.
- `_TODO_AireOS.py` is tracked but not valid Python.
- `m_cdp_to_csv.py` reads proxy settings but does not pass `proxy=proxy` to `script.connect()`.
- Config-changing scripts can push commands and save device configs.
- `send_config_commands()` has limited error checking and assumes prompt behavior.

## Avoid Modifying Without Approval

- `settings/`: user/runtime settings, gitignored.
- `ScriptOutput/`: generated script output, gitignored.
- `docs/`: generated HTML docs.
- `securecrt_tools/textfsm.py`: bundled third-party TextFSM code.
- `securecrt_tools/ipaddress.py`: bundled compatibility module.
- `securecrt_tools/manuf.py` and `securecrt_tools/manuf`: bundled MAC/OUI helper.
- `mac_list/mac_vendors_list.csv`: vendor data.
- `textfsm-templates/`: parser changes can affect many scripts.
- Config-changing scripts:
  - `s_add_global_config.py`
  - `m_add_global_config.py`
  - `s_update_dhcp_relay.py`
  - `m_update_dhcp_relay.py`
  - `s_update_interface_desc.py`
  - `m_update_interface_desc.py`

## Safe Read-Only Commands

```bash
git status --short
git ls-files
find . -maxdepth 3 -type f
find . -maxdepth 2 -type d
grep -RIn "pattern" --include='*.py' .
sed -n '1,220p' README.rst
sed -n '1,220p' CODEBASE_MAP.md
sed -n '1,220p' docs/source/securecrt_tools.rst
sed -n '1,220p' docs/source/single_device_scripts.rst
sed -n '1,220p' docs/source/multi_device_scripts.rst
python --version
```

Prefer `rg` over `grep` if available. Verify availability before use.

Read-only syntax check:

```bash
python - <<'PY'
import ast, pathlib
for path in pathlib.Path('.').rglob('*.py'):
    if any(part in {'.git', '__pycache__', '.venv', 'build', 'dist'} for part in path.parts):
        continue
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
print('parse ok')
PY
```

Note: `_TODO_AireOS.py` is expected to fail unless fixed or excluded.

## Verification Steps

Before considering work complete:

- Read `CODEBASE_MAP.md`.
- Read relevant docs in `docs/source/`.
- Read the relevant script and shared framework modules.
- Check for user changes with `git status --short`.
- For Python changes, run a syntax/AST check or explain why not run.
- For docs changes, update `docs/source/`; rebuild `docs/` only if requested.
- For TextFSM changes, validate with representative command output.
- For SecureCRT behavior changes, validate in SecureCRT 9.7.2 with Python 3.13.4.
- For config-changing behavior, test check mode first and inspect generated commands.
- For multi-device behavior, test with a small CSV and review failure logs.

## Definition Of Done

A task is done when:

- Requested changes are complete.
- Existing script/framework patterns are preserved.
- Relevant docs and `CODEBASE_MAP.md` were considered.
- Appropriate verification was run, or clearly marked not run.
- Runtime compatibility risks are called out.
- No unrelated files were modified.
