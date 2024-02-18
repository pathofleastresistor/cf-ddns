This repository allows the user to update A records on Cloudflare to current IP of the server, commonly called Dynamic DNS.

### Getting a Cloudflare API token
1. Review Cloudflare's help center on [creating an API token](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
2. Create a token with Zone:Zone:Read and Zone:DNS:Edit
3. Copy .env.default to .env and replace INSERT_TOKEN_HERE with your token.

### Set schedule
You need to set the CRON_SCHEDULE environment variable so that the script will check on a regular basis if the IP address is current. The default is set to every 5 minutes.

#### Run at startup
By default, when the user starts the container, the update script will run. To avoid this, set the env variable RUN_AT_STARTUP to `false`.


### Running the container
Run `docker compose up --build -d`.