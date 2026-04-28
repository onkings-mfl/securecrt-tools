# CODEBASE_MAP

## Purpose

This repository is a SecureCRT Python script collection for automating Cisco network-device workflows. The documentation is the best starting point for understanding the project because it explains the user-facing script model, script categories, settings, and expected workflows.

Use this map as a bridge between the docs and the implementation. Start with the docs to understand what each script does, then use the source references below to understand how the scripts work together.

## Target Runtime

Planned deployment target:

- Python 3.13.4, 64-bit
- SecureCRT 9.7.2, x64 build 3858

Important compatibility note: the current `README.rst` says SecureCRT 9.x was not working at the time it was written. Treat that as stale or unresolved until these scripts are validated against SecureCRT 9.7.2 and Python 3.13.4.

## Start With The Docs

Primary reading path:

1. `README.rst`
   - Explains the purpose of the project.
   - Explains single-device vs multi-device scripts.
   - Explains runtime settings and output behavior.
   - Explains jumpbox/proxy usage.

2. `docs/source/scripts.rst`
   - Top-level script catalog.
   - Links to single-device, multi-device, and no-device script groups.

3. `docs/source/single_device_scripts.rst`
   - Lists scripts intended to run against an already-connected SecureCRT session.

4. `docs/source/multi_device_scripts.rst`
   - Lists scripts that import a device CSV and connect to devices one at a time.
   - Documents the device-list CSV format and common optional columns.

5. `docs/source/no_device_scripts.rst`
   - Lists scripts that only interact with SecureCRT itself.

6. `docs/source/securecrt_tools.rst`
   - Explains the shared framework modules and how they fit together.

7. `docs/source/writing_intro.rst`
   - Explains the design intent behind the `Script` and `Session` classes.
   - Explains SecureCRT mode vs local debug mode.

8. `docs/source/textfsm_note.rst`
   - Explains why TextFSM is used to parse semi-structured CLI output.

The generated HTML docs in `docs/` mirror the Sphinx source docs and can be opened locally through `docs/index.html`.

## High-Level Architecture

The codebase is organized around three script types:

- Single-device scripts: `s_*.py`
- Multi-device scripts: `m_*.py`
- No-device SecureCRT utility scripts: currently `import_sessions_from_csv.py`

The shared implementation lives in `securecrt_tools/`.

The important framework split is:

- `securecrt_tools.scripts`
  - Represents the running script and its interaction with the SecureCRT application.
  - Handles settings bootstrap, message boxes, prompts, file dialogs, device CSV import, connection creation, disconnection, and saved-session creation.

- `securecrt_tools.sessions`
  - Represents a connected or simulated device session.
  - Handles prompt discovery, hostname detection, OS detection, terminal setup/restore, command output capture, config push, save, disconnect, and local debug simulation.

- `securecrt_tools.settings`
  - Loads and updates `settings/settings.ini`.
  - Creates or repairs settings using `securecrt_tools/default_settings.ini`.

- `securecrt_tools.utilities`
  - Provides reusable parsing and output helpers.
  - Wraps TextFSM parsing.
  - Writes CSV files.
  - Normalizes interface names, route protocol names, ranges, sorting, and path-safe filenames.

This split lets top-level scripts stay small: most scripts collect user choices, validate the device OS, send one or more commands, parse the output, and write files.

## Repository Layout

- `README.rst`
  - Main user-facing introduction and usage guide.

- `LICENSE`
  - Apache License 2.0.

- `s_*.py`
  - Single-device scripts.
  - Run from an existing SecureCRT tab that is already logged into a device.

- `m_*.py`
  - Multi-device scripts.
  - Run from a disconnected SecureCRT tab.
  - Import a device CSV and connect to each device sequentially.

- `import_sessions_from_csv.py`
  - No-device utility for creating SecureCRT saved sessions from CSV.

- `get_python_info.py`
  - Small SecureCRT helper that displays the bundled Python version and `sys.path`.

- `_TODO_AireOS.py`
  - Incomplete notes file for future AireOS work.
  - This file currently does not parse as Python.

- `securecrt_tools/`
  - Shared framework code and bundled helper modules.

- `textfsm-templates/`
  - TextFSM templates for Cisco IOS, NXOS, ASA, and AireOS command output.

- `templates/`
  - Starter scripts and example CSV files.

- `docs/source/`
  - Sphinx documentation source.

- `docs/`
  - Generated Sphinx HTML output.

- `mac_list/`
  - MAC vendor CSV data.

## Main Execution Model

### Single-Device Flow

Single-device scripts are launched from a SecureCRT tab that is already connected to a device.

```text
SecureCRT launches s_*.py
  -> script detects SecureCRT via __name__ == "builtins"
  -> script creates scripts.CRTScript(crt)
  -> CRTScript creates sessions.CRTSession for the current tab
  -> script gets the main session
  -> script calls session.start_cisco_session()
  -> CRTSession locks the tab and enables synchronous screen handling
  -> CRTSession discovers prompt, hostname, OS, enable state, terminal length/width
  -> script runs commands through get_command_output() or write_output_to_file()
  -> script optionally parses output with TextFSM
  -> script writes text or CSV output
  -> script calls session.end_cisco_session()
  -> CRTSession restores terminal settings and unlocks the tab
```

### Multi-Device Flow

Multi-device scripts are launched from a disconnected SecureCRT tab.

```text
SecureCRT launches m_*.py
  -> script creates scripts.CRTScript(crt)
  -> script checks that current tab is disconnected
  -> script.import_device_list() prompts for a device CSV
  -> missing passwords/enables may be prompted interactively
  -> script checks proxy settings
  -> script loops through each device
  -> script.connect() opens SSH2, SSH1, or Telnet
  -> per_device_work() starts a Cisco session and runs task logic
  -> script.disconnect() disconnects from the device
  -> failures are appended to a generated log file
```

Multi-device scripts process devices one at a time. The docs note that SecureCRT scripts do not provide true multi-threading, so parallelism is manual by splitting device CSV files and running scripts in multiple tabs.

### Local Debug Flow

Most top-level scripts also support direct local execution:

```text
python s_some_script.py
```

When run directly, scripts create `scripts.DebugScript` and `sessions.DebugSession` instead of SecureCRT-backed objects. Debug mode prompts for simulated device state and local files containing command output. This is meant for parsing and script-logic development, not full SecureCRT workflow validation.

## Core Framework Modules

### `securecrt_tools/scripts.py`

Important classes:

- `Script`
  - Abstract base for script execution context.
  - Loads settings.
  - Resolves output directories.
  - Initializes debug logging when enabled.
  - Provides common helpers such as `get_main_session()`, `validate_dir()`, `get_template()`, and `import_device_list()`.

- `CRTScript`
  - SecureCRT-backed implementation.
  - Wraps `crt.Dialog`, `crt.GetScriptTab()`, `ConnectInTab()`, and saved-session APIs.
  - Connects to devices over SSH2, SSH1, or Telnet.

- `DebugScript`
  - Local/debug implementation.
  - Simulates SecureCRT dialogs with console prompts.
  - Simulates connections without opening real network sessions.

Important exceptions:

- `ScriptError`
- `ConnectError`

### `securecrt_tools/sessions.py`

Important classes:

- `Session`
  - Abstract base for device sessions.
  - Provides shared filename creation and OS validation.

- `CRTSession`
  - SecureCRT-backed device session.
  - Wraps a SecureCRT tab/session/screen.
  - Handles command sending, waiting for prompts, reading output, paging, terminal length/width, config mode, and save behavior.

- `DebugSession`
  - Local/debug implementation.
  - Prompts for files instead of sending commands to devices.

Important exceptions:

- `InteractionError`
- `UnsupportedOSError`

### `securecrt_tools/settings.py`

Important class:

- `SettingsImporter`
  - Loads default settings from `securecrt_tools/default_settings.ini`.
  - Loads user settings from `settings/settings.ini`.
  - Creates the settings file when requested.
  - Validates that required sections/options exist.
  - Rewrites settings to add missing defaults while preserving existing values.
  - Provides `get()`, `getboolean()`, `getint()`, `getlist()`, and `update()`.

### `securecrt_tools/utilities.py`

Important functions:

- `textfsm_parse_to_list()`
- `textfsm_parse_to_dict()`
- `list_of_lists_to_csv()`
- `list_of_dicts_to_csv()`
- `extract_system_name()`
- `short_int_name()`
- `long_int_name()`
- `normalize_protocol()`
- `expand_number_range()`
- `human_sort_key()`
- `remove_empty_or_invalid_file()`
- `path_safe_name()`

These helpers keep common parsing, CSV, interface-name, and filename logic out of individual scripts.

### Bundled Third-Party/Helper Modules

- `securecrt_tools/textfsm.py`
  - Bundled TextFSM implementation.

- `securecrt_tools/ipaddress.py`
  - Bundled IP address module for compatibility with SecureCRT Python environments.

- `securecrt_tools/manuf.py` and `securecrt_tools/manuf`
  - MAC manufacturer/OUI lookup support.

## Configuration

Default settings live in:

```text
securecrt_tools/default_settings.ini
```

User/runtime settings live in:

```text
settings/settings.ini
```

The `settings/` directory is intentionally gitignored because settings are user/environment-specific.

Important global settings:

- `output_dir`
- `date_format`
- `modify_term`
- `debug_mode`
- `use_proxy`
- `proxy_session`
- `response_timeout`

Important script-specific sections:

- `[add_global_config]`
- `[cdp_to_csv]`
- `[create_sessions_from_cdp]`
- `[document_device]`
- `[update_interface_desc]`
- `[update_dhcp_relay]`

Settings behavior:

- If `settings/settings.ini` is missing, the framework prompts the user to create it.
- If defaults gain new required settings, `SettingsImporter` can rewrite the local settings file while preserving existing values.
- Some scripts update settings after user prompts. For example, scripts with `show_instructions` can set that option to `False` if the user asks not to see the instructions again.

## Output Behavior

Most scripts write files under the configured `output_dir`. The default is:

```text
ScriptOutput
```

Filenames are usually built from:

- device hostname
- output description or command name
- timestamp from `date_format`
- extension such as `.txt` or `.csv`

`Session.create_output_filename()` handles filename construction and path-safe cleanup.

For large outputs, `get_command_output()` captures output through a temporary file, then reads it back into memory. This is intentional because the docs and code note that storing very large SecureCRT screen output directly in a variable can make SecureCRT slow or freeze.

## Device CSV Format

Multi-device scripts use `script.import_device_list()` and prompt the user to select a CSV.

Example:

```text
templates/sample_device_list.csv
```

Required columns:

- `Hostname`
- `Protocol`
- `Username`

Common optional columns:

- `Password`
- `Enable`
- `Proxy Session`

Behavior:

- Empty hostname rows are skipped.
- Empty protocol means the script may try SSH2, SSH1, then Telnet.
- Missing usernames can be replaced by a prompted default username.
- Missing passwords can be prompted per username and reused.
- Missing enable passwords can be replaced by a prompted default enable password.
- `Proxy Session` can override the global proxy session per device.

Some scripts support additional columns. For example, `m_document_device.py` supports a `Command List` column to choose a per-device command list from `[document_device]`.

## Proxy / Jumpbox Support

The docs explain two related patterns:

- Manual SecureCRT proxying by configuring a saved SecureCRT session as a firewall/proxy.
- Script-driven proxying through `use_proxy`, `proxy_session`, and the optional `Proxy Session` CSV column.

At runtime, multi-device scripts generally:

1. Read `Global.use_proxy`.
2. Read `Global.proxy_session`.
3. Check each device row for `Proxy Session`.
4. Pass `proxy=proxy` into `script.connect()`.

Known exception: `m_cdp_to_csv.py` reads proxy settings but currently does not pass `proxy=proxy` into `script.connect()`.

## TextFSM Templates

TextFSM templates live in:

```text
textfsm-templates/
```

`Script.get_template()` resolves templates relative to the repo root.

Template groups:

- AireOS:
  - `cisco_aireos_show_ap_summary.template`
  - `cisco_aireos_show_ap_config_general.template`
  - `cisco_aireos_show_ap_config_slot.template`
  - `cisco_aireos_show_advanced_txpower.template`
  - `cisco_aireos_show_ap_cdp_neighbors_detail_all.template`
  - `cisco_aireos_show_auth_list.template`
  - `cisco_aireos_show_interface_summary.template`
  - `cisco_aireos_show_interface_detailed.template`
  - `cisco_aireos_show_mobility_summary.template`
  - `cisco_aireos_show_wlan_summary.template`
  - `cisco_aireos_show_wlan_detail.template`

- ASA:
  - `cisco_asa_show_version.template`

- IOS:
  - `cisco_ios_show_etherchannel_summary.template`
  - `cisco_ios_show_interfaces.template`
  - `cisco_ios_show_interfaces_description.template`
  - `cisco_ios_show_interfaces_status.template`
  - `cisco_ios_show_ip_arp.template`
  - `cisco_ios_show_ip_eigrp_topology.template`
  - `cisco_ios_show_ip_route.template`
  - `cisco_ios_show_mac_addr_table.template`
  - `cisco_ios_show_run_helper.template`
  - `cisco_ios_show_version.template`
  - `cisco_ios_show_vlan.template`

- NXOS:
  - `cisco_nxos_show_interface.template`
  - `cisco_nxos_show_interface_description.template`
  - `cisco_nxos_show_interface_status.template`
  - `cisco_nxos_show_inventory.template`
  - `cisco_nxos_show_ip_arp_detail.template`
  - `cisco_nxos_show_ip_bgp.template`
  - `cisco_nxos_show_ip_eigrp_topology.template`
  - `cisco_nxos_show_ip_route.template`
  - `cisco_nxos_show_mac_addr_table.template`
  - `cisco_nxos_show_portchannel_summary.template`
  - `cisco_nxos_show_run_dhcp_relay.template`
  - `cisco_nxos_show_version.template`
  - `cisco_nxos_show_vlan.template`
  - `cisco_nxos_show_vpc.template`

- Cross-platform Cisco:
  - `cisco_os_show_cdp_neigh_det.template`
  - `cisco_os_show_run_desc.template`
  - `cisco_os_show_spanning-tree_root.template`

## Single-Device Scripts

Single-device scripts are launched from a SecureCRT tab that is already connected to a device. They usually call `session.start_cisco_session()`, run a focused task, then call `session.end_cisco_session()`.

### `s_save_output.py`

Prompts for one command, sends it to the connected device, and saves the output to a timestamped file.

### `s_save_running.py`

Saves the running configuration from a connected device.

Command selection depends on OS:

- ASA: `show run-config`
- IOS/NXOS: `show run`
- AireOS variants use `show run-config...` style commands.

### `s_document_device.py`

Runs a configured list of commands and writes each command output to a file.

The command list comes from `[document_device]` in `settings/settings.ini`. The script can select command lists by detected OS or prompt for a custom list if `prompt_for_custom_lists` is enabled.

This script is also used by `m_document_device.py`.

### `s_cdp_to_csv.py`

Captures `show cdp neighbors detail`, parses it with `cisco_os_show_cdp_neigh_det.template`, normalizes remote system names, and writes a CSV.

Supported OS:

- IOS
- NXOS

This script is also used by `m_cdp_to_csv.py`.

### `s_create_sessions_from_cdp.py`

Captures and parses CDP detail, then creates SecureCRT saved sessions for discovered neighbors.

Settings:

- `[create_sessions_from_cdp].folder`
- `[create_sessions_from_cdp].strip_domains`

Supported OS:

- IOS
- NXOS

### `s_arp_to_csv.py`

Captures ARP data and writes it to CSV.

Supported OS:

- IOS: `show ip arp`
- NXOS: `show ip arp detail`

Can prompt for a VRF and append the VRF to the command.

### `s_mac_to_csv.py`

Captures the MAC address table and writes it to CSV.

Supported OS:

- IOS
- NXOS

Uses `show mac address-table`, with a fallback to `show mac-address-table dynamic` for older IOS syntax.

### `s_vlan_to_csv.py`

Captures `show vlan brief`, parses VLAN data, normalizes VLAN port lists, and writes a CSV.

Supported OS:

- IOS
- NXOS

### `s_switchport_mapping.py`

Builds an endpoint mapping for a connected switch.

Inputs and collected data:

- Optional ARP CSV selected by the user.
- `show interface status`
- `show mac address-table`
- `show interface description`
- NXOS vPC data when applicable.

Output maps local switch ports to MAC addresses, vendors, descriptions, and optional IP addresses from ARP data.

Supported OS:

- IOS
- NXOS

### `s_interface_stats.py`

Captures interface statistics from `show interface`, parses only useful fields, and writes them to CSV.

Supported OS:

- IOS
- NXOS

### `s_nexthop_summary.py`

Captures route-table data, parses routes, performs recursive next-hop/interface lookup, and writes a summary CSV.

Supported OS:

- IOS
- NXOS

Can prompt for a VRF.

### `s_eigrp_topology_summary.py`

Captures EIGRP topology and summarizes how many networks are learned from each successor or feasible successor.

Supported OS:

- IOS
- NXOS

Can prompt for VRF, including all VRFs on supported command variants.

### `s_eigrp_topology_to_csv.py`

Captures EIGRP topology and exports parsed topology entries directly to CSV.

Supported OS:

- IOS
- NXOS

Can prompt for VRF.

### `s_add_global_config.py`

Adds global configuration commands to the connected device. Commands are selected from `[add_global_config]` based on detected OS.

Modes:

- Check mode: write generated configuration to a file only.
- Apply mode: send configuration commands, save config, and capture before/after running config.

Supported settings include:

- `show_instructions`
- `ios`
- `nxos`
- `asa`
- `ios-xr`

### `s_update_dhcp_relay.py`

Scans running config for old helper/relay addresses and generates or applies replacements.

Settings:

- `[update_dhcp_relay].old_relays`
- `[update_dhcp_relay].new_relays`
- `[update_dhcp_relay].remove_old_relays`
- `[update_dhcp_relay].show_instructions`

Modes:

- Check mode: write generated config.
- Apply mode: send config commands, save config, and capture before/after running config.

### `s_update_interface_desc.py`

Uses CDP detail and port-channel data to generate interface-description changes.

Settings:

- `[update_interface_desc].strip_domains`
- `[update_interface_desc].take_backups`
- `[update_interface_desc].rollback_file`

Modes:

- Check mode: write generated config.
- Apply mode: send config commands and optionally save.

Supported OS:

- IOS
- NXOS

### `s_AireOS_collect_ap_summ.py`

Collects AireOS AP summary data from `show ap summary` and writes CSV output.

Supported OS:

- AireOS

### `s_AireOS_collect_ap_detail.py`

Collects detailed AireOS AP information by combining AP summary with per-AP config, slot, txpower, and CDP detail data.

Supported OS:

- AireOS

### `s_AireOS_collect_auth_list.py`

Collects AireOS authorization-list data from `show auth-list`.

Supported OS:

- AireOS

### `s_AireOS_collect_interface_detail.py`

Collects AireOS interface summary and per-interface detail data.

Supported OS:

- AireOS

### `s_AireOS_collect_mobility_group.py`

Collects AireOS mobility summary data.

Supported OS:

- AireOS

### `s_AireOS_collect_wlan_detail.py`

Collects AireOS WLAN, remote-LAN, and guest-LAN summary/detail data.

Supported OS:

- AireOS

## Multi-Device Scripts

Multi-device scripts are launched from a disconnected SecureCRT tab. They prompt for a device CSV, connect to each device, run per-device logic, and log failures.

### `m_save_output.py`

Prompts for a command and runs it across every device in the CSV. Each device output is saved to a file.

### `m_document_device.py`

Runs the same documentation workflow as `s_document_device.py` across multiple devices.

Additional behavior:

- Supports a default custom command list if enabled by settings.
- Supports a per-device `Command List` column in the device CSV.
- Can create a folder per device.

### `m_cdp_to_csv.py`

Runs CDP export across multiple devices by reusing `s_cdp_to_csv.py`.

Known issue:

- The script reads proxy settings but does not pass `proxy=proxy` into `script.connect()`.

### `m_inventory_report.py`

Connects to all devices in the CSV and creates an inventory report with fields such as hostname, model, software version, serial number, and manufacture date.

Supported OS:

- IOS
- NXOS
- ASA

NXOS devices may also use `show inventory` to fill model/serial fields.

### `m_merged_arp_to_csv.py`

Pulls ARP tables from multiple devices and merges them into one CSV.

This is useful before running `s_switchport_mapping.py`, especially in environments where ARP tables are split across gateways, HSRP peers, or VRFs.

Supported OS:

- IOS
- NXOS

### `m_find_macs_by_vlans.py`

Searches multiple switches for locally connected MAC addresses in a selected VLAN range.

Behavior:

- Prompts for VLAN range.
- Uses spanning-tree root data to identify uplinks/root ports.
- Parses MAC address tables.
- Excludes likely uplink ports when building results.

### `m_add_global_config.py`

Runs the same global config workflow as `s_add_global_config.py` across multiple devices.

Modes:

- Check mode: generate config files only.
- Apply mode: push config and save.

### `m_update_dhcp_relay.py`

Runs DHCP relay/helper updates across multiple devices by reusing logic from `s_update_dhcp_relay.py`.

Modes:

- Check mode: generate config files only.
- Apply mode: push config and save.

### `m_update_interface_desc.py`

Runs interface-description update logic across multiple devices by reusing `s_update_interface_desc.py`.

Modes:

- Check mode: generate config files only.
- Apply mode: push config and optionally save.

## No-Device Scripts

### `import_sessions_from_csv.py`

Creates SecureCRT saved sessions from a CSV file without connecting to devices.

Example CSV:

```text
templates/import_sessions_from_csv_example.csv
```

Columns:

- `session_name`
- `hostname`
- `protocol`
- `folder`

### `get_python_info.py`

Displays the SecureCRT Python version and Python path in a SecureCRT message box.

This is useful when validating the target SecureCRT 9.7.2 / Python 3.13.4 runtime.

## How Scripts Work Together

Several scripts are designed as single-device logic first, with multi-device wrappers that handle CSV import and connection loops.

Examples:

- `s_cdp_to_csv.py`
  - Contains CDP parsing and CSV output logic.
  - Reused by `m_cdp_to_csv.py`.

- `s_document_device.py`
  - Contains document collection logic.
  - Reused by `m_document_device.py`.

- `s_add_global_config.py`
  - Contains global config generation/application logic.
  - Reused by `m_add_global_config.py`.

- `s_update_dhcp_relay.py`
  - Contains DHCP helper/relay update logic.
  - Reused by `m_update_dhcp_relay.py`.

- `s_update_interface_desc.py`
  - Contains CDP/interface-description update logic.
  - Reused by `m_update_interface_desc.py`.

Operational workflow examples:

- Build endpoint mapping:
  1. Run `m_merged_arp_to_csv.py` or `s_arp_to_csv.py`.
  2. Run `s_switchport_mapping.py`.
  3. Select the ARP CSV when prompted.

- Create SecureCRT sessions from topology discovery:
  1. Connect to a seed device.
  2. Run `s_create_sessions_from_cdp.py`.
  3. The script parses CDP detail and creates saved sessions.

- Document devices:
  1. Configure command lists in `settings/settings.ini`.
  2. Run `s_document_device.py` for one device or `m_document_device.py` for many.

- Apply network-wide changes safely:
  1. Run the relevant script in check mode.
  2. Review generated config files.
  3. Run apply mode only after validation.
  4. Review failure logs and before/after captures.

## Build, Run, Lint, Test

Run scripts in SecureCRT:

```text
Scripts -> Run -> select script
```

Single-device scripts:

```text
Connect to device first, then run s_*.py
```

Multi-device scripts:

```text
Start from disconnected tab, then run m_*.py
```

Docs build:

```bash
cd docs
make html
```

Docs dependencies are not declared in the repo. `docs/source/conf.py` imports Sphinx and `recommonmark`.

Current project gaps:

- No `requirements.txt`
- No `pyproject.toml`
- No test suite found
- No lint config found
- No CI config found

Read-only parse status from onboarding pass:

- Local interpreter used: Python 3.12.1.
- 47 Python files checked.
- `_TODO_AireOS.py` fails with `IndentationError`.
- `securecrt_tools/utilities.py` has a regex escape `SyntaxWarning`.

The real target runtime is Python 3.13.4 inside SecureCRT 9.7.2, so compatibility should be validated there.

## Risk Areas

- The current README says SecureCRT 9.x was unsupported when written; this conflicts with the planned SecureCRT 9.7.2 deployment target and should be revisited after validation.
- Python compatibility needs focused validation under Python 3.13.4.
- Many exception handlers use `e.message`, which is not valid on normal Python 3 exceptions.
- Some code mixes binary file modes with text/CSV operations.
- Config-changing scripts can push commands and save device configs.
- `send_config_commands()` has limited error checking and assumes specific prompt behavior.
- Multi-device scripts continue through device lists and write failure logs; errors may be easy to miss without reviewing the log.
- Prompt and OS detection are heuristic and Cisco-focused.
- `m_cdp_to_csv.py` reads proxy settings but does not pass `proxy=proxy` to `script.connect()`.
- `_TODO_AireOS.py` is tracked but not valid Python.

## Recommended Validation For SecureCRT 9.7.2 / Python 3.13.4

Before relying on production use:

1. Run `get_python_info.py` inside SecureCRT 9.7.2 and confirm Python 3.13.4 64-bit.
2. Validate `CRTScript` initialization.
3. Validate `CRTSession` prompt discovery and OS detection on representative IOS, NXOS, ASA, and AireOS targets.
4. Validate `settings/settings.ini` creation and repair.
5. Validate CSV read/write behavior under Python 3.13.4.
6. Replace or test all `e.message` exception paths.
7. Test single-device read-only scripts first:
   - `s_save_output.py`
   - `s_cdp_to_csv.py`
   - `s_arp_to_csv.py`
   - `s_vlan_to_csv.py`
8. Test a multi-device read-only workflow with a small CSV:
   - `m_save_output.py`
   - `m_document_device.py`
9. Test proxy behavior if jumpboxes are required.
10. Test check-mode flows before any config-changing script.
11. Review generated failure logs after all multi-device runs.
12. Update README once SecureCRT 9.7.2 compatibility is confirmed.

## Maintenance Notes

- Treat `docs/source/` as the authoritative documentation source.
- `docs/` contains generated HTML output. If docs are updated, decide whether generated HTML should also be rebuilt and committed.
- Keep top-level scripts aligned with their docs because individual script docs are generated primarily through autodoc.
- Prefer reusing existing single-device logic when adding multi-device wrappers.
- Prefer adding shared parsing/output helpers to `securecrt_tools/utilities.py` when behavior is needed by multiple scripts.
- Prefer adding new TextFSM templates under `textfsm-templates/` and resolving them with `script.get_template()`.
