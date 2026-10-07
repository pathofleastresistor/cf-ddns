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

#### Interactive manager (TUI)
`python tui.py` opens a terminal UI with three tabs:

1. **DNS**: browse zones; create, edit and delete records.
2. **R2**: browse buckets and objects; create and delete them (needs `CLOUDFLARE_ACCOUNT_ID`).
3. **Tokens**: list your user API tokens and see what each can do. `n` creates a token, `e`/Enter edits its permissions, expiry, client-IP allow-list and active state, `x` rolls its secret, and `d` deletes it. The editor has templates (e.g. a ready-made cf-ddns token) and a filterable permission picker. New and rolled secrets are shown once. Tokens stored on this machine (the `.env` keys and the files above) are marked with `*` and where they're used; after a roll, a Save button writes the new secret back to each place.

#### Credentials for the CLI and TUI
Compose passes all of `.env` into the DDNS container, so keep `.env` to what the updater needs (a narrow Zone Read + DNS Edit token). Broader tokens used only interactively live in owner-only files under `~/.config/cloudflare/` (override with `CLOUDFLARE_CONFIG_DIR`):

| File | Used for | Env override |
|---|---|---|
| `token` | CLI and TUI DNS/R2 work (falls back to `CLOUDFLARE_API_TOKEN`) | `CLOUDFLARE_MANAGER_TOKEN` |
| `admin_token` | TUI Tokens tab; needs **User > API Tokens > Edit**, which only the dashboard's "Create Additional Tokens" template grants | `CLOUDFLARE_ADMIN_TOKEN` |
| `account_id` | R2 and account-scoped token permissions | `CLOUDFLARE_ACCOUNT_ID` |

Create them with `chmod 600`.

### Environment Variables

* `CLOUDFLARE_API_TOKEN`: the token you create in Cloudflare. Make sure the token is set up with Zone:Zone:Read and Zone:DNS:Edit
* `CLOUDFLARE_FQDNS`: the list of FQDNs you want to update
* `CLOUDFLARE_RECORDS`: optional comma-separated record names; only these are kept pointed at home (blank = every A record in the listed zones)
* `CLOUDFLARE_TOKEN_FILES`: optional comma-separated files holding token secrets, so the TUI's Tokens tab can show where each token is used (default: `token` and `admin_token` in `~/.config/cloudflare/`)
* CLI/TUI-only credentials: see *Credentials for the CLI and TUI* above
* `SLEEP`: how many seconds to wait between checks (default: 60)
* `FORCE_UPDATE`: force updating the A records, even if they have the current IP address
* `DRY_RUN`: set to "true" if you want to set the output the script without any changes being applied
