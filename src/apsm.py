#!/usr/bin/env python3

import sys
import logging
import collections
import json
import copy

import requests  # apt install python3-requests


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
            if r.status_code != 200:
                continue
            if a != 0:
                ak = self.api_keys
                self.api_keys = [ak[a]] + ak[:a] + ak[a + 1:]
            return r.json()
        else:
            raise Exception(
                f"Unable to connect to { url } after trying { len(self.api_keys()) } keys"
            )

    def get_config(self):
        return self._get("/rest/system/config")

    def status(self):
        return self._get("/rest/system/status")


def read_api_keys(f) -> list:
    res = []
    for line in f:
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        res.append(line.split("#")[0].strip())
    return res


def cli_import(options):
    logging.info("Reading api keys")
    keys = read_api_keys(options.api_keys_file)
    logging.debug(f"api keys { keys }")

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
    blacklist = {"devices": [], "folders": []}

    for did, d in cfg["devices"].items():
        n = d["name"].most_common()
        if not n[0][0]:
            blacklist["devices"].append(did)
            continue
        assert n[0][0] not in devices  # duplicate names
        devices[n[0][0]] = {"id": did}
        deviceid_to_name[did] = n[0][0]
        if len(n) > 1:
            devices[n[0][0]]["# other names"] = [l[0] for l in n[1:]]

    for fid, f in cfg["folders"].items():
        n = f["label"].most_common()
        assert n[0][0] not in folders
        rec = {"id": fid, "sync": [], "sync-off": []}
        if len(n) > 1:
            rec["# other names"] = [l[0] for l in n[1:]]
        for did, count in f["devices"].most_common():
            if did not in blacklist["devices"]:
                rec["sync"].append(deviceid_to_name[did])
        for name in deviceid_to_name.values():
            if name not in rec["sync"]:
                rec["sync-off"].append(name)
        if not rec["sync"]:
            blacklist["folders"].append(fid)
        else:
            folders[n[0][0]] = rec

    return {"devices": devices, "folders": folders, "blacklist": blacklist}


def merge_config(base, cfg):
    res = copy.deepcopy(base)
    cfg = copy.deepcopy(cfg)

    for n in "devices", "blacklist", "folders":
        if n not in res:
            res[n] = dict()
        assert isinstance(res[n], dict)

    for name, device in cfg["devices"].items():
        best = None
        for rname, rdevice in res["devices"].items():
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
        sync_off = folder.pop("sync-off")
        best.update(folder)
        for n in "sync", "sync-off":
            if n not in best:
                best[n] = []

        for s in sync:
            if s not in best["sync"]:
                best["sync"].append(s)

        for s in sync_off:
            if s not in best["sync"] and s not in best["sync-off"]:
                best["sync-off"].append(s)

    device_names = [
        name for name, device in cfg["devices"].items() if device.get("id")
    ]

    # ::TODO:: blacklist

    for fname, folder in res["folders"].items():
        remove = []
        if "sync-on" not in folder:
            continue
        for dname in folder["sync-off"]:
            if dname in folder["sync"]:
                remove.append(dname)
        for dname in remove:
            folder["sync-off"].remove(dname)

        for dname in device_names:
            if dname not in folder["sync"] and dname not in folder["sync-off"]:
                folder["sync-off"].append(dname)

        for k in "sync", "sync-off":
            folder[k].sort()

    return res


if __name__ == '__main__':
    import argparse

    p = argparse.ArgumentParser()
    p.set_defaults(func=lambda o: p.print_help())
    p.add_argument("--log-level",
                   choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                   help="Set the logging level")
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

    s = subs.add_parser("rename", help="Renames local folders to match labels")

    s = subs.add_parser("orphans", help="Find local folders no longer used")

    options = p.parse_args()

    try:
        if options.log_level:
            logging.basicConfig(level=getattr(logging, options.log_level))

        options.func(options)
    except Exception:
        logging.exception("Running command")
        sys.exit(5)
