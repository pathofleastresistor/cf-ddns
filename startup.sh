#!/bin/sh

# Default to running the script at startup unless RUN_AT_STARTUP is set to "false"
if [ "$RUN_AT_STARTUP" != "false" ]; then
  echo "Running script at startup..."
  python3 /usr/src/app/update.py
else
  echo "Skipping script run at startup..."
fi

# Set a default cron schedule if CRON_SCHEDULE is not set
CRON_SCHEDULE="${CRON_SCHEDULE:-*/5 * * * *}"

# Create a new crontab entry using the CRON_SCHEDULE environment variable
echo "$CRON_SCHEDULE /usr/local/bin/python /usr/src/app/update.py >> /var/log/cron.log 2>&1" | crontab -

# Start the cron service in the foreground
cron -f
