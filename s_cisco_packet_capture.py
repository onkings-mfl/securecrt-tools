# $language = "python"
# $interface = "1.0"

import getpass
import logging
import os
import re
import sys
import time
from configparser import NoOptionError, NoSectionError

# Add script directory to the PYTHONPATH so we can import our modules (only if run from SecureCRT)
if 'crt' in globals():
    script_dir, script_name = os.path.split(crt.ScriptFullName)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
else:
    script_dir, script_name = os.path.split(os.path.realpath(__file__))

# Now we can import our custom modules
from securecrt_tools import scripts
from securecrt_tools import sessions
from securecrt_tools.message_box_const import *

# Create global logger so we can write debug messages from any function (if debug mode setting is enabled in settings).
logger = logging.getLogger("securecrt")
logger.debug("Starting execution of {0}".format(script_name))


# ################################################   SCRIPT LOGIC   ###################################################

SETTINGS_HEADER = "cisco_packet_capture"

ERROR_MARKERS = [
    "% Invalid",
    "% Incomplete",
    "% Ambiguous",
    "%Error",
    "% Error",
    "Error:",
    "Invalid input detected",
    "Unknown command",
    "Unrecognized command",
]

CLEANUP_OK_MARKERS = [
    "No capture",
    "does not exist",
    "not found",
    "is not active",
    "% Invalid",
    "% Incomplete",
]

RISKY_INTERFACE_PREFIXES = (
    "po",
    "port-channel",
    "vlan",
    "vl",
    "loopback",
    "lo",
    "tunnel",
    "tu",
    "mgmt",
    "management",
)


class PacketCaptureError(Exception):
    """
    Raised when packet-capture setup, capture, export, or cleanup cannot be completed safely.
    """
    pass


class ScriptAbort(Exception):
    """
    Raised when the user cancels the workflow.
    """
    pass


def get_setting_bool(script, option, default):
    try:
        return script.settings.getboolean(SETTINGS_HEADER, option)
    except (NoSectionError, NoOptionError):
        return default


def get_setting_int(script, option, default):
    try:
        return script.settings.getint(SETTINGS_HEADER, option)
    except (NoSectionError, NoOptionError, ValueError):
        return default


def write_transcript(filename, message):
    if not filename:
        return

    with open(filename, "a") as output_file:
        output_file.write(message)
        if not message.endswith("\n"):
            output_file.write("\n")


def output_has_marker(output, markers):
    lower_output = output.lower()
    for marker in markers:
        if marker.lower() in lower_output:
            return marker
    return None


def marker_is_allowed(marker, allowed_markers):
    for allowed_marker in allowed_markers:
        if marker.lower() == allowed_marker.lower():
            return True
    return False


def validate_command_output(command, output, allowed_markers=None):
    allowed_markers = allowed_markers or []
    marker = output_has_marker(output, ERROR_MARKERS)
    if marker and not marker_is_allowed(marker, allowed_markers):
        raise PacketCaptureError(
            "Device returned an error for command:\n\n{0}\n\nMatched: {1}\n\n{2}".format(command, marker, output)
        )


def run_command(session, command, transcript=None, allowed_markers=None):
    logger.debug("<PACKET_CAPTURE> Sending command: {0}".format(command))
    output = session.get_command_output(command)
    write_transcript(transcript, "\n# {0}\n{1}\n".format(command, output))
    validate_command_output(command, output, allowed_markers=allowed_markers)
    return output


def run_cleanup_command(session, command, transcript=None):
    try:
        return run_command(session, command, transcript=transcript, allowed_markers=CLEANUP_OK_MARKERS)
    except PacketCaptureError as err:
        logger.debug("<PACKET_CAPTURE> Cleanup command failed but cleanup will continue: {0}".format(err))
        write_transcript(transcript, "\n# Cleanup warning for {0}\n{1}\n".format(command, err))
        return ""


def extract_help_tokens(output):
    tokens = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        token = stripped.split()[0].strip()
        if token and token not in tokens:
            tokens.append(token)

    return tokens


def get_context_help(session, command, transcript=None, allowed_markers=None):
    allowed_markers = allowed_markers or ["% Incomplete", "% Ambiguous"]
    output = run_command(session, "{0} ?".format(command), transcript=transcript,
                         allowed_markers=allowed_markers)
    return extract_help_tokens(output), output


def detect_capture_mode(session, capture_name, transcript=None):
    tokens, output = get_context_help(session, "monitor capture {0}".format(capture_name), transcript=transcript,
                                      allowed_markers=["% Incomplete", "% Ambiguous", "% Invalid",
                                                       "Invalid input detected"])

    named_tokens = set(["buffer", "clear", "export", "interface", "limit", "match", "start", "stop"])
    if not output_has_marker(output, ["% Invalid", "Invalid input detected"]) and named_tokens.intersection(tokens):
        logger.debug("<PACKET_CAPTURE> Detected named IOS XE monitor capture syntax.")
        return "named"

    buffer_tokens, buffer_output = get_context_help(session, "monitor capture buffer", transcript=transcript,
                                                    allowed_markers=["% Incomplete", "% Ambiguous", "% Invalid",
                                                                     "Invalid input detected"])
    point_tokens, point_output = get_context_help(session, "monitor capture point", transcript=transcript,
                                                  allowed_markers=["% Incomplete", "% Ambiguous", "% Invalid",
                                                                   "Invalid input detected"])

    if (not output_has_marker(buffer_output, ["% Invalid", "Invalid input detected"]) and
            not output_has_marker(point_output, ["% Invalid", "Invalid input detected"]) and
            buffer_tokens and point_tokens):
        logger.debug("<PACKET_CAPTURE> Detected traditional IOS EPC syntax.")
        return "traditional"

    raise sessions.UnsupportedOSError("This device does not appear to support a known Cisco packet-capture syntax.")


def get_export_syntax(session, capture_name, transcript=None):
    tokens, output = get_context_help(session, "monitor capture {0} export".format(capture_name),
                                      transcript=transcript)
    if output_has_marker(output, ["% Invalid", "Invalid input detected"]):
        raise PacketCaptureError("Unable to determine export syntax for capture {0}.".format(capture_name))

    if "location" in [token.lower() for token in tokens]:
        return "location"
    return "direct"


def verify_interface(session, interface, transcript=None):
    output = run_command(session, "show interface {0}".format(interface), transcript=transcript,
                         allowed_markers=ERROR_MARKERS)
    return not output_has_marker(output, ERROR_MARKERS + ["not a valid interface", "Invalid interface"])


def is_risky_interface(interface):
    normalized = interface.lower().replace(" ", "")
    if "." in normalized:
        return True

    return normalized.startswith(RISKY_INTERFACE_PREFIXES)


def prompt_required(script, message, title, default=""):
    while True:
        value = script.prompt_window(message, title).strip()
        if value:
            return value

        result = script.message_box("A value is required. Do you want to try again?", title,
                                    ICON_QUESTION + BUTTON_YESNO + DEFBUTTON1)
        if result != IDYES:
            raise ScriptAbort("Cancelled.")


def prompt_secret(script, message, title):
    if hasattr(script, "crt"):
        return script.crt.Dialog.Prompt(message, title, "", True)
    return getpass.getpass("{0}: ".format(message))


def prompt_int(script, message, title, default, minimum, maximum):
    while True:
        value = script.prompt_window(message, title).strip()
        if not value:
            value = str(default)

        try:
            int_value = int(value)
        except ValueError:
            script.message_box("Enter a whole number.", title, ICON_WARN)
            continue

        if minimum <= int_value <= maximum:
            return int_value

        script.message_box("Enter a value from {0} through {1}.".format(minimum, maximum), title, ICON_WARN)


def prompt_capture_name(script):
    name_exp = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    while True:
        capture_name = prompt_required(script, "Enter the packet-capture name:", "Capture Name", "pktcap")
        if name_exp.match(capture_name):
            return capture_name

        script.message_box("Use 1-32 letters, numbers, underscores, or hyphens. The first character must be a letter.",
                           "Invalid Capture Name", ICON_WARN)


def prompt_interface(session, transcript=None):
    script = session.script
    warn_on_risky = get_setting_bool(script, "warn_on_risky_interface", True)

    while True:
        interface = prompt_required(
            script,
            "Enter the physical interface to capture (for example Gi1/0/1 or TenGigabitEthernet1/0/1):",
            "Interface"
        )

        if not verify_interface(session, interface, transcript=transcript):
            script.message_box("Invalid interface or interface does not exist.\n\nPlease try again.",
                               "Interface Check", ICON_WARN)
            continue

        if warn_on_risky and is_risky_interface(interface):
            result = script.message_box(
                "This interface looks like a logical or platform-sensitive target:\n\n{0}\n\n"
                "Cisco packet capture is commonly restricted on logical interfaces such as Port-channels, SVIs, "
                "subinterfaces, management ports, and similar targets.\n\nProceed anyway?".format(interface),
                "Interface Warning",
                ICON_WARN + BUTTON_YESNOCANCEL + DEFBUTTON2
            )
            if result == IDYES:
                return interface
            if result == IDCANCEL:
                raise ScriptAbort("Cancelled.")
            continue

        return interface


def choose_export_option(script):
    options = {
        "1": "local",
        "2": "scp",
        "3": "ftp",
        "4": "sftp",
        "5": "tftp",
    }
    menu = "[1] Local only\n\n[2] SCP\n\n[3] FTP\n\n[4] SFTP\n\n[5] TFTP"

    while True:
        choice = script.prompt_window(menu, "Export Option").strip()
        if choice in options:
            return options[choice]

        if not choice:
            raise ScriptAbort("Cancelled.")

        script.message_box("Choose one of the listed export options.", "Export Option", ICON_WARN)


def parse_free_mb(dir_output):
    free_match = re.search(r"\((\d+)\s+bytes\s+free\)", dir_output, re.IGNORECASE)
    if not free_match:
        free_match = re.search(r"(\d+)\s+bytes\s+free", dir_output, re.IGNORECASE)

    if not free_match:
        return 0

    return int(free_match.group(1)) // 1048576


def detect_local_storage(session, transcript=None):
    output = run_command(session, "show file systems", transcript=transcript)

    if "bootflash:" in output:
        storage = "bootflash"
    elif "flash:" in output:
        storage = "flash"
    else:
        storage = "flash"

    dir_output = run_command(session, "dir {0}:".format(storage), transcript=transcript)
    return storage, parse_free_mb(dir_output)


def choose_buffer(session, storage, free_mb):
    script = session.script
    default = get_setting_int(script, "default_buffer_size_mb", 25)
    minimum = get_setting_int(script, "min_buffer_size_mb", 1)
    maximum = get_setting_int(script, "max_buffer_size_mb", 100)

    while True:
        buffer_size = prompt_int(
            script,
            "Available space on {0}: {1} MB\n\nEnter buffer size in MB:".format(storage, free_mb),
            "Buffer Size",
            default,
            minimum,
            maximum
        )

        if free_mb and buffer_size >= free_mb:
            result = script.message_box(
                "The selected buffer size ({0} MB) is greater than or equal to the reported free space "
                "on {1}: ({2} MB).\n\nChoose a smaller size?".format(buffer_size, storage, free_mb),
                "Low Free Space",
                ICON_WARN + BUTTON_YESNO + DEFBUTTON1
            )
            if result == IDYES:
                continue

        return buffer_size


def choose_runtime(script):
    default = get_setting_int(script, "default_runtime_seconds", 30)
    minimum = get_setting_int(script, "min_runtime_seconds", 5)
    maximum = get_setting_int(script, "max_runtime_seconds", 300)

    return prompt_int(script, "Enter capture runtime in seconds:", "Runtime", default, minimum, maximum)


def confirm_cleanup(session, had_error):
    script = session.script
    if had_error:
        return True

    if get_setting_bool(script, "cleanup_capture_on_exit", False):
        return True

    result = script.message_box("Clear captured packets and remove packet-capture configuration from the device now?",
                                "Cleanup Capture", ICON_QUESTION + BUTTON_YESNO + DEFBUTTON1)
    return result == IDYES


def confirm_delete_local_file(session):
    script = session.script
    if get_setting_bool(script, "delete_local_pcap_after_remote_copy", False):
        return True

    if not get_setting_bool(script, "prompt_delete_local_pcap", True):
        return False

    result = script.message_box("Delete the local PCAP file from device storage after the remote copy?",
                                "Delete Local PCAP", ICON_QUESTION + BUTTON_YESNO + DEFBUTTON2)
    return result == IDYES


def action_text(action, script):
    if callable(action):
        return action(script)
    return action


def accept_host_key(script):
    result = script.message_box("The remote server host key is not trusted by the device.\n\nAccept it for this copy?",
                                "Accept Host Key", ICON_WARN + BUTTON_YESNO + DEFBUTTON2)
    if result == IDYES:
        return "yes\n"
    raise PacketCaptureError("User declined remote host-key acceptance.")


def send_interactive(session, command, timeout, prompt_actions, success_markers=None, error_markers=None,
                     transcript=None, max_steps=60):
    success_markers = success_markers or []
    error_markers = error_markers or ERROR_MARKERS

    if not hasattr(session, "screen"):
        output = run_command(session, command, transcript=transcript)
        return output

    patterns = [session.prompt] + list(prompt_actions.keys()) + success_markers + error_markers
    screen = session.screen
    screen.Send(command + "\n")
    write_transcript(transcript, "\n# {0}\n".format(command))

    steps = 0
    while steps < max_steps:
        result = screen.WaitForStrings(patterns, timeout)
        if result == 0:
            raise PacketCaptureError("Timeout waiting for device response after command:\n\n{0}".format(command))

        matched = patterns[result - 1]
        write_transcript(transcript, "Matched: {0}".format(matched))

        if matched == session.prompt:
            return ""

        if matched in prompt_actions:
            screen.Send(action_text(prompt_actions[matched], session.script))
            steps += 1
            continue

        if matched in success_markers:
            steps += 1
            continue

        if matched in error_markers:
            tail = screen.ReadString(session.prompt, 10)
            raise PacketCaptureError(
                "Device reported an error while processing:\n\n{0}\n\nMatched text: {1}\n\n{2}".format(
                    command, matched, tail
                )
            )

    raise PacketCaptureError("Safety limit reached while handling interactive command:\n\n{0}".format(command))


def run_confirmed_command(session, command, transcript=None, timeout=30):
    prompt_actions = {
        "[confirm]": "\n",
        "[clear]?[confirm]": "\n",
        "[clear]? [confirm]": "\n",
        "clear]?[confirm]": "\n",
        "clear]? [confirm]": "\n",
        "confirm": "\n",
    }

    send_interactive(session, command, timeout, prompt_actions,
                     error_markers=[],
                     transcript=transcript,
                     max_steps=10)


def export_named_capture(session, capture_name, local_file, transcript=None):
    export_syntax = get_export_syntax(session, capture_name, transcript=transcript)
    if export_syntax == "location":
        export_cmd = "monitor capture {0} export location {1}".format(capture_name, local_file)
    else:
        export_cmd = "monitor capture {0} export {1}".format(capture_name, local_file)

    prompt_actions = {
        "overwrite?[confirm]": "\n",
        "overwrite? [confirm]": "\n",
        "[confirm]": "\n",
    }

    send_interactive(session, export_cmd, 60, prompt_actions,
                     success_markers=["Export Started Successfully", "Export completed"],
                     transcript=transcript)


def export_traditional_capture(session, buffer_name, local_file, transcript=None):
    export_cmd = "monitor capture buffer {0} export {1}".format(buffer_name, local_file)
    prompt_actions = {
        "overwrite?[confirm]": "\n",
        "overwrite? [confirm]": "\n",
        "[confirm]": "\n",
    }

    send_interactive(session, export_cmd, 60, prompt_actions,
                     success_markers=["bytes copied", "Exported", "Export completed"],
                     transcript=transcript)


def copy_remote(session, local_file, protocol, server_ip, remote_filename, username="", password="", transcript=None):
    def send_username(script):
        if username:
            return username + "\n"
        return "\n"

    def send_filename(script):
        if remote_filename:
            return remote_filename + "\n"
        return "\n"

    prompt_actions = {
        "Address or name of remote host []?": server_ip + "\n",
        "Address or name of remote host": server_ip + "\n",
        "Remote host []?": server_ip + "\n",
        "Destination username": send_username,
        "destination username": send_username,
        "Destination filename": send_filename,
        "destination filename": send_filename,
        "Destination file name": send_filename,
        "destination file name": send_filename,
        "Source filename": "\n",
        "overwrite?[confirm]": "\n",
        "overwrite? [confirm]": "\n",
        "[confirm]": "\n",
        "yes/no": accept_host_key,
        "(yes/no)?": accept_host_key,
        "Are you sure you want to continue connecting": accept_host_key,
        "Host key not found": accept_host_key,
        "authenticity of host": accept_host_key,
        "authenticity of the host": accept_host_key,
        "Continue connecting": accept_host_key,
        "Username:": send_username,
        "username:": send_username,
        "login as:": send_username,
        "Password:": password + "\n",
        "password:": password + "\n",
    }

    error_markers = ERROR_MARKERS + [
        "Permission denied",
        "Authentication failed",
        "Login invalid",
        "No such file",
        "No route to host",
        "Connection refused",
        "Timed out",
    ]

    copy_cmd = "copy {0} {1}:".format(local_file, protocol)
    send_interactive(session, copy_cmd, 60, prompt_actions,
                     success_markers=["bytes copied", "copied in", "Writing ", "!!"],
                     error_markers=error_markers,
                     transcript=transcript)


def delete_local_file(session, local_file, transcript=None):
    prompt_actions = {
        "Delete filename": "\n",
        "delete filename": "\n",
        "[confirm]": "\n",
    }
    send_interactive(session, "delete {0}".format(local_file), 30, prompt_actions,
                     success_markers=["Deleted", "bytes copied"], transcript=transcript)


def setup_named_capture(session, capture_name, interface, buffer_size, runtime, local_file, transcript=None):
    export_needed = True

    run_cleanup_command(session, "monitor capture {0} stop".format(capture_name), transcript=transcript)
    clear_named_capture(session, capture_name, transcript=transcript)
    run_confirmed_cleanup(session, "no monitor capture {0}".format(capture_name), transcript=transcript)

    run_command(session, "monitor capture {0} interface {1} both".format(capture_name, interface),
                transcript=transcript)

    try:
        run_command(session, "monitor capture {0} match any".format(capture_name), transcript=transcript)
    except PacketCaptureError as err:
        write_transcript(transcript, "\n# Warning: match any was not accepted. Continuing with platform default.\n{0}\n"
                         .format(err))

    try:
        try:
            run_command(session, "monitor capture {0} buffer circular size {1}".format(capture_name, buffer_size),
                        transcript=transcript)
        except PacketCaptureError:
            run_command(session, "monitor capture {0} buffer circular".format(capture_name), transcript=transcript)
            run_command(session, "monitor capture {0} buffer size {1}".format(capture_name, buffer_size),
                        transcript=transcript)
    except PacketCaptureError:
        run_command(session, "monitor capture file {0}".format(local_file), transcript=transcript)
        export_needed = False

    run_command(session, "monitor capture {0} limit duration {1}".format(capture_name, runtime),
                transcript=transcript)

    return export_needed


def setup_traditional_capture(session, capture_name, interface, buffer_size, transcript=None):
    buffer_name = "{0}BUF".format(capture_name[:24])
    point_name = "{0}POINT".format(capture_name[:22])
    buffer_kb = buffer_size * 1024

    run_cleanup_command(session, "monitor capture point stop {0}".format(point_name), transcript=transcript)
    run_cleanup_command(session, "no monitor capture point ip cef {0} {1} both".format(point_name, interface),
                        transcript=transcript)
    run_cleanup_command(session, "no monitor capture buffer {0}".format(buffer_name), transcript=transcript)

    run_command(session, "monitor capture buffer {0} size {1} max-size 1518 circular".format(buffer_name, buffer_kb),
                transcript=transcript)
    run_command(session, "monitor capture point ip cef {0} {1} both".format(point_name, interface),
                transcript=transcript)
    run_command(session, "monitor capture point associate {0} {1}".format(point_name, buffer_name),
                transcript=transcript)

    return buffer_name, point_name


def clear_named_capture(session, capture_name, transcript=None):
    try:
        run_confirmed_command(session, "monitor capture {0} clear".format(capture_name), transcript=transcript)
    except PacketCaptureError as err:
        logger.debug("<PACKET_CAPTURE> Capture clear failed but cleanup will continue: {0}".format(err))
        write_transcript(transcript, "\n# Cleanup warning for monitor capture {0} clear\n{1}\n"
                         .format(capture_name, err))


def run_confirmed_cleanup(session, command, transcript=None):
    try:
        run_confirmed_command(session, command, transcript=transcript)
    except PacketCaptureError as err:
        logger.debug("<PACKET_CAPTURE> Confirmed cleanup command failed but cleanup will continue: {0}".format(err))
        write_transcript(transcript, "\n# Cleanup warning for {0}\n{1}\n".format(command, err))


def cleanup_named_capture(session, capture_name, remove_capture, transcript=None):
    run_cleanup_command(session, "monitor capture {0} stop".format(capture_name), transcript=transcript)
    if remove_capture:
        clear_named_capture(session, capture_name, transcript=transcript)
        run_confirmed_cleanup(session, "no monitor capture {0}".format(capture_name), transcript=transcript)


def cleanup_traditional_capture(session, buffer_name, point_name, interface, remove_capture, transcript=None):
    run_cleanup_command(session, "monitor capture point stop {0}".format(point_name), transcript=transcript)
    if remove_capture:
        run_cleanup_command(session, "no monitor capture point ip cef {0} {1} both".format(point_name, interface),
                            transcript=transcript)
        run_cleanup_command(session, "no monitor capture buffer {0}".format(buffer_name), transcript=transcript)


def run_capture(session, capture_name, interface, runtime, buffer_size, local_file, export_option, transcript=None):
    capture_mode = detect_capture_mode(session, capture_name, transcript=transcript)
    buffer_name = None
    point_name = None
    capture_started = False

    try:
        if capture_mode == "named":
            export_needed = setup_named_capture(session, capture_name, interface, buffer_size, runtime, local_file,
                                                transcript=transcript)
            run_command(session, "monitor capture {0} start".format(capture_name), transcript=transcript)
            capture_started = True
            time.sleep(runtime)
            run_command(session, "monitor capture {0} stop".format(capture_name), transcript=transcript)
            capture_started = False
            if export_needed:
                export_named_capture(session, capture_name, local_file, transcript=transcript)
        else:
            buffer_name = "{0}BUF".format(capture_name[:24])
            point_name = "{0}POINT".format(capture_name[:22])
            buffer_name, point_name = setup_traditional_capture(session, capture_name, interface, buffer_size,
                                                               transcript=transcript)
            run_command(session, "monitor capture point start {0}".format(point_name), transcript=transcript)
            capture_started = True
            time.sleep(runtime)
            run_command(session, "monitor capture point stop {0}".format(point_name), transcript=transcript)
            capture_started = False
            export_traditional_capture(session, buffer_name, local_file, transcript=transcript)

        return capture_mode, buffer_name, point_name, capture_started
    except Exception:
        if capture_mode == "named":
            cleanup_named_capture(session, capture_name, True, transcript=transcript)
        elif buffer_name and point_name:
            cleanup_traditional_capture(session, buffer_name, point_name, interface, True, transcript=transcript)
        raise


def script_main(session):
    """
    | SINGLE device script
    | Author: Daniel L
    | Email: lenisd29@gmail.com

    Capture packets from a Cisco IOS/IOS XE device using Cisco Embedded Packet Capture or IOS XE monitor capture,
    export the capture to local device storage, and optionally copy the PCAP to a remote server.

    The script defaults to broad `match any` capture behavior on both interface directions. It limits the capture by
    user-selected runtime and buffer size, and it cleans capture state before returning control to the user.

    **Script Settings** (found in settings/settings.ini):

    * | **default_runtime_seconds** - Default capture runtime prompt value.
    * | **min_runtime_seconds** - Minimum allowed capture runtime.
    * | **max_runtime_seconds** - Maximum allowed capture runtime.
    * | **default_buffer_size_mb** - Default capture buffer prompt value.
    * | **min_buffer_size_mb** - Minimum allowed capture buffer.
    * | **max_buffer_size_mb** - Maximum allowed capture buffer.
    * | **warn_on_risky_interface** - Warn before attempting logical or platform-sensitive interface names.
    * | **cleanup_capture_on_exit** - Remove capture configuration automatically after export instead of prompting.
    * | **prompt_delete_local_pcap** - Prompt to delete local PCAP after a remote copy.
    * | **delete_local_pcap_after_remote_copy** - Delete local PCAP automatically after a remote copy.

    :param session: A subclass of the sessions.Session object that represents this particular script session.
    :type session: sessions.Session
    """
    script = session.script
    transcript = None
    capture_name = None
    interface = None
    capture_mode = None
    buffer_name = None
    point_name = None
    cleanup_needed = False
    had_error = False

    try:
        session.start_cisco_session()
        session.validate_os(["IOS"])

        capture_name = prompt_capture_name(script)
        transcript = session.create_output_filename("packet-capture-{0}-transcript".format(capture_name))
        write_transcript(transcript, "Cisco packet capture transcript for {0}\n".format(session.hostname))

        interface = prompt_interface(session, transcript=transcript)
        runtime = choose_runtime(script)
        storage, free_mb = detect_local_storage(session, transcript=transcript)
        buffer_size = choose_buffer(session, storage, free_mb)
        export_option = choose_export_option(script)

        filename = "{0}.pcap".format(capture_name)
        local_file = "{0}:{1}".format(storage, filename)

        capture_mode, buffer_name, point_name, _ = run_capture(
            session,
            capture_name,
            interface,
            runtime,
            buffer_size,
            local_file,
            export_option,
            transcript=transcript
        )
        cleanup_needed = True

        if export_option != "local":
            server_ip = prompt_required(script, "Enter server IP or hostname:", "Server IP/Hostname")
            username = ""
            password = ""
            if export_option != "tftp":
                username = prompt_required(script, "Enter username:", "Username")
                password = prompt_secret(script, "Enter password:", "Password")
                if not password:
                    raise ScriptAbort("Cancelled.")

            path = script.prompt_window("Enter remote path (optional, for example /captures/):", "Remote Path").strip()
            if path and not path.endswith("/"):
                path += "/"
            remote_filename = path + filename if path else filename

            copy_remote(session, local_file, export_option, server_ip, remote_filename, username, password,
                        transcript=transcript)

            if confirm_delete_local_file(session):
                delete_local_file(session, local_file, transcript=transcript)

        script.message_box("Packet capture workflow completed.\n\nTranscript:\n{0}".format(transcript),
                           "Packet Capture", ICON_INFO)

    except ScriptAbort:
        had_error = True
        write_transcript(transcript, "\n# User cancelled packet capture workflow.\n")
    except Exception:
        had_error = True
        write_transcript(transcript, "\n# Packet capture workflow failed.\n")
        raise
    finally:
        remove_capture = confirm_cleanup(session, had_error) if cleanup_needed or had_error else False
        if capture_name and session.prompt:
            if capture_mode == "traditional" and buffer_name and point_name and interface:
                cleanup_traditional_capture(session, buffer_name, point_name, interface, remove_capture,
                                            transcript=transcript)
            else:
                cleanup_named_capture(session, capture_name, remove_capture, transcript=transcript)

        session.end_cisco_session()


# ################################################  SCRIPT LAUNCH   ###################################################

# If this script is run from SecureCRT directly, use the SecureCRT specific class
if __name__ == "builtins":
    # Initialize script object
    crt_script = scripts.CRTScript(crt)
    # Get session object for the SecureCRT tab that the script was launched from.
    crt_session = crt_script.get_main_session()
    # Run script's main logic against our session
    try:
        script_main(crt_session)
    except Exception:
        crt_session.end_cisco_session()
        raise
    # Shutdown logging after
    logging.shutdown()

# If the script is being run directly, use the simulation class
elif __name__ == "__main__":
    # Initialize script object
    direct_script = scripts.DebugScript(os.path.realpath(__file__))
    # Get a simulated session object to pass into the script.
    sim_session = direct_script.get_main_session()
    # Run script's main logic against our session
    script_main(sim_session)
    # Shutdown logging after
    logging.shutdown()
