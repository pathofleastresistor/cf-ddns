#!/usr/bin/env python3
"""Cloudflare DNS CLI — scriptable interface for managing DNS records.

Can be run from any directory:
    python /path/to/cf-ddns/cli.py zones list
    python /path/to/cf-ddns/cli.py records list --zone example.com
    python /path/to/cf-ddns/cli.py records create --zone example.com --type A --name www --content 1.2.3.4
    python /path/to/cf-ddns/cli.py records update --zone example.com --id <id> --content 5.6.7.8
    python /path/to/cf-ddns/cli.py records delete --zone example.com --id <id>

Add --json to any command for machine-readable output.
"""

import argparse
import json
import os
import sys

# Load .env from the directory this script lives in, so it works from anywhere
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from dotenv import load_dotenv
load_dotenv(os.path.join(_HERE, ".env"))

from cloudflare import PRIORITY_TYPES, PROXIABLE_TYPES, CloudflareAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api() -> CloudflareAPI:
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not token:
        _die("CLOUDFLARE_API_TOKEN not set in environment or .env")
    return CloudflareAPI(token)


def resolve_zone(api: CloudflareAPI, zone_arg: str) -> dict:
    """Accept zone name (example.com) or zone ID."""
    for zone in api.get_zones():
        if zone["name"] == zone_arg or zone["id"] == zone_arg:
            return zone
    _die(f"Zone '{zone_arg}' not found")


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _print_table(rows: list[dict], fields: list[str]) -> None:
    if not rows:
        print("(no results)")
        return
    widths = {f: len(f) for f in fields}
    for row in rows:
        for f in fields:
            widths[f] = max(widths[f], len(str(row.get(f, ""))))
    header = "  ".join(f.upper().ljust(widths[f]) for f in fields)
    print(header)
    print("  ".join("-" * widths[f] for f in fields))
    for row in rows:
        print("  ".join(str(row.get(f, "")).ljust(widths[f]) for f in fields))


def _out(data, as_json: bool, fields: list[str] | None = None) -> None:
    if as_json:
        print(json.dumps(data, indent=2))
    elif isinstance(data, list):
        _print_table(data, fields or (list(data[0].keys()) if data else []))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")


def _ttl_display(ttl) -> str:
    return "Auto" if ttl == 1 else str(ttl)


def _format_zones(zones: list[dict]) -> list[dict]:
    return [{"name": z["name"], "id": z["id"], "status": z.get("status", "")} for z in zones]


def _format_records(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        out.append({
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "content": r["content"],
            "ttl": _ttl_display(r.get("ttl", 1)),
            "proxied": str(r.get("proxied", "")).lower() if r.get("proxiable") else "—",
            "priority": str(r["priority"]) if "priority" in r else "",
        })
    return out


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_zones_list(args) -> None:
    api = get_api()
    zones = api.get_zones()
    if args.json:
        _out(zones, True)
    else:
        _out(_format_zones(zones), False, ["name", "id", "status"])


def cmd_records_list(args) -> None:
    api = get_api()
    zone = resolve_zone(api, args.zone)
    records = api.get_dns_records(zone["id"])
    if args.type:
        records = [r for r in records if r["type"].upper() == args.type.upper()]
    if args.json:
        _out(records, True)
    else:
        fields = ["id", "name", "type", "content", "ttl", "proxied"]
        _out(_format_records(records), False, fields)


def cmd_records_get(args) -> None:
    api = get_api()
    zone = resolve_zone(api, args.zone)
    records = api.get_dns_records(zone["id"])
    match = next((r for r in records if r["id"] == args.id), None)
    if not match:
        _die(f"Record '{args.id}' not found in zone '{args.zone}'")
    _out(match if args.json else _format_records([match])[0], args.json)


def cmd_records_create(args) -> None:
    api = get_api()
    zone = resolve_zone(api, args.zone)
    data: dict = {
        "type": args.type.upper(),
        "name": args.name,
        "content": args.content,
        "ttl": args.ttl,
    }
    if args.type.upper() in PROXIABLE_TYPES:
        data["proxied"] = args.proxied
    if args.type.upper() in PRIORITY_TYPES:
        if args.priority is None:
            _die(f"--priority is required for {args.type} records")
        data["priority"] = args.priority
    result = api.create_dns_record(zone["id"], data)
    _out(result if args.json else _format_records([result])[0], args.json)


def cmd_records_update(args) -> None:
    api = get_api()
    zone = resolve_zone(api, args.zone)
    # Fetch current record so we only override what was provided
    records = api.get_dns_records(zone["id"])
    current = next((r for r in records if r["id"] == args.id), None)
    if not current:
        _die(f"Record '{args.id}' not found in zone '{args.zone}'")
    data: dict = {
        "type": (args.type or current["type"]).upper(),
        "name": args.name or current["name"],
        "content": args.content or current["content"],
        "ttl": args.ttl if args.ttl is not None else current.get("ttl", 1),
    }
    rec_type = data["type"]
    if rec_type in PROXIABLE_TYPES:
        data["proxied"] = args.proxied if args.proxied is not None else current.get("proxied", False)
    if rec_type in PRIORITY_TYPES:
        data["priority"] = args.priority if args.priority is not None else current.get("priority", 10)
    result = api.update_dns_record(zone["id"], args.id, data)
    _out(result if args.json else _format_records([result])[0], args.json)


def cmd_records_delete(args) -> None:
    api = get_api()
    zone = resolve_zone(api, args.zone)
    result = api.delete_dns_record(zone["id"], args.id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"deleted: {args.id}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # Shared --json flag inherited by every subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Output raw JSON")

    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Cloudflare DNS manager — scriptable CLI",
    )
    sub = parser.add_subparsers(dest="resource", metavar="<resource>", required=True)

    # -- zones ----------------------------------------------------------------
    zones_p = sub.add_parser("zones", help="Manage zones")
    zones_sub = zones_p.add_subparsers(dest="action", metavar="<action>", required=True)

    zones_list = zones_sub.add_parser("list", help="List all zones", parents=[common])
    zones_list.set_defaults(func=cmd_zones_list)

    # -- records --------------------------------------------------------------
    records_p = sub.add_parser("records", help="Manage DNS records")
    records_sub = records_p.add_subparsers(dest="action", metavar="<action>", required=True)

    # records list
    rl = records_sub.add_parser("list", help="List records for a zone", parents=[common])
    rl.add_argument("--zone", required=True, metavar="NAME_OR_ID")
    rl.add_argument("--type", metavar="TYPE", help="Filter by record type (A, CNAME, MX, ...)")
    rl.set_defaults(func=cmd_records_list)

    # records get
    rg = records_sub.add_parser("get", help="Get a single record by ID", parents=[common])
    rg.add_argument("--zone", required=True, metavar="NAME_OR_ID")
    rg.add_argument("--id", required=True, metavar="RECORD_ID")
    rg.set_defaults(func=cmd_records_get)

    # records create
    rc = records_sub.add_parser("create", help="Create a new DNS record", parents=[common])
    rc.add_argument("--zone", required=True, metavar="NAME_OR_ID")
    rc.add_argument("--type", required=True, metavar="TYPE")
    rc.add_argument("--name", required=True, metavar="NAME", help="Subdomain or @ for root")
    rc.add_argument("--content", required=True, metavar="VALUE")
    rc.add_argument("--ttl", type=int, default=1, metavar="SECONDS", help="TTL (1 = Auto)")
    rc.add_argument("--proxied", action="store_true", default=False)
    rc.add_argument("--priority", type=int, metavar="N", help="Required for MX/SRV")
    rc.set_defaults(func=cmd_records_create)

    # records update
    ru = records_sub.add_parser("update", help="Update an existing DNS record", parents=[common])
    ru.add_argument("--zone", required=True, metavar="NAME_OR_ID")
    ru.add_argument("--id", required=True, metavar="RECORD_ID")
    ru.add_argument("--type", metavar="TYPE")
    ru.add_argument("--name", metavar="NAME")
    ru.add_argument("--content", metavar="VALUE")
    ru.add_argument("--ttl", type=int, metavar="SECONDS")
    ru.add_argument("--proxied", action=argparse.BooleanOptionalAction, default=None)
    ru.add_argument("--priority", type=int, metavar="N")
    ru.set_defaults(func=cmd_records_update)

    # records delete
    rd = records_sub.add_parser("delete", help="Delete a DNS record", parents=[common])
    rd.add_argument("--zone", required=True, metavar="NAME_OR_ID")
    rd.add_argument("--id", required=True, metavar="RECORD_ID")
    rd.set_defaults(func=cmd_records_delete)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
