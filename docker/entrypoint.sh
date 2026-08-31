#!/usr/bin/env bash
# Selaraskan skema lebih dulu, baru serahkan ke perintah utama.
#
# Repo ini memiliki rangkaian migrasinya sendiri dengan tabel versi terpisah
# (`alembic_version_timbangan`), karena databasenya dipakai bersama sistem
# penggilingan yang punya rangkaiannya sendiri. Rinciannya di
# scripts/siapkan_skema.py dan migrations/env.py.
set -e

echo "[entrypoint] menyelaraskan skema..."
for i in 1 2 3 4 5; do
  if python -m scripts.siapkan_skema; then
    echo "[entrypoint] skema siap."
    break
  fi
  echo "[entrypoint] gagal (percobaan $i/5), tunggu 3 detik..."
  sleep 3
done

echo "[entrypoint] menjalankan: $*"
exec "$@"
