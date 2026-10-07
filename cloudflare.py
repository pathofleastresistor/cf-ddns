"""Cloudflare API client for DNS record and R2 management."""

import requests

CF_API_BASE = "https://api.cloudflare.com/client/v4"

PROXIABLE_TYPES = {"A", "AAAA", "CNAME"}
PRIORITY_TYPES = {"MX", "SRV", "URI"}


class CloudflareAPI:
    def __init__(self, token: str, account_id: str | None = None):
        self.account_id = account_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        r = requests.request(
            method, f"{CF_API_BASE}{path}", headers=self.headers, timeout=10, **kwargs
        )
        r.raise_for_status()
        return r.json()

    def _r2_request(self, method: str, path: str, **kwargs) -> dict:
        """R2 API returns data directly, not wrapped in {result: ...}."""
        r = requests.request(
            method, f"{CF_API_BASE}{path}", headers=self.headers, timeout=10, **kwargs
        )
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    def get_zones(self) -> list[dict]:
        return self._request("GET", "/zones", params={"per_page": 100}).get("result", [])

    def get_dns_records(self, zone_id: str) -> list[dict]:
        return self._request(
            "GET", f"/zones/{zone_id}/dns_records", params={"per_page": 500}
        ).get("result", [])

    def create_dns_record(self, zone_id: str, data: dict) -> dict:
        return self._request(
            "POST", f"/zones/{zone_id}/dns_records", json=data
        ).get("result", {})

    def update_dns_record(self, zone_id: str, record_id: str, data: dict) -> dict:
        return self._request(
            "PUT", f"/zones/{zone_id}/dns_records/{record_id}", json=data
        ).get("result", {})

    def delete_dns_record(self, zone_id: str, record_id: str) -> dict:
        return self._request(
            "DELETE", f"/zones/{zone_id}/dns_records/{record_id}"
        ).get("result", {})

    # ------------------------------------------------------------------
    # R2
    # ------------------------------------------------------------------

    def _r2_path(self, suffix: str = "") -> str:
        if not self.account_id:
            raise ValueError("account_id is required for R2 operations")
        return f"/accounts/{self.account_id}/r2/buckets{suffix}"

    def list_r2_buckets(self) -> list[dict]:
        return self._r2_request("GET", self._r2_path()).get("buckets", [])

    def create_r2_bucket(self, name: str, location: str | None = None) -> dict:
        body: dict = {"name": name}
        if location:
            body["locationHint"] = location
        return self._r2_request("POST", self._r2_path(), json=body)

    def delete_r2_bucket(self, name: str) -> dict:
        return self._r2_request("DELETE", self._r2_path(f"/{name}"))

    def get_r2_bucket(self, name: str) -> dict:
        return self._r2_request("GET", self._r2_path(f"/{name}"))

    def list_r2_objects(self, bucket: str, prefix: str = "", delimiter: str = "") -> list[dict]:
        params: dict = {}
        if prefix:
            params["prefix"] = prefix
        if delimiter:
            params["delimiter"] = delimiter
        return self._r2_request("GET", self._r2_path(f"/{bucket}/objects"), params=params).get("objects", [])

    def delete_r2_object(self, bucket: str, key: str) -> dict:
        return self._r2_request("DELETE", self._r2_path(f"/{bucket}/objects/{key}"))

    def upload_r2_object(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        upload_headers = {k: v for k, v in self.headers.items() if k != "Content-Type"}
        upload_headers["Content-Type"] = content_type
        r = requests.put(
            f"{CF_API_BASE}{self._r2_path(f'/{bucket}/objects/{key}')}",
            headers=upload_headers,
            data=data,
            timeout=60,
        )
        r.raise_for_status()
        return r.json() if r.content else {}

    def download_r2_object(self, bucket: str, key: str) -> bytes:
        r = requests.get(
            f"{CF_API_BASE}{self._r2_path(f'/{bucket}/objects/{key}')}",
            headers=self.headers,
            timeout=60,
        )
        r.raise_for_status()
        return r.content
