#!/usr/bin/env python3
"""Cloudflare DNS CLI — scriptable interface for managing DNS records and R2.

Can be run from any directory:
    python /path/to/cf-ddns/cli.py zones list
    python /path/to/cf-ddns/cli.py records list --zone example.com
    python /path/to/cf-ddns/cli.py records create --zone example.com --type A --name www --content 1.2.3.4
    python /path/to/cf-ddns/cli.py records update --zone example.com --id <id> --content 5.6.7.8
    python /path/to/cf-ddns/cli.py records delete --zone example.com --id <id>

    python /path/to/cf-ddns/cli.py r2 buckets list
    python /path/to/cf-ddns/cli.py r2 buckets create --name my-bucket
    python /path/to/cf-ddns/cli.py r2 buckets delete --name my-bucket
    python /path/to/cf-ddns/cli.py r2 objects list --bucket my-bucket
    python /path/to/cf-ddns/cli.py r2 objects upload --bucket my-bucket --key path/to/file --file ./local.txt
    python /path/to/cf-ddns/cli.py r2 objects download --bucket my-bucket --key path/to/file --out ./local.txt
    python /path/to/cf-ddns/cli.py r2 objects delete --bucket my-bucket --key path/to/file

Add --json to any command for machine-readable output.
CLOUDFLARE_ACCOUNT_ID must be set for R2 commands.
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

import credentials
from cloudflare import PRIORITY_TYPES, PROXIABLE_TYPES, CloudflareAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api() -> CloudflareAPI:
    token = credentials.manager_token()
    if not token:
        _die(f"no token: set CLOUDFLARE_API_TOKEN or save one to {credentials.config_path('token')}")
    return CloudflareAPI(token, account_id=credentials.account_id())


def get_api_r2() -> CloudflareAPI:
    api = get_api()
    if not api.account_id:
        _die(f"no account id: set CLOUDFLARE_ACCOUNT_ID or save it to {credentials.config_path('account_id')}")
    return api


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
# R2 command handlers
# ---------------------------------------------------------------------------

def cmd_r2_buckets_list(args) -> None:
    api = get_api_r2()
    buckets = api.list_r2_buckets()
    if args.json:
        _out(buckets, True)
    else:
        _out(
            [{"name": b["name"], "location": b.get("location", ""), "created": b.get("creation_date", "")} for b in buckets],
            False,
            ["name", "location", "created"],
        )


def cmd_r2_buckets_create(args) -> None:
    api = get_api_r2()
    result = api.create_r2_bucket(args.name, location=args.location)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"created: {args.name}")


def cmd_r2_buckets_delete(args) -> None:
    api = get_api_r2()
    api.delete_r2_bucket(args.name)
    if args.json:
        print(json.dumps({"name": args.name}, indent=2))
    else:
        print(f"deleted: {args.name}")


def cmd_r2_objects_list(args) -> None:
    api = get_api_r2()
    objects = api.list_r2_objects(args.bucket, prefix=args.prefix or "")
    if args.json:
        _out(objects, True)
    else:
        _out(
            [{"key": o["key"], "size": o.get("size", ""), "modified": o.get("uploaded", "")} for o in objects],
            False,
            ["key", "size", "modified"],
        )


def cmd_r2_objects_upload(args) -> None:
    api = get_api_r2()
    with open(args.file, "rb") as f:
        data = f.read()
    import mimetypes
    content_type = mimetypes.guess_type(args.file)[0] or "application/octet-stream"
    api.upload_r2_object(args.bucket, args.key, data, content_type=content_type)
    if args.json:
        print(json.dumps({"bucket": args.bucket, "key": args.key}, indent=2))
    else:
        print(f"uploaded: {args.key} → {args.bucket}")


def cmd_r2_objects_download(args) -> None:
    api = get_api_r2()
    data = api.download_r2_object(args.bucket, args.key)
    out_path = args.out or args.key.split("/")[-1]
    with open(out_path, "wb") as f:
        f.write(data)
    if args.json:
        print(json.dumps({"bucket": args.bucket, "key": args.key, "out": out_path}, indent=2))
    else:
        print(f"downloaded: {args.key} → {out_path}")


def cmd_r2_objects_delete(args) -> None:
    api = get_api_r2()
    api.delete_r2_object(args.bucket, args.key)
    if args.json:
        print(json.dumps({"bucket": args.bucket, "key": args.key}, indent=2))
    else:
        print(f"deleted: {args.key}")


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

    # -- r2 ------------------------------------------------------------------
    r2_p = sub.add_parser("r2", help="Manage R2 storage")
    r2_sub = r2_p.add_subparsers(dest="r2_resource", metavar="<resource>", required=True)

    # r2 buckets
    r2_buckets_p = r2_sub.add_parser("buckets", help="Manage R2 buckets")
    r2_buckets_sub = r2_buckets_p.add_subparsers(dest="action", metavar="<action>", required=True)

    r2_bl = r2_buckets_sub.add_parser("list", help="List R2 buckets", parents=[common])
    r2_bl.set_defaults(func=cmd_r2_buckets_list)

    r2_bc = r2_buckets_sub.add_parser("create", help="Create an R2 bucket", parents=[common])
    r2_bc.add_argument("--name", required=True, metavar="NAME")
    r2_bc.add_argument("--location", metavar="HINT", help="Location hint (e.g. WNAM, ENAM, WEUR, EEUR, APAC)")
    r2_bc.set_defaults(func=cmd_r2_buckets_create)

    r2_bd = r2_buckets_sub.add_parser("delete", help="Delete an R2 bucket", parents=[common])
    r2_bd.add_argument("--name", required=True, metavar="NAME")
    r2_bd.set_defaults(func=cmd_r2_buckets_delete)

    # r2 objects
    r2_objects_p = r2_sub.add_parser("objects", help="Manage R2 objects")
    r2_objects_sub = r2_objects_p.add_subparsers(dest="action", metavar="<action>", required=True)

    r2_ol = r2_objects_sub.add_parser("list", help="List objects in a bucket", parents=[common])
    r2_ol.add_argument("--bucket", required=True, metavar="NAME")
    r2_ol.add_argument("--prefix", metavar="PREFIX", help="Filter by key prefix")
    r2_ol.set_defaults(func=cmd_r2_objects_list)

    r2_ou = r2_objects_sub.add_parser("upload", help="Upload a file to R2", parents=[common])
    r2_ou.add_argument("--bucket", required=True, metavar="NAME")
    r2_ou.add_argument("--key", required=True, metavar="KEY")
    r2_ou.add_argument("--file", required=True, metavar="PATH", help="Local file to upload")
    r2_ou.set_defaults(func=cmd_r2_objects_upload)

    r2_od = r2_objects_sub.add_parser("download", help="Download an object from R2", parents=[common])
    r2_od.add_argument("--bucket", required=True, metavar="NAME")
    r2_od.add_argument("--key", required=True, metavar="KEY")
    r2_od.add_argument("--out", metavar="PATH", help="Local output path (default: filename from key)")
    r2_od.set_defaults(func=cmd_r2_objects_download)

    r2_odel = r2_objects_sub.add_parser("delete", help="Delete an object from R2", parents=[common])
    r2_odel.add_argument("--bucket", required=True, metavar="NAME")
    r2_odel.add_argument("--key", required=True, metavar="KEY")
    r2_odel.set_defaults(func=cmd_r2_objects_delete)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
