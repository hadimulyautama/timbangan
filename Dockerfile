# Image Pos Timbang — FastAPI, tanpa bot dan tanpa lapisan AI.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# tzdata dibutuhkan ZoneInfo (APP_TIMEZONE=Asia/Jakarta).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt tzdata

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini .
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Railway mengganti CMD tetapi TIDAK mengganti ENTRYPOINT — penyelarasan
# skema karenanya selalu berjalan lebih dulu. Bentuk `sh -c` dipakai supaya
# ${PORT} benar-benar ter-ekspansi; Railway menjalankan perintah start
# sebagai argv, bukan lewat shell.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
