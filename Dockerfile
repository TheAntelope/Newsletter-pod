FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ffmpeg powers the broadcast-loop waveform-video renderer
# (newsletter_pod/broadcast/video.py). ~50MB added; acceptable for the
# single image.
RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY newsletter_pod ./newsletter_pod
COPY sources.yml ./sources.yml
COPY voices.yml ./voices.yml
COPY weekly_changes.json ./weekly_changes.json

EXPOSE 8080

CMD ["uvicorn", "newsletter_pod.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
