"""Helpers for reading and editing Cloudflare API token policies.

A token's policies are edited as flat rows, one per (effect, permission group,
resource), and rebuilt into policies on save. Resource formats:
https://developers.cloudflare.com/fundamentals/api/how-to/create-via-api/
"""

import json

USER = "com.cloudflare.api.user"
ACCOUNT = "com.cloudflare.api.account"
ZONE = "com.cloudflare.api.account.zone"
R2_BUCKET = "com.cloudflare.edge.r2.bucket"

SCOPE_LABELS = {USER: "User", ACCOUNT: "Account", ZONE: "Zone", R2_BUCKET: "R2 bucket"}

# Starting points for common tokens: (permission group name, scope).
# Zone-scoped groups get "all zones in this account"; others get "this account".
TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "cf-ddns updater (Zone Read + DNS Write)": [
        ("Zone Read", ZONE),
        ("DNS Write", ZONE),
    ],
    "DNS read-only": [
        ("Zone Read", ZONE),
        ("DNS Read", ZONE),
    ],
    "R2 admin (Workers R2 Storage Write)": [
        ("Workers R2 Storage Write", ACCOUNT),
    ],
    "Workers deploy (wrangler)": [
        ("Workers Scripts Write", ACCOUNT),
        ("Account Settings Read", ACCOUNT),
        ("Workers Routes Write", ZONE),
        ("Zone Read", ZONE),
    ],
}


def flatten(policies: list[dict]) -> list[dict]:
    """Split policies into rows of {effect, group_id, group_name, resource}."""
    rows = []
    for policy in policies:
        effect = policy.get("effect", "allow")
        for key, val in (policy.get("resources") or {}).items():
            for group in policy.get("permission_groups", []):
                rows.append({
                    "effect": effect,
                    "group_id": group["id"],
                    "group_name": group.get("name", group["id"]),
                    "resource": {key: val},
                })
    return rows


def build(rows: list[dict]) -> list[dict]:
    """Rebuild policies from rows: one policy per (effect, resource)."""
    policies: dict[tuple, dict] = {}
    for row in rows:
        k = (row["effect"], json.dumps(row["resource"], sort_keys=True))
        policy = policies.setdefault(
            k, {"effect": row["effect"], "resources": row["resource"], "permission_groups": []}
        )
        if all(g["id"] != row["group_id"] for g in policy["permission_groups"]):
            policy["permission_groups"].append({"id": row["group_id"]})
    return list(policies.values())


def describe(resource: dict, zone_names: dict[str, str] | None = None,
             account_id: str | None = None) -> str:
    """Human-readable label for a single-key resource dict."""
    zone_names = zone_names or {}
    (key, val), = resource.items()

    def account_label(aid: str) -> str:
        return "this account" if aid == account_id else f"account {aid[:8]}…"

    if key == f"{ZONE}.*":
        return "All zones (all accounts)"
    if key.startswith(f"{ZONE}."):
        zid = key[len(ZONE) + 1:]
        return f"Zone {zone_names.get(zid, zid)}"
    if key.startswith(f"{R2_BUCKET}."):
        parts = key[len(R2_BUCKET) + 1:].split("_", 2)
        if len(parts) == 3:
            _, jurisdiction, bucket = parts
            return f"R2 bucket {bucket}" + ("" if jurisdiction == "default" else f" ({jurisdiction})")
        return key
    if key == f"{ACCOUNT}.*":
        return "All accounts"
    if key.startswith(f"{ACCOUNT}."):
        label = account_label(key[len(ACCOUNT) + 1:])
        if isinstance(val, dict):
            inner = set(val)
            if inner == {f"{ZONE}.*"}:
                return f"All zones in {label}"
            if inner == {f"{R2_BUCKET}.*"}:
                return f"All R2 buckets in {label}"
            return f"Some resources in {label}"
        return label[0].upper() + label[1:]
    if key.startswith(f"{USER}."):
        return "User (you)"
    return key


def default_resource(scope: str, account_id: str | None, user_tag: str | None) -> dict | None:
    """The broadest same-account resource for a scope, used by templates."""
    if scope == ZONE:
        return {f"{ACCOUNT}.{account_id}": {f"{ZONE}.*": "*"}} if account_id else {f"{ZONE}.*": "*"}
    if scope == ACCOUNT:
        return {f"{ACCOUNT}.{account_id}": "*"} if account_id else {f"{ACCOUNT}.*": "*"}
    if scope == R2_BUCKET:
        return {f"{ACCOUNT}.{account_id}": {f"{R2_BUCKET}.*": "*"}} if account_id else None
    if scope == USER:
        return {f"{USER}.{user_tag}": "*"} if user_tag else None
    return None


def resource_choices(scopes: list[str], zones: list[dict], account_id: str | None,
                     user_tag: str | None, buckets: list[dict]) -> list[tuple[str, dict]]:
    """(label, resource) options for a permission group with the given scopes."""
    choices: list[tuple[str, dict]] = []
    if ZONE in scopes:
        if account_id:
            choices.append(("All zones in this account", {f"{ACCOUNT}.{account_id}": {f"{ZONE}.*": "*"}}))
        choices.append(("All zones (all accounts)", {f"{ZONE}.*": "*"}))
        for z in zones:
            choices.append((f"Zone {z['name']}", {f"{ZONE}.{z['id']}": "*"}))
    if ACCOUNT in scopes:
        if account_id:
            choices.append(("This account", {f"{ACCOUNT}.{account_id}": "*"}))
        choices.append(("All accounts", {f"{ACCOUNT}.*": "*"}))
    if R2_BUCKET in scopes and account_id:
        choices.append(("All R2 buckets in this account", {f"{ACCOUNT}.{account_id}": {f"{R2_BUCKET}.*": "*"}}))
        for b in buckets:
            jurisdiction = b.get("jurisdiction") or "default"
            choices.append((f"R2 bucket {b['name']}", {f"{R2_BUCKET}.{account_id}_{jurisdiction}_{b['name']}": "*"}))
    if USER in scopes and user_tag:
        choices.append(("User (you)", {f"{USER}.{user_tag}": "*"}))
    return choices


def scope_label(scopes: list[str]) -> str:
    return ", ".join(SCOPE_LABELS.get(s, s) for s in scopes)


def find_user_tag(tokens: list[dict]) -> str | None:
    """Pull the user id out of any existing user-scoped policy."""
    for token in tokens:
        for row in flatten(token.get("policies", [])):
            (key, _), = row["resource"].items()
            if key.startswith(f"{USER}.") and key != f"{USER}.*":
                return key[len(USER) + 1:]
    return None


def to_expiry(text: str) -> str | None:
    """'2026-12-31' or a full RFC 3339 timestamp → RFC 3339; blank → None."""
    text = text.strip()
    if not text:
        return None
    return f"{text}T00:00:00Z" if len(text) == 10 else text


def ip_condition(existing: dict | None, ips_text: str) -> dict:
    """Set the request.ip allow-list on a condition, keeping any not_in list."""
    condition = json.loads(json.dumps(existing or {}))
    ip = condition.setdefault("request.ip", {})
    ips = [s.strip() for s in ips_text.split(",") if s.strip()]
    if ips:
        ip["in"] = ips
    else:
        ip.pop("in", None)
    if not ip:
        condition.pop("request.ip")
    return condition
