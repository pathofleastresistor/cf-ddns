#!/bin/sh

# Run your Python script once at startup
python3 /usr/src/app/update.py

# Create a new crontab entry using the CRON_SCHEDULE environment variable
echo "$CRON_SCHEDULE /usr/local/bin/python /usr/src/app/update.py >> /var/log/cron.log 2>&1" | crontab -

# Start the cron service in the foreground
# Note: The specific command to start cron depends on your base image
cron -f
