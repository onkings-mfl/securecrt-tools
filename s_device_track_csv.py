# $language = "python"
# $interface = "1.0"

import os
import sys
import logging
import re

# Add script directory to the PYTHONPATH so we can import our modules (only if run from SecureCRT)
if 'crt' in globals():
    script_dir, script_name = os.path.split(crt.ScriptFullName)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
else:
    script_dir, script_name = os.path.split(os.path.realpath(__file__))

# Now we can import our custom modules
from securecrt_tools import scripts
from securecrt_tools import utilities
from securecrt_tools.message_box_const import ICON_STOP

# Create global logger so we can write debug messages from any function (if debug mode setting is enabled in settings).
logger = logging.getLogger("securecrt")
logger.debug("Starting execution of {0}".format(script_name))


# ################################################   EXCEPTIONS    ####################################################

class DeviceTrackingDisabledError(Exception):
    """
    An exception type used when IP Device Tracking is supported but disabled on the remote device.
    """
    pass


# ################################################   SCRIPT LOGIC   ###################################################

def script_main(session):
    """
    | SINGLE device script
    | Author: Jamie Caesar
    | Email: jcaesar@presidio.com

    This script will capture the device tracking table from a Cisco IOS device and output the results as a CSV file.

    :param session: A subclass of the sessions.Session object that represents this particular script session (either
                SecureCRTSession or DirectSession)
    :type session: sessions.Session

    """
    # Start session with device, i.e. modify term parameters for better interaction (assuming already connected)
    session.start_cisco_session()

    # Validate device is running a supported OS
    session.validate_os(["IOS"])

    try:
        output = get_device_tracking_database(session)
    except ValueError as err:
        logger.debug("Could not parse modern device tracking output: {0}".format(err))
        try:
            output = get_ip_device_tracking_all(session)
        except DeviceTrackingDisabledError as err:
            session.script.message_box(str(err), "Device Tracking Disabled", ICON_STOP)
            raise scripts.ScriptError(str(err))
        except ValueError as legacy_err:
            raise scripts.ScriptError("Unable to parse device tracking output.\n"
                                      "Modern command error: {0}\n"
                                      "Legacy command error: {1}".format(err, legacy_err))

    # Generate filename and output data as CSV
    output_filename = session.create_output_filename("device-track", ext=".csv")
    utilities.list_of_lists_to_csv(output, output_filename)

    # Return terminal parameters back to the original state.
    session.end_cisco_session()


def get_device_tracking_database(session):
    """
    Capture and parse "show device-tracking database" output.

    :param session: The session object used to interact with the remote device
    :type session: sessions.Session
    :return: CSV-ready device tracking data
    :rtype: list
    """
    send_cmd = "show device-tracking database"
    logger.debug("Command set to '{0}'".format(send_cmd))
    raw_tracking = session.get_command_output(send_cmd)
    return parse_device_tracking_database(raw_tracking)


def get_ip_device_tracking_all(session):
    """
    Capture and parse "show ip device tracking all" output.

    :param session: The session object used to interact with the remote device
    :type session: sessions.Session
    :return: CSV-ready device tracking data
    :rtype: list
    """
    send_cmd = "show ip device tracking all"
    logger.debug("Command set to '{0}'".format(send_cmd))
    raw_tracking = session.get_command_output(send_cmd)
    return parse_ip_device_tracking_all(raw_tracking)


def parse_device_tracking_database(raw_tracking):
    """
    Parse the modern "show device-tracking database" output used by newer Catalyst platforms.

    :param raw_tracking: Raw command output
    :type raw_tracking: str
    :return: CSV-ready device tracking data
    :rtype: list
    """
    header = ["Protocol", "Network Layer Address", "Link Layer Address", "Interface", "vlan", "prlvl", "age",
              "state", "Time left"]
    lines = raw_tracking.splitlines()
    header_index = find_header_line(lines, ["Network Layer Address", "Link Layer Address", "Interface"])
    output = [header]

    for line in lines[header_index + 1:]:
        if not line.strip():
            continue
        line_parts = line.split(None, 8)
        if len(line_parts) < 8:
            continue
        if len(line_parts) == 8:
            line_parts.append("")
        line_parts = [clean_value(part) for part in line_parts]
        output.append(line_parts)

    logger.debug("Parsed {0} records from show device-tracking database.".format(len(output) - 1))
    return output


def parse_ip_device_tracking_all(raw_tracking):
    """
    Parse the legacy "show ip device tracking all" output used by older Catalyst platforms.

    :param raw_tracking: Raw command output
    :type raw_tracking: str
    :return: CSV-ready device tracking data
    :rtype: list
    """
    validate_global_tracking(raw_tracking)
    header = ["IP Address", "MAC Address", "Vlan", "Interface", "Probe-Timeout", "State", "Source"]
    lines = raw_tracking.splitlines()
    header_index = find_header_line(lines, ["IP Address", "MAC Address", "Probe-Timeout"])
    output = [header]

    for line in lines[header_index + 1:]:
        if not line.strip() or is_separator_line(line):
            continue
        line_parts = line.split(None, 6)
        if len(line_parts) < 7:
            continue
        line_parts = [clean_value(part) for part in line_parts]
        output.append(line_parts)

    logger.debug("Parsed {0} records from show ip device tracking all.".format(len(output) - 1))
    return output


def validate_global_tracking(raw_tracking):
    """
    Validate that global IP device tracking is enabled when the legacy command exposes that setting.

    :param raw_tracking: Raw command output
    :type raw_tracking: str
    """
    re_global = re.compile(r"Global IP Device Tracking for clients\s*=\s*(\S+)", re.IGNORECASE)
    match = re_global.search(raw_tracking)

    if match and match.group(1).lower() != "enabled":
        raise DeviceTrackingDisabledError("Global IP Device Tracking for clients is not enabled on this device.")


def find_header_line(lines, markers):
    """
    Find the first line containing all expected header markers.

    :param lines: Lines from command output
    :type lines: list
    :param markers: Strings that must be present in the header line
    :type markers: list
    :return: Header line index
    :rtype: int
    """
    for index, line in enumerate(lines):
        if all(marker in line for marker in markers):
            return index
    raise ValueError("Unable to find command output header containing: {0}".format(", ".join(markers)))


def is_separator_line(line):
    """
    Return True if a command output line is a separator.

    :param line: One line of command output
    :type line: str
    :return: True if the line is made only of dashes, False otherwise
    :rtype: bool
    """
    return line.strip("- ") == ""


def clean_value(value):
    """
    Collapse whitespace from a parsed command output value.

    :param value: Value to clean
    :type value: str
    :return: Cleaned value
    :rtype: str
    """
    return " ".join(value.strip().split())


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
