FROM python:3.11-slim

WORKDIR /app

# Install FFmpeg, fonts, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app ./app

RUN mkdir -p /app/storage/uploads /app/storage/outputs /app/storage/temp

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
