# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set an environment variable for the port number Cloud Run will use
ENV PORT 8080

# Set the working directory inside the container
WORKDIR /app

# Copy the dependencies file first to leverage Docker's layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's source code into the container
COPY . .

# Command to run the application using Gunicorn (production server)
# Gunicorn will listen on the port specified by the PORT environment variable.
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--workers", "1", "--threads", "8", "--timeout", "0", "run:app"]
