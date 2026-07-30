#!/usr/bin/env bash
# Generează un certificat self-signed pentru HTTPS (necesar pe unele
# telefoane care refuză http către IP-uri locale). Se rulează pe Pi.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$DIR"

IP="$(hostname -I | awk '{print $1}')"
HOST="$(hostname)"

echo "==> Generez certificat pentru IP $IP și host $HOST.local …"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$DIR/key.pem" -out "$DIR/cert.pem" \
  -days 3650 \
  -subj "/CN=CloudPrint" \
  -addext "subjectAltName=IP:$IP,DNS:$HOST.local,DNS:localhost"

chmod 600 "$DIR/key.pem"
echo "==> Gata. Certificatul e în $DIR/"
echo "    Repornește serviciul:  sudo systemctl restart cloud-print"
echo "    Apoi accesează:        https://$IP:8080  (acceptă avertismentul)"
