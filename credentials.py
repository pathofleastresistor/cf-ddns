"""Where the CLI and TUI find Cloudflare credentials.

The DDNS updater (update.py) only uses CLOUDFLARE_API_TOKEN from .env, and compose
passes all of .env into its container. So broader tokens used only interactively
live outside .env, in owner-only files under CLOUDFLARE_CONFIG_DIR
(default ~/.config/cloudflare):

    token        manager token for the CLI/TUI (DNS, R2, ...)
    admin_token  token with User > API Tokens > Edit, for the TUI's Tokens tab
    account_id   Cloudflare account id

An environment variable (or .env entry) of the same purpose always wins.
"""

import os


def config_dir() -> str:
    return os.path.expanduser(os.getenv("CLOUDFLARE_CONFIG_DIR", "~/.config/cloudflare"))


def config_path(name: str) -> str:
    return os.path.join(config_dir(), name)


def read_config(name: str) -> str | None:
    try:
        with open(config_path(name)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def manager_token() -> str | None:
    """Token for interactive DNS/R2 work; falls back to the DDNS token."""
    return (os.getenv("CLOUDFLARE_MANAGER_TOKEN") or read_config("token")
            or os.getenv("CLOUDFLARE_API_TOKEN"))


def admin_token() -> str | None:
    return os.getenv("CLOUDFLARE_ADMIN_TOKEN") or read_config("admin_token")


def account_id() -> str | None:
    return os.getenv("CLOUDFLARE_ACCOUNT_ID") or read_config("account_id")
