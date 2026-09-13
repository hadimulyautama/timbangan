# Image Pos Timbang — FastAPI, tanpa bot dan tanpa lapisan AI.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# tzdata dibutuhkan ZoneInfo (APP_TIMEZONE=Asia/Jakarta).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt tzdata

# Paket bersama (repo core/, di-vendor oleh core/scripts/sinkron.py).
COPY hmu_core ./hmu_core
COPY hmu_identitas ./hmu_identitas
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
# --proxy-headers / --forwarded-allow-ips: Railway menaruh proxy di depan
# aplikasi, dan tanpa keduanya uvicorn membaca sambungan dari proxy itu apa
# adanya. Dua akibatnya, dan dua-duanya diam:
#
#   · `request.url.scheme` terbaca "http" walau pengunjungnya memakai HTTPS,
#     jadi cookie sesi dipasang TANPA bendera Secure — cookie yang boleh
#     ikut berangkat lewat sambungan tak terenkripsi;
#   · `request.client.host` berisi alamat proxy, jadi SELURUH jejak audit
#     menyebut alamat yang sama untuk semua orang, dan "dari mana login itu
#     datang" tak punya jawaban.
#
# `*` aman di sini karena satu-satunya jalan masuk ke container ini adalah
# proxy Railway itu sendiri; port-nya tak terbuka ke jaringan lain.
# Temuan QA T-27.
CMD ["sh", "-c", "uvicorn app.timbangan.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
