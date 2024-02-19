import requests
import logging
import os
import sys
import re
from retrying import retry
from dotenv import load_dotenv
from urllib.parse import urlparse

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv()

# Accessing the environment variable
CLOUDFLARE_TOKEN = os.getenv('CLOUDFLARE_API_TOKEN')
DRY_RUN = os.getenv('DRY_RUN', 'false')
FORCE_UPDATE = os.getenv('FORCE_UPDATE', 'false')
CLOUDFLARE_FQDNS = os.getenv('CLOUDFLARE_FQDNS', '')

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
    zones = {}
    list_zones_url = 'https://api.cloudflare.com/client/v4/zones'
    try:
        response = requests.get(list_zones_url, headers=HEADERS)
        zones_data = response.json().get('result', [])
        for zone in zones_data:
            zones[zone['name']] = zone['id']
    except requests.RequestException as e:
        logging.error(f"Failed to fetch zones: {e}")
        sys.exit(1)
    return zones

def update_dns_record(zone_id, record_id, new_data):

    if DRY_RUN == 'true':
        logging.info(f"[DRY RUN] Updated DNS record: {new_data['name']} to {new_data['content']}")
        return
    else:
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
    if FORCE_UPDATE == 'true':
        return True
    
    return record['content'] != current_ip

def extract_zone_and_fqdn(fqdn):
    parsed_url = urlparse('//' + fqdn)
    domain_parts = parsed_url.netloc.split('.')
    domain = '.'.join(domain_parts[-2:])
    
    return domain, fqdn

def group_fqdn_by_zone(fqdns_string):
    formatted_fqdns = ''.join(fqdns_string.split())
    fqdns_list = formatted_fqdns.split(',')
    domain_groups = {}

    for fqdn in fqdns_list:
        domain, a_record = extract_zone_and_fqdn(fqdn.strip())
        if domain in domain_groups:
            if a_record:  # Add the A record if it's not an empty string
                domain_groups[domain].append(a_record)
        else:
            domain_groups[domain] = [a_record] if a_record else []

    # Optionally, remove duplicates by converting lists to sets and back to lists
    for domain in domain_groups:
        domain_groups[domain] = list(set(domain_groups[domain]))

    return domain_groups

def main():
    if not CLOUDFLARE_TOKEN:
        logging.error("Cloudflare API token not set.")
        sys.exit(1)
    
    public_ip = get_public_ip()
    logging.info(f"Current public IP: {public_ip}")

    requested_zones = group_fqdn_by_zone(CLOUDFLARE_FQDNS)
    zones_dict = get_zones()

    for zone_name in requested_zones:
        if zone_name in zones_dict:
            logging.info(f"Processing zone: {zone_name}")
            zone_id = zones_dict[zone_name]
            dns_records = fetch_dns_records(zone_id)
            
            for record in requested_zones[zone_name]:
                dns_record = next((item for item in dns_records if item.get("name") == record), None)

                if(dns_record is None):
                    logging.error(f"{record} was not found.")
                    continue
                
                if should_update_record(public_ip, dns_record):
                    new_record_data = {
                        'type': 'A',
                        'name': dns_record['name'],
                        'content': public_ip,
                        'ttl': dns_record['ttl'],
                        'proxied': dns_record.get('proxied', False),
                    }
                    update_dns_record(zone_id, dns_record['id'], new_record_data)
                else:
                    logging.info(f"No update needed for {dns_record['name']} (IP matches current public IP)")
        else:
            logging.error(f"Zone not found: {zone_name}")

if __name__ == "__main__":
    main()
