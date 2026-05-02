FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY newsletter_pod ./newsletter_pod
COPY sources.yml ./sources.yml
COPY voices.yml ./voices.yml

EXPOSE 8080

CMD ["uvicorn", "newsletter_pod.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
