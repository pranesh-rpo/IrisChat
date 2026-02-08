FROM python:3.11-slim

# Install system dependencies
# ffmpeg is CRITICAL for the Music Bot features
# build-essential and cmake are needed for compiling tgcrypto/tgcalls if wheels are missing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
