# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install cron
RUN apt-get update && apt-get install -y cron

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy startup script
COPY startup.sh /usr/src/app/startup.sh

# Make startup script executable
RUN chmod +x /usr/src/app/startup.sh

# Run the startup script
CMD ["/usr/src/app/startup.sh"]