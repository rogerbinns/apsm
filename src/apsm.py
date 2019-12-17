#!/usr/bin/env python3

import sys
import os
import logging
import collections
import json
import copy
import subprocess
import time

import requests  # apt install python3-requests

opj = os.path.join


class EndPoint:
    def __init__(self, api_keys, endpoint):
        self.endpoint = f"http://{ endpoint }"
        # make a copy because we modify later
        self.api_keys = [a for a in api_keys]

    def ping(self):
        return self._get("/rest/system/ping")

    def _get(self, uri):
        url = f"{self.endpoint}{uri}"
        for a in range(len(self.api_keys)):
            r = requests.get(url, headers={"X-API-Key": self.api_keys[a]})
            if r.status_code == 403:
                continue
            if a != 0:
                ak = self.api_keys
                self.api_keys = [ak[a]] + ak[:a] + ak[a + 1:]
            return r.json()

        txt = f"Unable to connect to { url } after trying { len(self.api_keys) } keys"
        logging.error(txt)
        raise Exception(txt)

    def _post(self, uri, data=None):
        url = f"{self.endpoint}{uri}"
        for a in range(len(self.api_keys)):
            r = requests.post(url,
                              data=data,
                              headers={"X-API-Key": self.api_keys[a]})
            if r.status_code == 403:
                continue
            if a != 0:
                ak = self.api_keys
                self.api_keys = [ak[a]] + ak[:a] + ak[a + 1:]
            if r.status_code != 200:
                raise Exception(r.text)
            return
        else:
            raise Exception(
                f"Unable to connect to { url } after trying { len(self.api_keys()) } keys"
            )

    def get_config(self):
        return self._get("/rest/system/config")

    def status(self):
        return self._get("/rest/system/status")

    def pause(self):
        self._post("/rest/system/pause")

    def restart(self):
        self._post("/rest/system/restart")

    def update_config(self, config):
        self._post("/rest/system/config", json.dumps(config).encode("utf8"))


def read_api_keys(f) -> list:
    res = []
    for line in f:
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        res.append(line.split("#")[0].strip())
    return res


def cli_import(options):
    keys = read_api_keys(options.api_keys_file)

    configs = []
    for endpoint in options.endpoints:
        logging.info(f"Checking { endpoint }")
        ep = EndPoint(keys, endpoint)
        ep.ping()
        configs.append({"id": ep.status()["myID"], "config": ep.get_config()})

    cfg = {"devices": {}, "folders": {}}

    for config in configs:
        for device in config["config"]["devices"]:
            did = device["deviceID"]
            if did not in cfg["devices"]:
                cfg["devices"][did] = {"name": collections.Counter()}
            cfg["devices"][did]["name"][device["name"]] += 1

        for folder in config["config"]["folders"]:
            fid = folder["id"]
            if fid not in cfg["folders"]:
                cfg["folders"][fid] = {
                    "label": collections.Counter(),
                    "devices": collections.Counter()
                }
            cfg["folders"][fid]["label"][folder["label"]] += 1
            for device in folder["devices"]:
                cfg["folders"][fid]["devices"][device["deviceID"]] += 1

    cfg = gen_config(cfg)

    if options.base_config:
        base = json.load(options.base_config)
        cfg = merge_config(base, cfg)

    print(json.dumps(cfg, sort_keys=True, indent=4))


def gen_config(cfg):
    deviceid_to_name = {}

    devices = {}
    folders = {}

    for did, d in cfg["devices"].items():
        n = d["name"].most_common()
        if not n[0][0]:
            continue
        assert n[0][0] not in devices  # duplicate names
        devices[n[0][0]] = {"id": did}
        deviceid_to_name[did] = n[0][0]
        if len(n) > 1:
            devices[n[0][0]]["# other names"] = [l[0] for l in n[1:]]

    for fid, f in cfg["folders"].items():
        n = f["label"].most_common()
        while n[0][0] in folders:
            n[0][0] += "_"
        rec = {"id": fid, "sync": []}
        if len(n) > 1:
            rec["# other names"] = [l[0] for l in n[1:]]
        for did, _ in f["devices"].most_common():
            rec["sync"].append(deviceid_to_name[did])
        if rec["sync"]:
            folders[n[0][0]] = rec

    return {"devices": devices, "folders": folders}


def merge_config(base, cfg):
    res = copy.deepcopy(base)
    cfg = copy.deepcopy(cfg)

    for n in "devices", "blacklist", "folders":
        if n not in res:
            res[n] = dict()
        assert isinstance(res[n], dict)

    for name, device in cfg["devices"].items():
        best = None
        for rdevice in res["devices"].values():
            if rdevice.get("id") == device["id"]:
                best = rdevice
                break
        else:
            if name in res["devices"]:
                best = res["devices"][name]
            else:
                res["devices"][name] = device
                continue
        best.update(device)

    for name, folder in cfg["folders"].items():
        best = None
        for rname, rfolder in res["folders"].items():
            if rfolder.get("id") == folder["id"]:
                best = rfolder
                break
        else:
            if name in res["folders"]:
                best = res["folders"][name]
            else:
                res["folders"][name] = folder
                continue

        sync = folder.pop("sync")
        best.update(folder)
        for n in ("sync", ):
            if n not in best:
                best[n] = []

        for s in sync:
            if s not in best["sync"]:
                best["sync"].append(s)

    for folder in res["folders"].values():
        if "sync" not in folder:
            continue
        folder["sync"].sort()

    return res


def cli_rename(options):
    keys = read_api_keys(options.api_keys_file)
    ep = EndPoint(keys, options.endpoint)
    ep.ping()

    config = ep.get_config()

    for folder in config["folders"]:
        label = folder["label"]
        path = folder["path"]

        path = path.rstrip("/")

        if os.path.basename(path) == label:
            continue
        print(label, folder["id"], path)
        existing_folder = os.path.dirname(path)
        res = ask_folder(path)
        if res == path:
            continue
        newfolder = os.path.dirname(res)
        if existing_folder != newfolder:
            print(f"  !!! Folder changed to { newfolder }")
        check = input(f"Confirm rename to { res }? Y/n ").strip()
        if check != "Y":
            print("Not doing rename")
            continue

        for checkf in config["folders"]:
            if checkf["path"] == res:
                print("Path already used by", checkf["id"], checkf["label"])
                sys.exit(5)

        if os.path.exists(res):
            sys.exit(f"Destination { res } already exists")

        print("Pausing all syncthing devices")
        ep.pause()
        print("Pausing folder")
        cfg_paused = copy.deepcopy(config)
        for candidate in cfg_paused["folders"]:
            if candidate["id"] == folder["id"]:
                candidate["paused"] = True
                break
        else:
            raise Exception("Couldn't find our folder")  # coding error

        make_backup(options, ep)
        try:
            ep.update_config(cfg_paused)
            time.sleep(1)  # give time for backup timestamp to increment
            run(["mv", path, res])
            folder["path"] = res
            ep.update_config(config)
        except Exception:
            logging.exception(
                "Syncthing still paused and config / filesystem inconsistent.  Giving up"
            )
            raise

        print("Restarting synthing")
        ep.restart()
        print()


def cli_orphans(options):
    keys = read_api_keys(options.api_keys_file)
    ep = EndPoint(keys, options.endpoint)
    ep.ping()

    config = ep.get_config()

    used = set()
    dirs = set()

    for folder in config["folders"]:
        dirs.add(os.path.dirname(folder["path"]))
        used.add(folder["path"].rstrip("/"))

    if options.directories:
        dirs.update(options.directories)

    for folder in sorted(dirs):
        for d in os.listdir(folder):
            dd = opj(folder, d)
            if os.path.isdir(opj(dd, ".stfolder")) and not dd in used:
                print(dd)


def cli_update(options):
    keys = read_api_keys(options.api_keys_file)

    target = json.load(options.config)

    for endpoint in options.endpoints:
        ep = EndPoint(keys, endpoint)
        ep.ping()
        config = ep.get_config()
        status = ep.status()

        print("==== Processing", name_from_id(target, status["myID"]))

        tilde = status["tilde"]
        defpath = config["options"]["defaultFolderPath"].replace("~", tilde)
        actions, new_config = get_update(options, config, target,
                                         status["myID"], defpath)
        if new_config and new_config != config:
            print("Updating", name_from_id(target, status["myID"]))
            for a in actions:
                print("   ", a)
            if ask_yes_no("Proceed"):
                make_backup(options, ep)
                ep.update_config(new_config)
                ep.restart()
        else:
            print("No changes for", name_from_id(target, status["myID"]))

        print()


def name_from_id(target, id) -> str:
    for name, device in target["devices"].items():
        if device.get("id") == id:
            return name
    return f"Device Id { id }"


def get_update(options, config, target, myid, tilde):
    actions = []
    res = copy.deepcopy(config)

    def name_to_id(name):
        dev = target["devices"].get(name)
        if dev and "id" in dev:
            return dev["id"]
        return None

    def id_to_name(id):
        for name, dev in target["devices"].items():
            if dev and "id" in dev and dev["id"] == id:
                return name
        return None

    def id_to_pretty_name(id):
        n = id_to_name(id)
        return n if n else f"id {id}"

    def id_to_label(id):
        for name, folder in target["folders"].items():
            if folder and "id" in folder and folder["id"] == id:
                return name
        return None

    def id_to_folder(id):
        for folder in target["folders"].values():
            if folder and "id" in folder and folder["id"] == id:
                return folder
        return None

    def id_to_device(id):
        for dev in target["devices"].values():
            if dev and "id" in dev and dev["id"] == id:
                return dev
        return None

    def device_ids_for_folder(id):
        folder = id_to_folder(id)
        if not folder: return None
        dev_ids = set()
        for dev in folder.get("sync", []):
            i = name_to_id(dev)
            if i:
                dev_ids.add(i)
        return sorted(dev_ids)

    has_ids = set()
    for i in range(len(res["devices"]) - 1, -1, -1):
        rec = res["devices"][i]
        if not id_to_device(rec["deviceID"]):
            actions.append(
                f"Remove device { id_to_pretty_name(rec['deviceID']) }")
            del res["devices"][i]
            continue

        has_ids.add(rec["deviceID"])

        name = id_to_name(rec["deviceID"])
        if rec["name"] != name:
            actions.append(f"Updated name for { name }")
            res["devices"][i]["name"] = name

    for n in target["devices"]:
        id = name_to_id(n)
        if id and id not in has_ids:
            actions.append(f"Add device { id_to_pretty_name(id) }")
            res["devices"].append({"deviceID": id, 'name': n})

    has_ids = set()

    for i in range(len(res["folders"]) - 1, -1, -1):
        rec = res["folders"][i]
        if not id_to_folder(rec["id"]):
            actions.append(
                f"Remove folder id { rec['id']} path { rec ['path'] }")
            del res["folders"][i]
            continue

        has_ids.add(rec["id"])

        label = id_to_label(rec["id"])
        if rec["label"] != label:
            actions.append(f"Updated label for { label }")
            rec["label"] = label

        sync_ids = device_ids_for_folder(rec["id"])
        have = set()
        syncs = []
        for s in rec["devices"]:
            if s["deviceID"] in sync_ids:
                syncs.append(s)
                have.add(s["deviceID"])
                continue
            else:
                actions.append(
                    "Remove device %s from folder %s" %
                    (id_to_pretty_name(s["deviceID"]), id_to_label(rec["id"])))

        for s in sync_ids:
            if s not in have:
                actions.append("Added device %s to folder %s" %
                               (id_to_name(s), id_to_label(rec["id"])))
                syncs.append({"deviceID": s})

        rec["devices"] = syncs

    for label, folder in target["folders"].items():
        if "id" not in folder:
            continue
        id = folder["id"]
        if id not in has_ids:
            syncs = device_ids_for_folder(folder["id"])
            if not syncs:
                continue
            print(f"Adding folder { label } with { len(syncs) } devices")
            path = ask_folder(opj(tilde, label), tilde, label)
            actions.append(
                f"Add folder { label } id { id } at { path } ({ len(syncs) } devices)"
            )
            res["folders"].append({
                "id": id,
                'label': label,
                'path': path,
                "devices": [{
                    "deviceID": id
                } for id in syncs]
            })

    return actions, res


def cli_verify(options):
    target = json.load(options.config)
    verify_target(target)


def verify_target(target):
    devices = target["devices"].keys()
    used_devices = set()

    nosuchdev = collections.Counter()

    for name, folder in target["folders"].items():
        if not folder.get("id"):
            print(f"No id specified for folder { name }")
            continue
        if not folder.get("sync"):
            print(f"No syncs specified for folder { name }")
            continue
        dev_exists = 0
        for dev in folder["sync"]:
            if dev not in devices:
                nosuchdev[dev] += 1
            else:
                used_devices.add(dev)
                dev_exists += 1
        if not dev_exists:
            print(f"Folder { name } doesn't have any known devices syncing")

    if nosuchdev:
        print("Unknown devices in folder syncs but no device & id")
        print(nosuchdev.most_common())

    not_used = set(devices) - used_devices
    if not_used:
        print("Devices defined but not used")
        print(not_used)


def cli_restore(options):
    keys = read_api_keys(options.api_keys_file)
    ep = EndPoint(keys, options.endpoint)
    ep.ping()

    id = ep.status()["myID"]
    if id not in options.config:
        sys.exit(
            f"""Device id is { id }\nNot restoring because that id needs to be in filename"""
        )
    config = json.load(open(options.config, "rt"))
    make_backup(options, ep)
    ep.update_config(config)


def make_backup(options, ep):
    config = ep.get_config()
    id = ep.status()["myID"]
    if not os.path.isdir(options.backup_directory):
        os.makedirs(options.backup_directory)
    with open(
            opj(options.backup_directory,
                f"config-{ id }-{ time.strftime('%Y%m%d-%H%m') }.json"),
            "wt") as f:
        json.dump(config, f, indent=4, sort_keys=True)


def run(cmd, **kwargs):
    print(f">>> { cmd }")
    subprocess.check_call(cmd, **kwargs)


def ask_yes_no(question, default=False):
    r = input(f"{ question } y/N? ")
    return True if r.strip() == "Y" else default


def ask_folder(value, basedir=None, label=None):
    basedir = basedir or os.path.dirname(value)
    label = label or os.path.basename(value)

    while True:
        res = input(f"[{ value }] ? ").strip()
        if not res:
            return value
        if '/' not in res:
            value = opj(basedir, res)
            continue
        return res


if __name__ == '__main__':
    import argparse

    p = argparse.ArgumentParser()
    p.set_defaults(func=lambda o: p.print_help())
    p.add_argument("--log-level",
                   choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                   help="Set the logging level")

    p.add_argument("--backup-directory",
                   default=os.path.expanduser("~/.config/apsm"),
                   help="Directory for backup of configs [%(default)s]")

    subs = p.add_subparsers()

    s = subs.add_parser(
        "import", help="Import configs from devices, printing json to stdout")
    s.set_defaults(func=cli_import)
    s.add_argument(
        "--base-config",
        help=
        "File with existing config.  Output will update this with new info",
        type=argparse.FileType("rb"))
    s.add_argument("api_keys_file",
                   help="File to get api keys from, one per line",
                   type=argparse.FileType("rt"))
    s.add_argument("endpoints",
                   nargs="+",
                   help="list of endpoints ipaddr:port")

    s = subs.add_parser("update", help="Update devices from json config")
    s.set_defaults(func=cli_update)
    s.add_argument("config",
                   help="File with desired json config",
                   type=argparse.FileType("rb"))
    s.add_argument("api_keys_file",
                   help="File to get api keys from, one per line",
                   type=argparse.FileType("rt"))
    s.add_argument("endpoints",
                   nargs="+",
                   help="list of endpoints ipaddr:port")

    s = subs.add_parser("verify", help="Check json config consistency")
    s.set_defaults(func=cli_verify)
    s.add_argument("config",
                   help="File with desired json config",
                   type=argparse.FileType("rb"))

    s = subs.add_parser("rename", help="Renames local folders to match labels")
    s.set_defaults(func=cli_rename)
    s.add_argument("api_keys_file",
                   help="File to get api keys from, one per line",
                   type=argparse.FileType("rt"))
    s.add_argument("endpoint", help="ipaddr:port ")

    s = subs.add_parser("orphans",
                        help="Find local folders no longer referenced")
    s.set_defaults(func=cli_orphans)
    s.add_argument("api_keys_file",
                   help="File to get api keys from, one per line",
                   type=argparse.FileType("rt"))
    s.add_argument("endpoint", help="ipaddr:port ")
    s.add_argument("directories",
                   nargs=argparse.REMAINDER,
                   help="Addiitonal directories to check")
    options = p.parse_args()

    s = subs.add_parser("restore", help="Restore backup config")
    s.set_defaults(func=cli_restore)
    s.add_argument("config", help="filename with json to restore")
    s.add_argument("api_keys_file",
                   help="File to get api keys from, one per line",
                   type=argparse.FileType("rt"))
    s.add_argument("endpoint", help="ipaddr:port ")

    try:
        if options.log_level:
            logging.basicConfig(level=getattr(logging, options.log_level))

        options.func(options)
    except Exception:
        logging.exception("Running command")
        sys.exit(5)
