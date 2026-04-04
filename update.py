import ipaddress
import logging
import os
import time

import requests
from dotenv import load_dotenv
from tenacity import Retrying, retry, stop_after_attempt, wait_exponential, wait_fixed

# Initialize logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Load environment variables with default values
load_dotenv()
CLOUDFLARE_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
FORCE_UPDATE = os.getenv("FORCE_UPDATE", "false").lower() == "true"
CLOUDFLARE_FQDNS = os.getenv("CLOUDFLARE_FQDNS", "").split(",")
try:
    SLEEP = int(os.getenv("SLEEP", 60))
except ValueError:
    logging.warning("Invalid SLEEP value, defaulting to 60 seconds.")
    SLEEP = 60

if not CLOUDFLARE_TOKEN:
    logging.error("Cloudflare API token not set.")
    exit(1)

HEADERS = {
    "Authorization": f"Bearer {CLOUDFLARE_TOKEN}",
    "Content-Type": "application/json",
}

# List of services to try fetching the public IP
IP_SERVICES = [
    "https://api.ipify.org?format=json",
    "https://ipinfo.io/json",
    "https://ifconfig.me/ip",
]


def is_valid_ip(ip_str):
    """Return True only for valid, globally routable IPv4 addresses."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_global
    except ValueError:
        return False


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def get_public_ip():
    """Fetch the current public IP address with retries on failure."""
    for service_url in IP_SERVICES:
        try:
            response = requests.get(service_url, timeout=5)
            if "ipify" in service_url or "ipinfo" in service_url:
                ip = response.json().get("ip", "").strip()
            else:
                ip = response.text.strip()
            if is_valid_ip(ip):
                return ip
        except requests.RequestException as e:
            logging.error(f"Error fetching public IP from {service_url}: {e}")
    raise Exception("Failed to fetch public IP after multiple attempts.")


def get_zones(filter_zones=None):
    """Retrieve filtered zones (domains) managed in Cloudflare."""
    zones = {}
    list_zones_url = "https://api.cloudflare.com/client/v4/zones"
    try:
        response = requests.get(list_zones_url, headers=HEADERS, timeout=10)
        zones_data = response.json().get("result", [])
        for zone in zones_data:
            if not filter_zones or zone["name"] in filter_zones:
                zones[zone["name"]] = zone["id"]
    except requests.RequestException as e:
        logging.error(f"Failed to fetch zones: {e}")
    return zones


def update_dns_record(zone_id, record_id, new_data):
    """Update a specific DNS record."""
    if DRY_RUN:
        logging.info(
            f"[DRY RUN] Updated DNS record: {new_data['name']} to {new_data['content']}"
        )
        return
    update_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    try:
        response = requests.put(update_url, headers=HEADERS, json=new_data, timeout=10)
        if response.status_code == 200:
            logging.info(
                f"Updated DNS record: {new_data['name']} to {new_data['content']}"
            )
        else:
            logging.error(f"Failed to update DNS record: {new_data['name']}")
    except requests.RequestException as e:
        logging.error(f"Error updating DNS record: {e}")


def fetch_dns_records(zone_id):
    """Fetch all A records for a given zone."""
    list_dns_url = (
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A"
    )
    try:
        response = requests.get(list_dns_url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json().get("result", [])
        logging.error(f"Failed to fetch DNS records for zone {zone_id}")
    except requests.RequestException as e:
        logging.error(f"Error fetching DNS records for zone {zone_id}: {e}")
    return []


def should_update_record(current_ip, record):
    """Determine whether the DNS record should be updated."""
    return FORCE_UPDATE or record["content"] != current_ip


def is_network_available():
    try:
        requests.get("https://api.cloudflare.com/client/v4/", timeout=5)
        return True
    except requests.RequestException:
        return False


def fetch_and_update_zones(public_ip, filtered_zones):
    for zone_name, zone_id in filtered_zones.items():
        logging.info(f"Processing zone: {zone_name}")
        for record in fetch_dns_records(zone_id):
            if should_update_record(public_ip, record):
                new_record_data = {
                    "type": "A",
                    "name": record["name"],
                    "content": public_ip,
                    "ttl": record["ttl"],
                    "proxied": record.get("proxied", False),
                }
                update_dns_record(zone_id, record["id"], new_record_data)
            else:
                logging.info(
                    f"No update needed for {record['name']} (Record [{record['content']}] matches public IP [{public_ip}])"
                )


def main():
    while True:
        try:
            if is_network_available():
                public_ip = get_public_ip()
                zones = get_zones(CLOUDFLARE_FQDNS)
                for attempt in Retrying(stop=stop_after_attempt(3), wait=wait_fixed(10)):
                    with attempt:
                        fetch_and_update_zones(public_ip, zones)
            else:
                logging.error("Network not available. DNS records cannot be updated.")
        except Exception as e:
            logging.error(f"Unexpected error during update cycle: {e}")

        logging.info(f"Waiting {SLEEP} seconds before next check...")
        time.sleep(SLEEP)


if __name__ == "__main__":
    main()
