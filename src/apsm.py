#!/usr/bin/env python3

import sys
import logging
import collections

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
        logging.info(f"Checking to { endpoint }")
        ep = EndPoint(keys, endpoint)
        try:
            ep.ping()
            configs.append({
                "id": ep.status()["myID"],
                "config": ep.get_config()
            })
        except Exception:
            logging.exception("Failed with { endpoint }")
            raise

    cfg = {"devices": {}, "folders": {}}

    for config in configs:
        for device in config["config"]["devices"]:
            did = device["deviceId"]
            if did not in cfg["devices"]:
                cfg["devices"] = {"name": collections.Counter()}
            cfg["devices"][did]["name"][device["name"]]

    import pdb
    pdb.set_trace()


if __name__ == '__main__':
    import argparse

    p = argparse.ArgumentParser()
    p.set_defaults(func=lambda o: p.print_help())
    p.add_argument("--log-level",
                   choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                   help="Set the logging level")
    subs = p.add_subparsers()

    s = subs.add_parser("import", help="Import configs from devices")
    s.set_defaults(func=cli_import)
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
