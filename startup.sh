#!/bin/sh

# Set a default cron schedule if CRON_SCHEDULE is not set
CRON_SCHEDULE="${CRON_SCHEDULE:-*/5 * * * *}"

# Check if the script should run at startup
if [ "$RUN_AT_STARTUP" != "false" ]; then
  echo "Running script at startup..."
  python3 /usr/src/app/update.py
else
  echo "Skipping script run at startup..."
fi

# Create a new crontab entry using the CRON_SCHEDULE environment variable
echo "$CRON_SCHEDULE /usr/local/bin/python3 /usr/src/app/update.py > /var/log/cron.log 2>&1" | crontab -

# Make sure the cron log file exists
touch /var/log/cron.log

# Start the cron service
crond

# Keep the container running by tailing the cron log
tail -f /var/log/cron.log