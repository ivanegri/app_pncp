# Use official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project
COPY . /app/

# Expose port (Flash default 5000, we'll map it)
EXPOSE 5000

# Run the application
# We use python run.py for dev/simple setups, or gunicorn for prod.
# Given the user context "run anywhere", python run.py is simplest if it binds 0.0.0.0.
# I will ensure run.py binds 0.0.0.0 or use a CMD that does.
# Let's assume run.py binds to 0.0.0.0 or we pass host param. 
# Checking run.py later. For now, let's use a standard CMD.
CMD ["python", "run.py"]
