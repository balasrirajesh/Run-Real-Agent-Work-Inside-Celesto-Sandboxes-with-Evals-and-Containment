FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck validation and runtime tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application and report artifacts
COPY app/ app/
COPY seeds/ seeds/
COPY reports/ reports/
COPY logs/ logs/
COPY demo/ demo/

ENV PYTHONUNBUFFERED=1
ENV API_PORT=8080

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

