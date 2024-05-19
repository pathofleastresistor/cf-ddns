import requests
import logging
import os
import re
import time
from retrying import retry
from dotenv import load_dotenv

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
SLEEP = int(os.getenv("SLEEP", 60))

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


def is_valid_ip(ip_address):
    """Validate the IP address format."""
    pattern = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
    return re.match(pattern, ip_address) is not None


@retry(stop_max_attempt_number=3, wait_exponential_multiplier=1000)
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
        response = requests.get(list_zones_url, headers=HEADERS)
        zones_data = response.json().get("result", [])
        for zone in zones_data:
            if not filter_zones or zone["name"] in filter_zones:
                zones[zone["name"]] = zone["id"]
    except requests.RequestException as e:
        logging.error(f"Failed to fetch zones: {e}")
    return zones


def update_dns_record(zone_id, record_id, new_data):

    if DRY_RUN:
        logging.info(
            f"[DRY RUN] Updated DNS record: {new_data['name']} to {new_data['content']}"
        )
        return
    else:
        """Update a specific DNS record."""
        update_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
        try:
            response = requests.put(update_url, headers=HEADERS, json=new_data)
            if response.status_code == 200:
                logging.info(
                    f"Updated DNS record: {new_data['name']} to {new_data['content']}"
                )
            else:
                logging.error(f"Failed to update DNS record: {new_data['name']}")
        except requests.RequestException as e:
            logging.error(f"Error updating DNS record: {e}")


def fetch_dns_records(zone_id):
    """Fetch all DNS records for a given zone."""
    dns_records = []
    list_dns_url = (
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A"
    )
    try:
        response = requests.get(list_dns_url, headers=HEADERS)
        if response.status_code == 200:
            dns_records = response.json().get("result", [])
        else:
            logging.error(f"Failed to fetch DNS records for zone {zone_id}")
    except requests.RequestException as e:
        logging.error(f"Error fetching DNS records for zone {zone_id}: {e}")
    return dns_records


def filter_dns_records(dns_records, zone_name):
    """Filter DNS records based on zone name."""
    return [record for record in dns_records if record["name"] == zone_name]


def should_update_record(current_ip, record):
    """Determine whether the DNS record should be updated."""
    return FORCE_UPDATE or record["content"] != current_ip


def is_network_available():
    try:
        requests.get("https://www.google.com/", timeout=5)
        return True
    except requests.RequestException:
        return False


def fetch_and_update_zones(public_ip, filtered_zones):
    for zone_name, zone_id in filtered_zones.items():
        logging.info(f"Processing zone: {zone_name}")
        dns_records = filter_dns_records(fetch_dns_records(zone_id), zone_name)
        for record in dns_records:
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
    while True:  # Keep the script running in a loop
        if is_network_available():
            public_ip = get_public_ip()
            zones = get_zones(CLOUDFLARE_FQDNS)

            @retry(stop_max_attempt_number=3, wait_fixed=10000)
            def update_records():
                fetch_and_update_zones(public_ip, zones)

            update_records()  # Call the decorated function to update records

        else:
            logging.error(
                "Network not available. DNS records cannot be updated."
            )  # Log the error

        # Always sleep for 60 seconds before the next iteration
        logging.info(f"Waiting {SLEEP} seconds before next check...")
        time.sleep(SLEEP)


if __name__ == "__main__":
    main()
