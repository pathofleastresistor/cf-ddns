import requests
import logging
import os
import sys
import re
from retrying import retry
from dotenv import load_dotenv

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv()

# Accessing the environment variable
CLOUDFLARE_TOKEN = os.getenv('CLOUDFLARE_API_TOKEN')

if not CLOUDFLARE_TOKEN:
    print("Cloudflare API token not set.")
    exit(1)

HEADERS = {
    'Authorization': f'Bearer {CLOUDFLARE_TOKEN}',
    'Content-Type': 'application/json',
}

# List of services to try fetching the public IP
IP_SERVICES = [
    'https://api.ipify.org?format=json',
    'https://ipinfo.io/json',
    'https://ifconfig.me/ip',
]

def is_valid_ip(ip_address):
    """Validate the IP address format."""
    pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    return re.match(pattern, ip_address) is not None

@retry(stop_max_attempt_number=3, wait_exponential_multiplier=1000)
def get_public_ip():
    """Fetch the current public IP address with retries on failure."""
    for service_url in IP_SERVICES:
        try:
            response = requests.get(service_url, timeout=5)
            if 'ipify' in service_url or 'ipinfo' in service_url:
                ip = response.json().get('ip', '').strip()
            else:
                ip = response.text.strip()
            if is_valid_ip(ip):
                return ip
        except requests.RequestException as e:
            logging.warning(f"Error fetching public IP from {service_url}: {e}")
    raise Exception("Failed to fetch public IP after multiple attempts.")

def get_zones():
    """Retrieve all zones (domains) managed in Cloudflare."""
    zones = []
    list_zones_url = 'https://api.cloudflare.com/client/v4/zones'
    try:
        response = requests.get(list_zones_url, headers=HEADERS)
        zones_data = response.json().get('result', [])
        for zone in zones_data:
            zones.append((zone['id'], zone['name']))
    except requests.RequestException as e:
        logging.error(f"Failed to fetch zones: {e}")
        sys.exit(1)
    return zones

def update_dns_record(zone_id, record_id, new_data):
    """Update a specific DNS record."""
    update_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    try:
        response = requests.put(update_url, headers=HEADERS, json=new_data)
        if response.status_code == 200:
            logging.info(f"Updated DNS record: {new_data['name']} to {new_data['content']}")
        else:
            logging.error(f"Failed to update DNS record: {new_data['name']}")
    except requests.RequestException as e:
        logging.error(f"Error updating DNS record: {e}")

def fetch_dns_records(zone_id):
    """Fetch all DNS records for a given zone."""
    dns_records = []
    list_dns_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A"
    try:
        response = requests.get(list_dns_url, headers=HEADERS)
        if response.status_code == 200:
            dns_records = response.json().get('result', [])
        else:
            logging.error(f"Failed to fetch DNS records for zone {zone_id}")
    except requests.RequestException as e:
        logging.error(f"Error fetching DNS records for zone {zone_id}: {e}")
    return dns_records

def should_update_record(current_ip, record):
    """Determine whether the DNS record should be updated."""
    return record['content'] != current_ip

def main():
    if not CLOUDFLARE_TOKEN:
        logging.error("Cloudflare API token not set.")
        sys.exit(1)
    
    public_ip = get_public_ip()
    logging.info(f"Current public IP: {public_ip}")
    zones = get_zones()

    for zone_id, zone_name in zones:
        logging.info(f"Processing zone: {zone_name}")
        dns_records = fetch_dns_records(zone_id)
        for record in dns_records:
            if should_update_record(public_ip, record):
                new_record_data = {
                    'type': 'A',
                    'name': record['name'],
                    'content': public_ip,
                    'ttl': record['ttl'],
                    'proxied': record.get('proxied', False),
                }
                update_dns_record(zone_id, record['id'], new_record_data)
            else:
                logging.info(f"No update needed for {record['name']} (IP matches current public IP)")


if __name__ == "__main__":
    main()
