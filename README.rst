Introduction
==================
SecureCRT Tools is a collection of Python scripts for automating common Cisco network-device workflows from SecureCRT.
The scripts can collect show-command output, turn common tables into CSV files, create saved sessions, and handle a few
targeted operational workflows such as packet captures and configuration updates.

This fork is aimed at SecureCRT 9.x users.  The current validation target is SecureCRT 9.7.2 x64 build 3858 with Python
3.13.4 64-bit.  Other SecureCRT versions may work, but test in your environment before relying on a script in
production, especially when it changes configuration or starts a packet capture.

SecureCRT 9.x Support
=====================
Older copies of this README warned that SecureCRT 9.x did not work with these scripts because of changes to SecureCRT's
bundled Python interpreter.  That warning is no longer accurate for this fork.

That does not mean every script has been tested across every SecureCRT, Python, platform, and device combination.  If
something fails, please include the SecureCRT version, Python version, script name, device platform, and error details.

What's New In This Fork
=======================
This fork keeps the original SecureCRT Tools workflow and adds updates focused on SecureCRT 9.x, day-to-day switch
operations, and a few stale-data fixes.

New scripts:

* ``s_cisco_packet_capture.py`` runs a guided Cisco IOS/IOS XE Embedded Packet Capture workflow.  It asks for the
  capture name, interface, runtime, buffer size, local storage, and export method, then can leave the PCAP on the device
  or copy it out with SCP, FTP, SFTP, or TFTP.
* ``s_interface_age_csv.py`` combines ``show interfaces link`` and ``show interfaces status`` into an
  ``interface-age`` CSV report, which is useful when reviewing how long ports have been up or down.
* ``s_device_track_csv.py`` exports IOS device-tracking data to CSV.  It tries modern
  ``show device-tracking database`` output first and falls back to legacy ``show ip device tracking all`` output when
  needed.

Updates and fixes:

* SecureCRT 9.x support has been refreshed around SecureCRT 9.7.2 and Python 3.13.4.
* A new global ``response_timeout`` setting controls SecureCRT screen reads and command-response waits.
* Packet capture prompts now enforce configured runtime and buffer limits, warn on risky interface choices, and support
  optional command transcripts.
* Packet capture cleanup behavior is configurable, and command-echo waits now time out instead of hanging indefinitely.
* The bundled MAC/OUI vendor database in ``securecrt_tools/manuf`` has been refreshed.
* ``securecrt_tools/manuf.py`` now downloads updates from Wireshark's current automated ``manuf`` file and handles the
  padded columns used by the current file format.

Upgrade Notes
=============
Very old versions of SecureCRT Tools used per-script JSON settings files.  Current versions use one INI file at
``settings/settings.ini``.  There is no automatic migration from the old JSON layout, so review your settings and remove
or archive old JSON settings files before running the current scripts.

The current framework can initiate SSH and Telnet connections for multi-device scripts, use a SecureCRT saved session as
a jumpbox/proxy, and run a small number of configuration-changing workflows.

If you are looking for previous versions of the scripts, they can be found in the branches below:

* Please see the `Pre-2017` branch if you need to access the original versions (1.0) that were all function based.
* Please see the `2017` branch if you want the original class-based scripts use the JSON based settings files. (2.0)

What These Scripts Do
=====================
The documentation has the full script list, but these are the main things the repository is built for:

* Save command output from one device or many devices into hostname- and timestamp-based files.
* Capture device inventory data (code version, model number, serial number, mfg. date, etc.) for a list of devices provided to the script in CSV format.
* Export ARP, MAC address, VLAN, CDP, EIGRP, interface status, interface age, device-tracking, and switchport mapping data to CSV.
* Create SecureCRT saved sessions from CDP data or from a CSV file.
* Map switchports to attached MAC addresses, IP addresses, DNS names, and MAC vendors.
* Summarize route-table next-hop usage before or after routing changes.
* Run Cisco IOS/IOS XE packet captures and export PCAP files.
* Search devices for existing IP helper/DHCP relay addresses and add or remove relays where needed.

Most of the reusable work lives in the ``securecrt_tools`` package.  It handles settings, output directories, SecureCRT
dialogs, session setup, prompt and hostname detection, command collection, TextFSM parsing, CSV writing, and output
filename creation.  That lets the individual scripts stay focused on the network task instead of repeating SecureCRT API
plumbing.

Using a Jumpbox/Bastion Host
============================
In some cases you can only access a remote device by proxying through a jump box/bastion host.  Fortunately, SecureCRT already has a method of handling this and so I don't have to build the code directly into the securecrt_tools module to do it.  The steps for proxying a connection through another device are:

1) Create an SSH2 session to connect to the jump box.  Make sure you can use this session to connect to the jump box directly.

2) Create a session to connect to the remote device by IP or name (that the jump box can resolve).

3) While editing the remote device session, go to the SSH2/SSH1/Telnet section and look for the `Firewall` drop down.

4) Choose `Select Session` and select the session for the jump box.

5) When you launch the remote device session, you'll first be prompted for the jump box credentials (unless you've saved them) and then you'll be prompted for the remote device credentials.  You should now be connected to the remote device by proxying through the jump box.

For more information, watch the video on VanDyke Software's YouTube channel at `https://youtu.be/XHOVTuv-LKY <https://youtu.be/XHOVTuv-LKY>`_.

Running The Scripts
===================
There are 2 types of scripts in this repository:

1) Scripts that interact with a single device, AFTER you have logged in manually (starts with 's\_'), and

2) Scripts that interact with multiple devices, where the script performs the login action (starts with 'm\_')

A list of all the single- and multi-device scripts and descriptions on what they do can be found in the documentation below.

The run any of these scripts, you need to download the entire repo to your computer.  You can either clone the repository or download an archive to extact on your machine.

**NOTE** While the scripts are running they will lock the tab until they complete.  If for some reason (error, etc) the script ends and the tab is still locked, you can unlock it by going to **File->Unlock Session** in the menus.

Single Device Scripts
*********************
To run SINGLE device scripts, do the following:

1) **AFTER** connecting and logging into a device with SecureCRT, go to the *Scripts* menu and select "Run"

2) Choose the script you want to run (that starts with 's\_')

3) The script looks for your `settings.ini` file. If this file doesn't exist (and it won't the first time you run one of these scripts) the script will create the file.

4) If the script produces an output, it will be saved in the directory specified in the `settings/settings.ini` file.  If this diretory does not exist, you will be prompted to create it.  You can modify this path in the `settings.ini` file to change where the scripts save the output they produce.

The output files are automatically named based on the hostname of the device connected to.   This name is taken from the prompt of the device, so these scripts will work whether you are directly connected, or connected via a jumpbox or other intermediate device.

Multiple Device Scripts
***********************
1) While **NOT** connected to a device, go to the *Scripts* menu and select "Run"

2) The script will prompt you to select a CSV file that contains all the required information for the devices the script should connect to.  You will be prompted for credentials, if required.  **A sample device file can be found at templates/sample_device_list.csv**

3) The script will connect to each device and execute the script logic.  The script will process one device at a time in the same tab.  While this it the case because SecureCRT does not support multi-threading within scripts, you can manually multi-thread by breaking your devices file into multiple files and lauching the same script in multiple tabs with differnet device files.

Settings
========
All settings files are stored in the `settings/settings.ini` file from the root of the scripts directory.

Global Settings
***************

Global settings that are used by all scripts are under the `Global` heading in the `settings.ini` file.  The following options are available in the global settings file:

* '**output_dir**': This is the path where you want the output from scripts to be saved.
* '**date_format**': Default is '%Y-%m-%d-%H-%M-%S'.  This string specifies how the date stamp in output filenames is formatted.
  - %Y - 4-digit Year
  - %m - numeric month
  - %d - day of the month
  - %H - Hours
  - %M - Minutes
  - %S - Seconds
* '**modify_term**': True or False.  When True, the script will attempt to modify the terminal length and width to 0 so that output flows continuously.  When the output is complete the script will return the length and width to their original values.   If False, it will not change the values, but instead auto-advance when a "More" prompt is encountered.
* '**debug_mode**': True or False.  If True, a log file will be written that contains debug messages from the script execution.  This can be helpful for troubleshooting scripts that are failing.  The debug files will be saved in a `debugs` directory under your configured output directory.
* '**use_proxy**': True or False.  If True, scripts that initiate connections (multi-device scripts) will use the `proxy_session` option below to specify which SecureCRT Session to use as a SOCKS proxy.  When enabled, this option uses the `Firewall` setting in the SecureCRT sessions settings to specify the device to proxy the connection through.
* '**proxy_session**': The name of the SecureCRT session that should be used to proxy connections.  This **MUST** be a session that uses SSH2.  Use the forward slash (/) to specify folders in the path to the session, i.e. `proxy_session = Site 1/Core/S1_Core1`.
* '**response_timeout**': Timeout in seconds for SecureCRT screen reads and command-response waits.

Script-Specific Settings
************************

Some scripts have settings that are used to change certain behaviors while running.  If such a settings are used, the setting will be saved under a heading named for the script in the `settings.ini` file.  Details about the settings used by a script are described in the documentation for that script, or in the docstring in the script file itself.

The ``[cisco_packet_capture]`` section controls the packet capture workflow.  It includes runtime limits, buffer-size limits, interface warning behavior, transcript logging, capture cleanup behavior, and whether to delete the local PCAP after a successful remote copy.

Contributing
============
While I've tried to create an assortment of scripts that would be useful to most network professionals, I would love for people to contribute to this repository by adding script and making improvements via pull request. These improvements can include bug fixes or support for additional devices beyond the few Cisco OSes I have access to test against.  The majority of these scripts were created to do things that I've found useful over time, but I'm sure there are plenty more great ideas for scripts that I haven't thought of. 

If you have a need for a script but do not feel confident that you can write one yourself, please post the idea in the issues log and perhaps someone will find the time to write it. Ultimately, if you have the interest, the best way to learn both Python and how to write your own scripts using these tools is by coming up with something you want to build and just keep working at it.  Blank script templates (in the `templates` folder) are provided to help with getting started quickly and all of the existing scripts can be used as examples or modified to suit your needs.  Since there are currently very few contributors to this repository the fastest way to get a new script to do what you need is to try to write it yourself and reach out for feedback and help. I can't guarantee that anyone will have the time to build a suggested script if suggested, but I'd still love to have those ideas posted even if it doesn't meet your timeline.

To help support involvement from others in the community, I've tried to write comprehensive documentation about both the high-level design/logic of the modules and scripts, as well as detailed documentation about all of the functions/methods in the modules. This include docstrings and comments within the code to make it as easy as possible for people new to this repository to understand what it is doing and to understand the existing capabilities thta can be used to save time writing new scripts. Please reach out with any feedback you have on the documentation so it can be continuously improved, even for simple typos and grammar errors that you find (or better yet, create a pull request to fix the file as practice using git and github!)

Documentation
=============

The detailed documentation for this project can be found at `https://securecrt-tools.readthedocs.io/ <https://securecrt-tools.readthedocs.io/>`_.  If you've downloaded the repository, the same documentation can also be accessed offline by opening the `docs/index.html` file with a web browser.
