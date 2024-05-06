FROM python:3.9-alpine

RUN apk add --no-cache tzdata
ENV TZ=America/Los_Angeles

# Install cron and msmtp
RUN apk update \
    && apk add --no-cache dcron msmtp

# Set the working directory
WORKDIR /usr/src/app

# Copy the Python script, crontab, and msmtp configuration
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy and set permissions for the startup script
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

CMD ["/startup.sh"]