FROM python:3.12-slim

LABEL maintainer="Ryan Swindle <rswindle@gmail.com>"
LABEL description="ASCOM Alpaca server for QHYCCD cameras (libqhyccd)"

# Install minimal system dependencies for libqhyccd
RUN apt-get update && apt-get install -y \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /alpyca

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY config.yaml .
COPY *.py ./

CMD ["python", "main.py"]