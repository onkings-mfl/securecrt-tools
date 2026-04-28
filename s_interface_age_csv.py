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

# Create global logger so we can write debug messages from any function (if debug mode setting is enabled in settings).
logger = logging.getLogger("securecrt")
logger.debug("Starting execution of {0}".format(script_name))


# ################################################   SCRIPT LOGIC   ###################################################

def script_main(session):
    """
    | SINGLE device script
    | Author: Daniel L
    | Email: lenisd29@gmail.com

    This script will grab interface link age information and interface status information from a Cisco IOS device,
    merge the results by port, and export the combined data to a CSV file.

    :param session: A subclass of the sessions.Session object that represents this particular script session (either
                SecureCRTSession or DirectSession)
    :type session: sessions.Session

    """
    # Start session with device, i.e. modify term parameters for better interaction (assuming already connected)
    session.start_cisco_session()

    # Validate device is running a supported OS
    session.validate_os(["IOS"])

    # Get "show interfaces link" data
    link_cmd = "show interfaces link"
    logger.debug("Command set to '{0}'".format(link_cmd))
    raw_link = session.get_command_output(link_cmd)
    link_header, link_table = parse_interfaces_link(raw_link)

    # Get "show interfaces status" data
    status_cmd = "show interfaces status"
    logger.debug("Command set to '{0}'".format(status_cmd))
    raw_status = session.get_command_output(status_cmd)
    status_table = parse_interfaces_status(raw_status)

    # Generate filename and output data as CSV
    output = merge_interface_tables(link_header, link_table, status_table)
    output_filename = session.create_output_filename("interface-age", ext=".csv")
    utilities.list_of_lists_to_csv(output, output_filename)

    # Return terminal parameters back to the original state.
    session.end_cisco_session()


def parse_interfaces_link(raw_link):
    """
    Parse "show interfaces link" output into a dictionary keyed by port.

    Catalyst 4k output includes "Down Since", while Catalyst 9k output includes "Up Time".  The returned header
    includes only the columns that were present in the command output.

    :param raw_link: Raw output from "show interfaces link"
    :type raw_link: str
    :return: A tuple containing the dynamic CSV header columns and a dictionary of parsed port data
    :rtype: tuple
    """
    lines = raw_link.splitlines()
    header_index, header_line = find_header_line(lines, ["Port", "Name", "Down Time"])
    down_start = header_line.index("Down Time")

    if "Down Since" in header_line:
        link_header = ["Down Time", "Down Since"]
        link_type = "Down Since"
    elif "Up Time" in header_line:
        link_header = ["Down Time", "Up Time"]
        link_type = "Up Time"
    else:
        raise ValueError("Unable to determine 'show interfaces link' output type.")

    logger.debug("Detected show interfaces link type: '{0}'".format(link_type))
    output = {}
    for line in lines[header_index + 1:]:
        port_info = get_interface_port(line)
        if not port_info:
            continue
        port, port_end = port_info
        name = clean_value(line[port_end:down_start])
        remainder = clean_value(line[down_start:])

        if link_type == "Down Since":
            down_time, down_since = split_down_since(remainder)
            output[port] = {"Name": name, "Down Time": down_time, "Down Since": down_since}
        else:
            down_time, up_time = split_up_time(remainder)
            output[port] = {"Name": name, "Down Time": down_time, "Up Time": up_time}

    if not output:
        raise ValueError("No interface records found in 'show interfaces link' output.")

    logger.debug("Parsed {0} records from show interfaces link.".format(len(output)))
    return link_header, output


def parse_interfaces_status(raw_status):
    """
    Parse "show interfaces status" output into a dictionary keyed by port.

    :param raw_status: Raw output from "show interfaces status"
    :type raw_status: str
    :return: Dictionary containing interface name and status values by port
    :rtype: dict
    """
    lines = raw_status.splitlines()
    header_index, header_line = find_header_line(lines, ["Port", "Name", "Status", "Vlan"])
    status_start = header_line.index("Status")
    vlan_start = header_line.index("Vlan")

    output = {}
    for line in lines[header_index + 1:]:
        port_info = get_interface_port(line)
        if not port_info:
            continue
        port, port_end = port_info
        output[port] = {
            "Name": clean_value(line[port_end:status_start]),
            "Status": clean_value(line[status_start:vlan_start])
        }

    if not output:
        raise ValueError("No interface records found in 'show interfaces status' output.")

    logger.debug("Parsed {0} records from show interfaces status.".format(len(output)))
    return output


def merge_interface_tables(link_header, link_table, status_table):
    """
    Merge interface link data and interface status data into CSV-ready rows.

    :param link_header: Dynamic column names from "show interfaces link"
    :type link_header: list
    :param link_table: Parsed "show interfaces link" data keyed by port
    :type link_table: dict
    :param status_table: Parsed "show interfaces status" data keyed by port
    :type status_table: dict
    :return: A list of CSV rows
    :rtype: list
    """
    output = [["Port", "Name", "Status"] + link_header]
    port_list = sorted(list(set(link_table.keys()).union(status_table.keys())), key=utilities.human_sort_key)

    for port in port_list:
        link_entry = link_table.get(port, {})
        status_entry = status_table.get(port, {})
        name = status_entry.get("Name") or link_entry.get("Name") or ""
        row = [port, name, status_entry.get("Status", "")]
        for column in link_header:
            row.append(link_entry.get(column, ""))
        output.append(row)

    return output


def find_header_line(lines, markers):
    """
    Find the first line containing all expected header markers.

    :param lines: Lines from command output
    :type lines: list
    :param markers: Strings that must be present in the header line
    :type markers: list
    :return: Tuple containing line index and line text
    :rtype: tuple
    """
    for index, line in enumerate(lines):
        if all(marker in line for marker in markers):
            return index, line
    raise ValueError("Unable to find command output header containing: {0}".format(", ".join(markers)))


def get_interface_port(line):
    """
    Return the interface name and ending index from a command output row.

    :param line: One line of command output
    :type line: str
    :return: Tuple of interface name and ending index, or None if the line does not start with an interface
    :rtype: tuple
    """
    match = re.match(r"^\s*(\S+)", line)
    if not match:
        return None

    port = match.group(1)
    if re.match(r"^[A-Za-z]+[0-9][A-Za-z0-9/.:_-]*$", port):
        return port, match.end(1)
    else:
        return None


def split_down_since(value):
    """
    Split Catalyst 4k link age text into down time and down since values.

    :param value: Text after the Name column from "show interfaces link"
    :type value: str
    :return: Tuple of down time and down since strings
    :rtype: tuple
    """
    re_down_since = re.compile(r"(?P<down_since>\d{1,2}:\d{2}:\d{2}\s+\S+\s+\S+\s+\d{1,2}\s+\d{4})$")
    match = re_down_since.search(value)
    if match:
        down_time = clean_value(value[:match.start()])
        down_since = clean_value(match.group("down_since"))
    else:
        down_time = clean_value(value)
        down_since = ""
    return down_time, down_since


def split_up_time(value):
    """
    Split Catalyst 9k link age text into down time and up time values.

    :param value: Text after the Name column from "show interfaces link"
    :type value: str
    :return: Tuple of down time and up time strings
    :rtype: tuple
    """
    parts = value.split()
    if len(parts) > 1:
        return parts[0], " ".join(parts[1:])
    elif parts:
        return parts[0], ""
    else:
        return "", ""


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
