Another Python Syncthing Manager
================================

Purpose
-------

APSM is a primarily interactive tool for managing groups of syncthing
servers. Syncthing does not have central servers to configure, and
instead each syncthing must be separately configured.  For example
adding a device or folders requires configuring each syncthing,
although features like introducers and auto-accept can help.

APSM has a simple json file you configure with devices, folders and
which devices sync the folders.  You can also have arbitrary comments
and other information.

.. code-block:: json

  {
    "devices": {
        "server1": { "id": "...", "#": "in the left cupboard"},
        "laptop1": { "id": "...." },
        "phone1": {"id": "..."},
        "server2": {"id": "..."}
    },
    "folders": {
        "taxes": { "id": "...", "sync": ["server1", "phone1"],
        "photos": { "id": "...", "sync": ["server1", "server2", "laptop1"]
    }
  }

With this file, APSM will update each syncthing you run against.  They
do not have to all be done at the same time.

* Updates device list and names
* Adds or removes folders
* Updates labels and device list for folders

Caveats
-------

Folder and path logic only works on Unix/Mac (not Windows)

Simultaneous config changes while the script is running
will likely be overwritten, although backups are timely.

Only talking to the `REST api
<https://docs.syncthing.net/dev/rest.html>`__.  No `XML
<https://docs.syncthing.net/users/config.html#config-file-format>`__
is used, understood, or generated.

The code has no comments other than this doc.  There are no tests
as it was developed interactively.


All Features
=============

Backups

    Before making any change, a local file backup is made.  You can
    easily restore, with checks to make sure it is the right file.

Generate configuration

    Point at one or more syncthings and a config is generated merging
    the information from them.  You can also provide an existing
    config which is used a base before merging.

    This means you do most of your configuration using the syncthing
    gui.

Update configuration

    Point at one or more syncthings and they will be updated to match
    the config

Folder rename / relocate

    Checks folder name against label and lets you rename.  The second
    time you get a "phone camera" folder, this helps greatly.

Find orphan folders

    Checks the containing directories you currently use plus any
    on the command line to find subfolders with .stfolder in them
    but are not referenced by the syncthing config.

    When a syncthing folder is removed, the disk folder is left in
    place.  This way you can find them.

Running
=======

python3 & script

--loglevel
----------

--backup-directory
-------------------

api keys file
-------------

endpoints
---------

Commands
========

import 

update

verify

rename

orphans

restore

backup

