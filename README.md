[![App Test](https://github.com/pathofleastresistor/cf-ddns/actions/workflows/python-app.yml/badge.svg)](https://github.com/pathofleastresistor/cf-ddns/actions/workflows/python-app.yml)

This repository allows the user to update A records on Cloudflare to current IP of the server, commonly called Dynamic DNS.

### How to setup

#### Getting a Cloudflare API token
1. Review Cloudflare's help center on [creating an API token](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
2. Create a token with Zone:Zone:Read and Zone:DNS:Edit
3. Copy .env.default to .env and replace INSERT_TOKEN_HERE with your token.

#### Create .env
1. Copy .env.default to .env
2. Set the ennvironment variables according to your preference (see definitions below)

### How to use

#### Container (preferred)
The repo includes a docker-compose.yml file that you can use to spin everything up. It also supports the CRON_SCHEDULE environment variable to run the script routinely.

1. `docker compose up --build -d`

#### Run script
1. Create a Python virtual environment: `python -m venv venv`
2. Open the venv: `source venv/bin/activate`
3. Install requirements: `pip install -r requirements.txt`
4. Run the script: `python update.py`

CRON_SCHEDULE won't do anything with this method, but you can create your own crontab entry.

### Environment Variables

* `CLOUDFLARE_API_TOKEN`: the token you create in Cloudflare. Make sure the token is set up with Zone:Zone:Read and Zone:DNS:Edit
* `CLOUDFLARE_FQDNS`: the list of FQDNs you want to update
* `CRON_SCHEDULE`: the cron schedule for running the script inside the container
* `RUN_AT_STARTUP`: when starting the container, set to "true" if you want to immediately run the script once. Otherwise set to `false`
* `FORCE_UPDATE`: force updating the A records, even if they have the current IP address
* `DRY_RUN`: set to "true" if you want to set the output the script without any changes being applied
