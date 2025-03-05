"""
This module contains classes for representing the execution of a script in SecureCRT.  The attributes and methods
defined with these classes are more "global" in nature, meaning that they focus on either the interaction with the
application, or anything that is common to the entire script regardless of how many sessions (in tabs) are open to
remote devices.
"""

import os
import sys
import logging
import datetime
import csv
import getpass
from abc import ABCMeta, abstractmethod
from . import sessions
from .settings import SettingsImporter
from .message_box_const import *


# ################################################    EXCEPTIONS     ###################################################


class ScriptError(Exception):
    """
    An exception type that is raised when there is a problem with the main scripts, such as missing settings files.
    """
    pass

class ConnectError(Exception):
    """
    An exception type that is raised when there are problems connecting to a device.
    """
    pass


# ################################################    APP  CLASSES    ##################################################

class Script(metaclass=ABCMeta):
    """
    This is a base class for the script object.  This class cannot be used directly, but is instead a blueprint that
    enforces what any sub-classes must implement.  The reason for using this design (base class with sub-classes) is
    to allow the script to be run in different contexts without needing to change the code, as long as the correct
    sub-class is being used.

    For example, the most important sub-class is the CRTScript subclass which is used when the script is executed from
    SecureCRT.  This class is written to interact with SecureCRT's Python API to be able to control the applications.
    If the script author wants to display something to the user, they can use the message_box() method to use
    SecureCRT's pop-up message box (crt.Dialog.MessageBox() call).  The other sub-class (currently) is the DebugScript
    sub-class, which was created to allow easier debugging of a script's logic by letting you execute the script using
    a local python installation -- ideally in your IDE of choice. This would allow you to use the fully debugging
    features of the IDE which are otherwise not available when executing a script inside SecureCRT.  When the
    message_box() is called on the DebugScript sub-class, the message will be printed to the console.

    This sub-class design can also allow for additional classes to be created in the future -- perhaps one that uses
    Netmiko to connect to the remote devices.   In this way, if a Netmiko sub-class was created, then all of the same
    scripts can be executed without needing to change them, because the Netmiko class would be required to implement
    all of the same methods that are defined in the base class (just like CRTScript and DebugScript)

    DebugScript class is to allow the programmer to debug their code in their favorite IDE or debugger, which cannot
    be done when executing the script from SecureCRT (in which case you are forced to either use debug messages or write
    outputs to a messagebox.  DebugScript allows the same code to run locally without SecureCRT and the class will
    prompt for the information it needs to continue running the main script.

    Any methods that are not prepended with the @abstractmethod tag preceding the method definition will be inherited
    and available to the sub-classes without needing to define them specifically in each sub-class.  Methods designed
    this way would use the exact same code in all sub-classes, and so there is no reason to re-create them in each
    subclass.

    Methods defined with the @abstractmethod tag should be left empty in this class.  They are required to be
    implemented in each sub-class.  Methods are defined this way when they are required to exist in all sub-classes
    for consistency, but the code would be written completely different depending on which class is being used.  One
    example is the message_box method below.  Under the CRTScript class, this method uses the SecureCRT API to print
    messages and format the text box that should pop up to the user, but in the DebugScript class this method only
    prints the message to the console.  In this way, a call to this method will work either way the script is called
    as long as the correct Script sub-class is being used (and the template are already written to do this).
    """

    def __init__(self, script_path):
        # Initialize application attributes
        self.script_dir, self.script_name = os.path.split(script_path)
        self.logger = logging
        self.main_session = None
        self.host_os = sys.platform

        # Load Settings
        settings_file = os.path.join(self.script_dir, "settings", "settings.ini")
        try:
            self.settings = SettingsImporter(settings_file)
        except IOError:
            error_msg = "A settings file at {0} does not exist.  Do you want to create it?".format(settings_file)
            result = self.message_box(error_msg, "Missing Settings File", ICON_QUESTION | BUTTON_YESNO)
            if result == IDYES:
                self.settings = SettingsImporter(settings_file, create=True)
            else:
                raise ScriptError("Settings file not found")

        # Get the date and time, which is returned when creating filenames based on a session from this script.
        now = datetime.datetime.now()
        date_format = self.settings.get("Global", "date_format")
        self.datetime = now.strftime(date_format)

        # Extract and store "save path" for future reference by scripts.
        output_dir = self.settings.get("Global", "output_dir")
        exp_output_dir = os.path.expandvars(os.path.expanduser(output_dir))
        if os.path.isabs(exp_output_dir):
            self.output_dir = os.path.realpath(exp_output_dir)
        else:
            full_path = os.path.join(self.script_dir, exp_output_dir)
            self.output_dir = os.path.realpath(full_path)
        self.validate_dir(self.output_dir)

        # Check if Debug Mode is enabled.
        if self.settings.getboolean("Global", "debug_mode"):
            self.debug_dir = os.path.join(self.output_dir, "debugs")
            self.validate_dir(self.debug_dir)
            log_file = os.path.join(self.debug_dir, self.script_name.replace(".py", "-debug.txt"))
            self.logger = logging.getLogger("securecrt")
            self.logger.propagate = False
            self.logger.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%m/%d/%Y %I:%M:%S')
            fh = logging.FileHandler(log_file, mode='w')
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)
            self.logger.debug("<SCRIPT_INIT> Starting Logging. Running Python version: {0}".format(sys.version))

    def get_main_session(self):
        """
        Returns a CRTSession object that interacts with the SecureCRT tab that the script was lauched within.  This is
        the primary tab that will be used to interact with remote devices.  While new tabs can be created to connect to
        other devices, SecureCRT does not support multi-threading so multiple devices cannot be interacted with
        simultaneously via a script.

        :return: A session object that represents the tab where the script was launched
        :rtype: sessions.Session
        """
        return self.main_session

    def validate_dir(self, path, prompt_to_create=True):
        """
        Verifies that the path to the supplied directory exists.  If not, prompt the user to create it.

        :param path: A directory path (not including filename) to be validated
        :type path: str
        """

        self.logger.debug("<VALIDATE_PATH> Starting validation of path: {0}".format(path))

        # Verify that base_path is valid absolute path, or else error and exit.
        if not os.path.isabs(path):
            self.logger.debug("<VALIDATE_PATH> Supplied path is not an absolute path. Raising exception".format(path))
            error_str = 'Directory {0} is invalid.'.format(path)
            raise IOError(error_str)

        # Check if directory exists.  If not, prompt to create it.
        if not os.path.exists(os.path.normpath(path)):
            if prompt_to_create:
                self.logger.debug("<VALIDATE_PATH> Supplied directory path does not exist. Prompting User.")
                message_str = "The path: '{0}' does not exist.  Do you want to create it?.".format(path)
                result = self.message_box(message_str, "Create Directory?", ICON_QUESTION | BUTTON_YESNO | DEFBUTTON2)

                if result == IDYES:
                    self.logger.debug("<VALIDATE_PATH> User chose to create directory.".format(path))
                    os.makedirs(path)
                else:
                    self.logger.debug("<VALIDATE_PATH> User chose NOT to create directory.  Raising exception")
                    error_str = 'Required directory {0} does not exist.'.format(path)
                    raise IOError(error_str)
            else:
                self.logger.debug("<VALIDATE_PATH> Supplied directory path does not exist. Prompting User OVERRIDDEN")
                self.logger.debug("<VALIDATE_PATH> Creating directory.".format(path))
                os.makedirs(path)

        self.logger.debug("<VALIDATE_PATH> Path is Valid.")

    def get_template(self, name):
        """
        Retrieve the full path to a TextFSM template file.

        :param name: Filename of the template
        :type name: str

        :return: Full path to the template location
        :rtype: str
        """
        path = os.path.abspath(os.path.join(self.script_dir, "textfsm-templates", name))
        if os.path.isfile(path):
            return path
        else:
            raise IOError("The template name {0} does not exist.".format(name))

    def import_device_list(self):
        """
        This function will prompt for a device list CSV file to import, returns a list containing all of the
        devices that were in the CSV file and their associated credentials.  The CSV file must be of the format, and
        include a header row of ['Hostname', 'Protocol', 'Username', 'Password', 'Enable', 'Proxy Session'].  An example
        device list CSV file is at 'template/sample_device_list.csv'

        The 'Proxy Session' options is looking for a SecureCRT session name that can be used to proxy this connection
        through.  This sets the 'Firewall' option under a SecureCRT session to perform this connection proxy.

        Some additional information about missing items from a line in the CSV:
        - If the hostname field is missing, the line will be skipped.
        - If the protocol field is empty, the script will try SSH2, then SSH1, then Telnet.
        - If the username is missing, this method will prompt the user for a default usernaem to use
        - If the password is missing, will prompt the user for a password for each username missing a password
        - If the enable password is missing, the method will ask the user if they want to set a default enable to use
        - If the IP is included then the device will be reached through the jumpbox, otherwise connect directly.

        :return: A list where each entry is a dictionary representing a device and the associated login information.
        :rtype: list of dict
        """
        # Get the filename of the device list CSV file.
        self.logger.debug("<IMPORT_DEVICES> Prompting for input CSV file.")
        device_list_filename = ""
        device_list_filename = self.file_open_dialog("Please select a device list CSV file.", "Open",
                                                     device_list_filename, "CSV Files (*.csv)|*.csv||")
        if device_list_filename == "":
            self.logger.debug("<IMPORT_DEVICES> No filename received from dialog window.  Exiting.")
            return

        self.logger.debug("<IMPORT_DEVICES> Starting processing of device CSV file.")
        # Track how many lines of the CSV are skipped.
        skipped_lines = 0

        # The username that will be used when one isn't given in the CSV.  This will be prompted for when an empty
        # username field is found.
        device_list = []
        default_username = None
        default_enable = None
        prompt_enable = True
        credentials = {}
        required_header = {'Hostname', 'Protocol', 'Username'}

        # Extract the list of devices into a data structure we can use (and fill in any gaps needed).
        with open(device_list_filename, 'r') as device_file:
            device_csv = csv.DictReader(device_file)

            # Get a list of all the header values found in the CSV in lowercase.
            header = set(device_csv.fieldnames)
            if required_header.difference(header):
                raise ScriptError("CSV file does not have a valid header row.\n"
                                  "Please see the documentation or the templates/sample_device_list.csv file for an "
                                  "example")

            line = 0
            for entry in device_csv:
                line += 1

                if not entry['Hostname']:
                    self.logger.debug("<IMPORT_DEVICES> Skipping CSV line {0} because no hostname exists.".format(line))
                    skipped_lines += 1
                    continue

                if entry['Protocol'].lower() not in ['', 'ssh', 'ssh1', 'ssh2', 'telnet']:
                    self.logger.debug("<IMPORT_DEVICES> Skipping CSV line {0} because no valid protocol.".format(line))
                    skipped_lines += 1
                    continue

                if not entry['Username']:
                    if default_username:
                        entry['Username'] = default_username
                        self.logger.debug("<IMPORT_DEVICES> Using default username '{0}', for host {1}."
                                          .format(default_username, entry['Hostname']))
                    else:
                        self.logger.debug(
                            "<IMPORT_DEVICES> Didn't find username for host '{0}'.  Prompting for DEFAULT."
                            .format(entry['Hostname']))
                        default_username = self.prompt_window("Enter the DEFAULT USERNAME to use.")
                        if not default_username:
                            self.logger.debug("<IMPORT_DEVICES> Default username not provided.  Stopping".format(line))
                            error = "Found hosts without usernames and no default username provided."
                            raise ScriptError(error)
                        else:
                            self.logger.debug("<IMPORT_DEVICES> Using default username '{0}', for host {1}."
                                              .format(default_username, entry['Hostname']))
                            entry['Username'] = default_username

                if "Password" not in header:
                    entry['Password'] = ""
                if not entry['Password']:
                    try:
                        entry['Password'] = credentials[entry['Username']]
                    except KeyError:
                        self.logger.debug("<IMPORT_DEVICES> Prompting for password for username '{0}'"
                                          .format(entry['Username']))
                        password = self.prompt_window("Enter the password for USER: {0}".format(entry['Username']),
                                                      hide_input=True)
                        if password:
                            credentials[entry['Username']] = password
                            entry['Password'] = password
                        else:
                            self.logger.debug("<IMPORT_DEVICES> Skipping {0}.  No password for user.".format(line[0]))
                            skipped_lines += 1
                            continue

                if "Enable" not in header:
                    entry['Enable'] = ""
                if not entry["Enable"]:
                    if default_enable:
                        entry["Enable"] = default_enable
                    elif prompt_enable:
                        self.logger.debug(
                            "<IMPORT_DEVICES> Devices without enable passwords found.  Prompting for password.")
                        enable_msg = "Devices were found without enable passwords listed.  Do you want to enter a " \
                                     "default enable password?"
                        result = self.message_box(enable_msg, "No Enable PW", BUTTON_YESNO | ICON_QUESTION)
                        if result == IDYES:
                            default_enable = self.prompt_window("Enter default ENABLE password", "Enter Enable",
                                                                hide_input=True)
                            entry["Enable"] = default_enable
                        else:
                            prompt_enable = False

                device_list.append(entry)

        # Give stats on how many devices were found and prompt user before going forward with connections.
        validate_message = "{0} devices found in CSV.\n" \
                           "{1} lines in CSV skipped.\n" \
                           "\n" \
                           "Do you want to proceed?".format(len(device_list), skipped_lines)
        message_box_design = ICON_QUESTION | BUTTON_CANCEL | DEFBUTTON2
        self.logger.debug("<IMPORT_DEVICES> Prompting the user to continue with updates.")
        result = self.message_box(validate_message, "Ready to Start?", message_box_design)

        # IF user cancels, end program.
        if result == IDCANCEL:
            self.logger.debug("<IMPORT_DEVICES> User chose to cancel the script.")
            return

        return device_list

    @abstractmethod
    def connect_ssh(self, host, username, password, version=None, proxy=None, prompt_endings=("#", ">")):
        """
        Connects to a device via the SSH protocol. By default, SSH2 will be tried first, but if it fails it will attempt
        to fall back to SSH1.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
            user will be prompted for one.
        :type password: str
        :param version: The SSH version to connect with (1 or 2).  Default is None, which will try 2 first and fallback
            to 1 if that fails.
        :type version: int
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        pass

    @abstractmethod
    def connect_telnet(self, host, username, password, proxy=None, prompt_endings=("#", ">")):
        """
        Connects to a device via the Telnet protocol.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        pass

    @abstractmethod
    def connect(self, host, username, password, protocol=None, proxy=None, prompt_endings=("#", ">")):
        """
        Attempts to connect to a device by any available protocol, starting with SSH2, then SSH1, then telnet

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param protocol: A string with the desired protocol (telnet, ssh1, ssh2, ssh). If left blank it will try all
                         starting with SSH2, then SSH1 then Telnet.  "ssh" means SSH2 then SSH1.
        :type protocol: str
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        pass

    @abstractmethod
    def disconnect(self, command="exit"):
        """
        Disconnects the connected session by sending the "exit" command to the remote device.  If that does not make
        the disconnect happen, attempt to force and ungraceful disconnect.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        pass


    @abstractmethod
    def message_box(self, message, title="", options=0):
        """
        Prints a message for the user.  In SecureCRT, the message is displayed in a pop-up message box.  When used in a
        DirectSession, the message is printed to the console and the user is prompted to type the button that would be
        selected.

        This window can be customized by setting the "options" value, using the constants listed at the top of the
        sessions.py file.  One constant from each of the 3 categories can be OR'd (|) together to make a single option
        value that will format the message box.

        :param message: The message to send to the user
        :type message: str
        :param title: Title for the message box
        :type title: str
        :param options: Sets the display format of the messagebox. (See Message Box constants in sessions.py)
        :type options: int

        :return: The return code that identifies which button the user pressed. (See Message Box constants)
        :rtype: int
        """
        # TODO Re-write this function to avoid needing to import constants to know how to modify the message box.
        pass

    @abstractmethod
    def prompt_window(self, message, title="", hide_input=False):
        """
        Prompts the user for an input value.  In SecureCRT this will open a pop-up window where the user can input the
        requested information.  In a direct session, the user will be prompted at the console for input.

        The "hide_input" input will mask the input, so that passwords or other senstive information can be requested.

        :param message: The message to send to the user
        :type message: str
        :param title: Title for the prompt window
        :type title: str
        :param hide_input: Specifies whether to hide the user input or not.  Default is False.
        :type hide_input: bool

        :return: The value entered by the user
        :rtype: str
        """
        pass

    @abstractmethod
    def file_open_dialog(self, title, button_label="Open", default_filename="", file_filter=""):
        """
        Prompts the user to select a file that will be processed by the script.  In SecureCRT this will give a pop-up
        file selection dialog window.  For a direct session, the user will be prompted for the full path to a file.
        See the SecureCRT built-in Help at Scripting > Script Objects Reference > Dialog Object for more details.

        :param title: <String> Title for the File Open dialog window (Only displays in Windows)
        :param button_label: <String> Label for the "Open" button
        :param default_filename: <String> If provided a default filename, the window will open in the parent directory
            of the file, otherwise the current working directory will be the starting directory.
        :param file_filter: <String> Specifies a filter for what type of files can be selected.  The format is:
            <Name of Filter> (*.<extension>)|*.<extension>||
            For example, a filter for CSV files would be "CSV Files (*.csv)|*.csv||" or multiple filters can be used:
            "Text Files (*.txt)|*.txt|Log File (*.log)|*.log||"

        :return: The absolute path to the file that was selected
        :rtype: str
        """
        pass

    @abstractmethod
    def create_new_saved_session(self, session_name, ip, protocol="SSH2", folder="_imports"):
        """
        Creates a session object that can be opened from the Connect menu in SecureCRT.

        :param session_name: The name of the session
        :type session_name: str
        :param ip: The IP address or hostname of the device represented by this session
        :type ip: str
        :param protocol: The protocol to use for this connection (TELNET, SSH1, SSH2, etc)
        :type protocol: str
        :param folder: The folder (starting from the configured Sessions folder) where this session should be saved.
        :type folder: str
        """
        pass


class CRTScript(Script):
    """
    This class is a sub-class of the Script base class, and is meant to be used in any scripts that are being executed
    from inside of SecureCRT.  This sub-class is designed to interact with the SecureCRT application itself (not with
    tabs that have connections to remote devices) and represent a script being executed from within SecureCRT.  This
    class inherits the methods from the Script class that are documented above, and is required to implement all of the
    abstract classes defined in the Script class.
    """

    def __init__(self, crt):
        self.crt = crt
        super(CRTScript, self).__init__(crt.ScriptFullName)
        self.logger.debug("<SCRIPT_INIT> Starting creation of CRTScript object")

        # Set up SecureCRT tab for interaction with the scripts
        self.main_session = sessions.CRTSession(self, self.crt.GetScriptTab())

    def __post_connect_check(self, endings):
        """
        Validates that we've gotten to the prompt after a connection is made.

        :param endings: A list of strings, where each string is a possible character that would be found at the end
                        of the CLI prompt for the remote device.
        :type endings: list
        """
        self.logger.debug("<CONN_CHECK> Started looking for following prompt endings: {0}".format(endings))
        at_prompt = False
        while not at_prompt:
            found = self.main_session.screen.WaitForStrings(endings, self.main_session.response_timeout)
            if not found:
                raise sessions.InteractionError("Timeout reached looking for prompt endings: {0}".format(endings))
            else:
                test_string = "!@&^"
                self.main_session.screen.Send(test_string + "\b" * len(test_string))
                result = self.main_session.screen.WaitForStrings(test_string, self.main_session.response_timeout)
                if result:
                    self.logger.debug("<CONN_CHECK> At prompt.  Continuing".format(result))
                    at_prompt = True

    def __connect_ssh_2(self, host, username, password, proxy=None, prompt_endings=("#", "# ", ">")):
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        expanded_endings = []
        for ending in prompt_endings:
            expanded_endings.append("{0}".format(ending))
            expanded_endings.append("{0} ".format(ending))

        # If we have a proxy object, verify
        if proxy:
            ssh2_string = "/FIREWALL=Session:\"{0}\" /SSH2 /ACCEPTHOSTKEYS  /L {1} /PASSWORD {2} {3}"\
                .format(proxy, username, password, host)
        else:
            ssh2_string = "/SSH2 /ACCEPTHOSTKEYS /L {0} /PASSWORD {1} {2}".format(username, password, host)

        # If the tab is already connected, then give an exception that we cannot connect.
        if self.main_session.is_connected():
            self.logger.debug("<CONNECT_SSH2> Session already connected.  Raising exception")
            raise ConnectError("Tab is already connected to another device.")
        else:
            try:
                self.logger.debug("<CONNECT_SSH2> Attempting Connection to: {0}@{1} via SSH2".format(username, host))
                tab = self.main_session.session.ConnectInTab(ssh2_string)
                tab_index = tab.Index
                self.main_session = sessions.CRTSession(self, self.crt.GetTab(tab_index), prompt_endings=prompt_endings)
            except:
                error = self.crt.GetLastErrorMessage()
                raise ConnectError(error)

        self.main_session.wait_for_connected()
        # Set Tab parameters to allow correct sending/receiving of data via SecureCRT
        self.main_session.screen.Synchronous = True
        self.main_session.screen.IgnoreEscape = True
        self.logger.debug("<CONNECT_SSH2> Set Synchronous and IgnoreEscape")

        # Make sure banners have printed and we've reached our expected prompt.
        self.__post_connect_check(expanded_endings)

    def __connect_ssh_1(self, host, username, password, proxy=None, prompt_endings=("#", "# ", ">")):
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        expanded_endings = []
        for ending in prompt_endings:
            expanded_endings.append("{0}".format(ending))
            expanded_endings.append("{0} ".format(ending))

        if proxy:
            ssh1_string="/FIREWALL=Session:\"{0}\" /SSH1 /ACCEPTHOSTKEYS /L {0} /PASSWORD {1} {2}".format(proxy, username,
                                                                                                      password, host)
        else:
            ssh1_string = "/SSH1 /ACCEPTHOSTKEYS /L {0} /PASSWORD {1} {2}".format(username, password, host)

        # If the tab is already connected, then give an exception that we cannot connect.
        if self.main_session.is_connected():
            self.logger.debug("<CONNECT_SSH1> Session already connected.  Raising exception")
            raise ConnectError("Tab is already connected to another device.")
        else:
            try:
                self.logger.debug("<CONNECT_SSH1> Attempting Connection to: {0}@{1} via SSH1".format(username, host))
                tab = self.main_session.session.ConnectInTab(ssh1_string)
                tab_index = tab.Index
                self.main_session = sessions.CRTSession(self, self.crt.GetTab(tab_index), prompt_endings=prompt_endings)
            except:
                error = self.crt.GetLastErrorMessage()
                raise ConnectError(error)

        # Set Tab parameters to allow correct sending/receiving of data via SecureCRT
        self.main_session.screen.Synchronous = True
        self.main_session.screen.IgnoreEscape = True
        self.logger.debug("<CONNECT_SSH1> Set Synchronous and IgnoreEscape")

        # Make sure banners have printed and we've reached our expected prompt.
        self.__post_connect_check(expanded_endings)

    def connect_ssh(self, host, username, password, version=None, proxy=None, prompt_endings=("#", ">")):
        """
        Connects to a device via the SSH protocol. By default, SSH2 will be tried first, but if it fails it will attempt
        to fall back to SSH1.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
            user will be prompted for one.
        :type password: str
        :param version: The SSH version to connect with (1 or 2).  Default is None, which will try 2 first and fallback
            to 1 if that fails.
        :type version: int
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        self.logger.debug("<CONNECT_SSH> Attempting Connection to: {0}@{1}".format(username, host))

        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        if version == 2:
            self.__connect_ssh_2(host, username, password, proxy=proxy, prompt_endings=prompt_endings)
        elif version == 1:
            self.__connect_ssh_1(host, username, password, proxy=proxy, prompt_endings=prompt_endings)
        else:
            try:
                self.__connect_ssh_2(host, username, password, proxy=proxy, prompt_endings=prompt_endings)
            except ConnectError as e:
                self.logger.debug("<CONNECT_SSH> Failure trying SSH2: {0}".format(e.message))
                ssh2_error = e.message
                try:
                    self.__connect_ssh_1(host, username, password, proxy=proxy, prompt_endings=prompt_endings)
                except ConnectError as e:
                    ssh1_error = e.message
                    self.logger.debug("<CONNECT_SSH> Failure trying SSH1: {0}".format(e.message))
                    error = "SSH2 and SSH1 failed.\nSSH2 Failure:{0}\nSSH1 Failure:{1}".format(ssh2_error, ssh1_error)
                    raise ConnectError(error)

    def connect_telnet(self, host, username, password, proxy=None, prompt_endings=("#", ">")):
        """
        Connects to a device via the Telnet protocol.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        if proxy:
            telnet_string="/FIREWALL=Session:\"{0}\" /TELNET {0}".format(proxy, host)
        else:
            telnet_string = "/TELNET {0}".format(host)

        # If the tab is already connected, then give an exception that we cannot connect.
        if self.main_session.is_connected():
            self.logger.debug("<CONNECT_TELNET> Session already connected.  Raising exception")
            raise ConnectError("Tab is already connected to another device.")
        else:
            try:
                self.logger.debug("<CONNECT_TELNET> Attempting Connection to: {0} via TELNET".format(host))
                tab = self.main_session.session.ConnectInTab(telnet_string)
                tab_index = tab.Index
                self.main_session = sessions.CRTSession(self, self.crt.GetTab(tab_index), prompt_endings=prompt_endings)
            except:
                error = self.crt.GetLastErrorMessage()
                raise ConnectError(error)

        # Set Tab parameters to allow correct sending/receiving of data via SecureCRT
        self.main_session.screen.Synchronous = True
        self.main_session.screen.IgnoreEscape = True
        self.logger.debug("<CONNECT_TELNET> Set Synchronous and IgnoreEscape")

        # Handle Login
        self.main_session.telnet_login(username, password)

        # Make sure banners have printed and we've reached our expected prompt.
        self.__post_connect_check(prompt_endings)

    def connect(self, host, username, password, protocol=None, proxy=None, prompt_endings=("#", ">")):
        """
        Attempts to connect to a device by any available protocol, starting with SSH2, then SSH1, then telnet

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param protocol: A string with the desired protocol (telnet, ssh1, ssh2, ssh). If left blank it will try all
                         starting with SSH2, then SSH1 then Telnet.  "ssh" means SSH2 then SSH1.
        :type protocol: str
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if not prompt_endings:
            raise ConnectError("Cannot connect without knowing what character ends the CLI prompt.")

        if not protocol:
            try:
                self.connect_ssh(host, username, password, proxy=proxy, prompt_endings=prompt_endings)
            except ConnectError:
                try:
                    self.connect_telnet(host, username, password, prompt_endings=prompt_endings)
                except ConnectError:
                    raise ConnectError("Unable to make a connection with either SSH or Telnet")
        elif protocol.lower() == "ssh":
            self.connect_ssh(host, username, password, proxy=proxy, prompt_endings=prompt_endings)
        elif protocol.lower() == "ssh2":
            self.connect_ssh(host, username, password, version=2, proxy=proxy, prompt_endings=prompt_endings)
        elif protocol.lower() == "ssh1":
            self.connect_ssh(host, username, password, version=1, proxy=proxy, prompt_endings=prompt_endings)
        elif protocol.lower() == "telnet":
            self.connect_telnet(host, username, password, proxy=proxy, prompt_endings=prompt_endings)
        else:
            raise ConnectError("Unknown protocol specified.")

    def disconnect(self, command="exit"):
        """
        Disconnects the main session used by the script by calling the disconnect method on the session object.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        self.main_session.disconnect(command=command)

    def message_box(self, message, title="", options=0):
        """
        Prints a message for the user.  In SecureCRT, the message is displayed in a pop-up message box with a variety
        of buttons, depending on which options are chosen.   The default is just an "OK" button.

        This window can be customized by setting the "options" value, using the constants listed at the top of the
        sessions.py file.  One constant from each of the 3 categories can be OR'd (|) together to make a single option
        value that will format the message box.

        :param message: The message to send to the user
        :type message: str
        :param title: Title for the message box
        :type title: str
        :param options: Sets the display format of the messagebox. (See Message Box constants in sessions.py)
        :type options: int
        :return: The return code that identifies which button the user pressed. (See Message Box constants)
        :rtype: int
        """
        self.logger.debug("<MESSAGE_BOX> Creating MessageBox with: \nTitle: {0}\nMessage: {1}\nOptions: {2}"
                          .format(title, message, options))
        return self.crt.Dialog.MessageBox(message, title, options)

    def prompt_window(self, message, title="", hide_input=False):
        """
        Prompts the user for an input value.  In SecureCRT this will open a pop-up window where the user can input the
        requested information.

        The "hide_input" input will mask the input, so that passwords or other senstive information can be requested.

        :param message: The message to send to the user
        :type message: str
        :param title: Title for the prompt window
        :type title: str
        :param hide_input: Specifies whether to hide the user input or not.  Default is False.
        :type hide_input: bool
        :return: The value entered by the user
        :rtype: str
        """
        self.logger.debug("<PROMPT> Creating Prompt with message: '{0}'".format(message))
        result = self.crt.Dialog.Prompt(message, title, "", hide_input)
        self.logger.debug("<PROMPT> Captures prompt results: '{0}'".format(result))
        return result

    def file_open_dialog(self, title, button_label="Open", default_filename="", file_filter=""):
        """
        Prompts the user to select a file that will be processed by the script.  In SecureCRT this will give a pop-up
        file selection dialog window, and will return the full path to the file chosen.

        :param title: Title for the File Open dialog window (Only displays in Windows)
        :type title: str
        :param button_label: Label for the "Open" button
        :type button_label: str
        :param default_filename: If provided a default filename, the window will open in the parent directory
            of the file, otherwise the current working directory will be the starting directory.
        :type default_filename: str
        :param file_filter: Specifies a filter for what type of files can be selected.  The format is:
            <Name of Filter> (*.<extension>)|*.<extension>||
            For example, a filter for CSV files would be "CSV Files (*.csv)|*.csv||" or multiple filters can be used:
            "Text Files (*.txt)|*.txt|Log File (*.log)|*.log||"
        :type file_filter: str

        :return: The absolute path to the file that was selected
        :rtype: str
        """
        self.logger.debug("<FILE_OPEN> Creating File Open Dialog with title: '{0}'".format(title))
        if 'darwin' in self.host_os:
            self.message_box(title, "Select File", ICON_INFO)
        result_filename = self.crt.Dialog.FileOpenDialog(title, button_label, default_filename, file_filter)
        return result_filename

    def create_new_saved_session(self, session_name, ip, protocol="SSH2", folder="_imports"):
        """
        Creates a session object that can be opened from the Connect menu in SecureCRT.

        :param session_name: The name of the session
        :type session_name: str
        :param ip: The IP address or hostname of the device represented by this session
        :type ip: str
        :param protocol: The protocol to use for this connection (TELNET, SSH1, SSH2, etc)
        :type protocol: str
        :param folder: The folder (starting from the configured Sessions folder) where this session should be saved.
        :type folder: str
        """
        now = datetime.datetime.now()
        creation_date = now.strftime("%A, %B %d %Y at %H:%M:%S")

        # Create a session from the configured default values.
        new_session = self.crt.OpenSessionConfiguration("Default")

        # Set options based)
        new_session.SetOption("Protocol Name", protocol)
        new_session.SetOption("Hostname", ip)
        desc = ["Created on {0} by script:".format(creation_date), self.crt.ScriptFullName]
        new_session.SetOption("Description", desc)
        session_path = os.path.join(folder, session_name)
        # Save session based on passed folder and session name.
        self.logger.debug("<CREATE_SESSION> Creating new session '{0}'".format(session_path))
        new_session.Save(session_path)


class DebugScript(Script):
    """
    This class is a sub-class of the Script base class, and is meant to be used in any scripts that are being executed
    directly from a local python installation.  This sub-class is designed to simulate the interaction with SecureCRT
    while the script is being run from a local python installation.  For example, when a script attempts to create a
    pop-up message box in SecureCRT, this class will simply print the information to the console (or request information
    from the user via the console).

    This class inherits the methods from the Script class that are documented above, and is required to implement all
    of the abstract classes defined in the Script class.  This way, it is a complete replacement for the CRTScript class
    if a script is run directly.
    """

    def __init__(self, full_script_path):
        super(DebugScript, self).__init__(full_script_path)
        self.logger.debug("<INIT> Building DirectExecution Object")
        self.main_session = sessions.DebugSession(self)

    def connect_ssh(self, host, username, password, version=None, proxy=None, prompt_endings=("#", ">")):
        """
        Pretends to connect to a device via SSH.  Simply tracks that we are now connected to something within this
        session (this method never fails).

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
            user will be prompted for one.
        :type password: str
        :param version: The SSH version to connect with (1 or 2).  Default is None, which will try 2 first and fallback
            to 1 if that fails.
        :type version: int
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if version == 2 or version == 1:
            print("Pretending to log into device {0} with username {1} using SSH{2}.".format(host, username, version))
        else:
            print("Pretending to log into device {0} with username {1} using SSH2.".format(host, username))
        self.main_session.hostname = host
        self.main_session.prompt = host + "#"
        self.main_session._connected = True

    def connect_telnet(self, host, username, password, proxy=None, prompt_endings=("#", ">")):
        """
        Pretends to connect to a device via the Telnet protocol, just like connect_ssh above.  Never fails.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        print("Pretending to log into device {0} with username {1} using TELNET.".format(host, username))
        self.main_session.hostname = host
        self.main_session.prompt = host + "#"
        self.main_session._connected = True

    def connect(self, host, username, password, protocol=None, proxy=None, prompt_endings=("#", ">")):
        """
        Pretends to connect to a device.  Simply marks the state of the session as connected.  Never fails.

        :param host: The IP address of DNS name for the device to connect
        :type host: str
        :param username: The username to login to the device with
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one.
        :type password: str
        :param protocol: A string with the desired protocol (telnet, ssh1, ssh2, ssh). If left blank it will try all
                         starting with SSH2, then SSH1 then Telnet.  "ssh" means SSH2 then SSH1.
        :type protocol: str
        :param proxy: The name of a SecureCRT session object that can be used as a jumpbox to proxy the SSH connection
                      through.  This is the same as selecting a session under the "Firewall" selection under the SSH
                      settings screen for a SecureCRT session.
        :type proxy: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts).
        :type prompt_endings: list
        """
        if proxy:
            print("Using session '{}' as a proxy.")

        if not protocol:
            print("Pretending to log into device {0} with username {1} using ANY.".format(host, username, protocol))
        else:
            print("Pretending to log into device {0} with username {1} using {2}.".format(host, username, protocol))
        self.main_session._connected = True

    def disconnect(self, command="exit"):
        """
        Disconnects the main session used by the script by calling the disconnect method on the session object.

        :param command: The command to be issued to the remote device to disconnect.  The default is 'exit'
        :type command: str
        """
        self.main_session.disconnect(command=command)

    def message_box(self, message, title="", options=0):
        """
        Prints a message for the user.  When used in a DirectSession, the message is printed to the console and the
        user is prompted to type the button that would be selected.

        This window can be customized by setting the "options" value, using the constants listed at the top of the
        sessions.py file.  One constant from each of the 3 categories can be OR'd (|) together to make a single option
        value that will format the message box.

        :param message: The message to send to the user
        :type message: str
        :param title: Title for the message box
        :type title: str
        :param options: Sets the display format of the messagebox. (See Message Box constants in sessions.py)
        :type options: int

        :return: The return code that identifies which button the user pressed. (See Message Box constants)
        :rtype: int
        """
        def get_button_layout(option):
            # These numbers signify default buttons and icons shown.  We don't care about these when using console.
            numbers = [512, 256, 64, 48, 32, 16]

            for number in numbers:
                if option >= number:
                    option -= number

            return option

        def get_response_code(text):
            responses = {"OK": IDOK, "Cancel": IDCANCEL, "Yes": IDYES, "No": IDNO, "Retry": IDRETRY, "Abort": IDABORT,
                         "Ignore": IDIGNORE}
            return responses[text]

        self.logger.debug("<MESSAGEBOX> Creating Message Box, with Title: {0}, Message: {1}, and Options: {2}"
                          .format(title, message, options))
        # Extract the layout paramter in the options field
        layout = get_button_layout(options)
        self.logger.debug("<MESSAGEBOX> Layout Value is: {0}".format(layout))

        # A mapping of each integer value and which buttons are shown in a MessageBox, so we can prompt for the
        # same values from the console
        buttons = {BUTTON_OK: ["OK"], BUTTON_CANCEL: ["OK", "Cancel"],
                   BUTTON_ABORTRETRYIGNORE: ["Abort", "Retry", "Ignore"],
                   BUTTON_YESNOCANCEL: ["Yes", "No", "Cancel"], BUTTON_YESNO: ["Yes", "No"],
                   BUTTON_RETRYCANCEL: ["Retry", "Cancel"]}

        print("{0}: {1}".format(message, title))
        response = ""
        while response not in buttons[layout]:
            response = input("Choose from {0}: ".format(buttons[layout]))
            self.logger.debug("<MESSAGEBOX> Received: {0}".format(response))

        code = get_response_code(response)
        self.logger.debug("<MESSAGEBOX> Returning Response Code: {0}".format(code))
        return code

    def prompt_window(self, message, title="", hide_input=False):
        """
        Prompts the user for an input value.  In a direct session, the user will be prompted at the console for input.

        The "hide_input" input will mask the input, so that passwords or other senstive information can be requested.

        :param message: The message to send to the user
        :type message: str
        :param title: Title for the prompt window
        :type title: str
        :param hide_input: Specifies whether to hide the user input or not.  Default is False.
        :type hide_input: bool

        :return: The value entered by the user
        :rtype: str
        """
        self.logger.debug("<PROMPT> Creating Prompt with message: '{0}'".format(message))
        if hide_input:
            result = getpass.getpass(message)
            self.logger.debug("<PROMPT> Captures hidden result (likely a password)".format(result))
        else:
            result = input("{0}: ".format(message))
            self.logger.debug("<PROMPT> Captures prompt results: '{0}'".format(result))

        return result

    def file_open_dialog(self, title, button_label="Open", default_filename="", file_filter=""):
        """
        Prompts the user to select a file that will be processed by the script.  In a direct session, the user will be
        prompted for the full path to a file.

        :param title: Title for the File Open dialog window (Only displays in Windows)
        :type title: str
        :param button_label: Label for the "Open" button
        :type button_label: str
        :param default_filename: If provided a default filename, the window will open in the parent directory
            of the file, otherwise the current working directory will be the starting directory.
        :type default_filename: str
        :param file_filter: Specifies a filter for what type of files can be selected.  The format is:
            <Name of Filter> (*.<extension>)|*.<extension>||
            For example, a filter for CSV files would be "CSV Files (*.csv)|*.csv||" or multiple filters can be used:
            "Text Files (*.txt)|*.txt|Log File (*.log)|*.log||"
        :type file_filter: str

        :return: The absolute path to the file that was selected
        :rtype: str
        """
        result_filename = input("{0} (type {0}): ".format(title, file_filter))
        return result_filename

    def ssh_in_new_tab(self, host, username, password, prompt_endings=("#", ">")):
        """
        Pretends to open a new tab.  Since this is being run directly and no tabs exist, the function really does
        nothing but return a new Session object.

        :param host: The IP address of DNS name for the device to connect (only for API compatibility - not used)
        :type host: str
        :param username: The username to login to the device with (only for API compatibility - not used)
        :type username: str
        :param password: The password that goes with the provided username.  If a password is not specified, the
                         user will be prompted for one. (only for API compatibility - not used)
        :type password: str
        :param prompt_endings: A list of strings that are possible prompt endings to watch for.  The default is for
                               Cisco devices (">" and "#"), but may need to be changed if connecting to another
                               type of device (for example "$" for some linux hosts). (only for API compatibility
                               - not used)
        :type prompt_endings: list
        """
        return sessions.DebugSession(self)

    def create_new_saved_session(self, session_name, ip, protocol="SSH2", folder="_imports"):
        """
        Pretends to create a new SecureCRT session.  Since we aren't running in SecureCRT, it does nothing except
        print a message that a device was created.

        :param session_name: The name of the session
        :type session_name: str
        :param ip: The IP address or hostname of the device represented by this session
        :type ip: str
        :param protocol: The protocol to use for this connection (TELNET, SSH1, SSH2, etc)
        :type protocol: str
        :param folder: The folder (starting from the configured Sessions folder) where this session should be saved.
        :type folder: str
        """
        print("Pretending to save session {0} with hostname: {1}, protocol: {2}, under folder: {3}"\
              .format(session_name, ip, protocol, folder))

