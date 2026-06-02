FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg yt-dlp && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir -e .
RUN mkdir -p data outputs assets/cache assets/voiceovers

EXPOSE 5000
CMD ["python3", "-m", "clipper_agency", "dashboard"]
