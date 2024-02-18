# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container
# This step can be skipped if your script does not serve a web application
# EXPOSE 80

# Define environment variable
# Use this step if you want to set a default value or ensure it exists, but remember to pass actual values at runtime
# ENV CLOUDFLARE_API_TOKEN="YourTokenHere"

# Run script.py when the container launches
CMD ["python", "./update.py"]