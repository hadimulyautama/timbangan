#!/usr/bin/env bash
# Selaraskan skema lebih dulu, baru serahkan ke perintah utama.
#
# Repo ini memiliki rangkaian migrasinya sendiri dengan tabel versi terpisah
# (`alembic_version_timbangan`), karena databasenya dipakai bersama sistem
# penggilingan yang punya rangkaiannya sendiri. Rinciannya di
# scripts/siapkan_skema.py dan migrations/env.py.
#
# Gagal setelah lima percobaan berarti BERHENTI, bukan menyala apa adanya.
# Server yang hidup di atas skema yang belum tentu benar akan menerima
# timbangan dan menyimpannya salah — jauh lebih buruk daripada service yang
# mati terang-terangan dan terlihat di Railway.
set -e

siap=""
for i in 1 2 3 4 5; do
  if python -m scripts.siapkan_skema; then
    siap="ya"
    echo "[entrypoint] skema siap."
    break
  fi
  echo "[entrypoint] gagal (percobaan $i/5), tunggu 3 detik..."
  sleep 3
done

if [ -z "$siap" ]; then
  echo "[entrypoint] BERHENTI — skema tidak bisa diselaraskan." >&2
  exit 1
fi

echo "[entrypoint] menjalankan: $*"
exec "$@"
