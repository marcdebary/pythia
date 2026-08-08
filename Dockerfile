# Ein Abbild fuer beide Rollen: HTTP-Oberflaeche und Zeitsteuerung.
# Welche laeuft, entscheidet das Kommando in docker-compose.yml.
FROM python:3.12-slim

# Nicht als Wurzelnutzer laufen. Das Programm liest Marktdaten und schreibt
# eine SQLite-Datei - mehr Rechte braucht es nicht.
RUN useradd --create-home --uid 10001 pythia

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
COPY web/ /web/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    WEB_DIR=/web

RUN mkdir -p /data && chown -R pythia:pythia /data /app /web
USER pythia

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
