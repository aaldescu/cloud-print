#!/usr/bin/env bash
# Generează un certificat self-signed pentru HTTPS (necesar pe unele
# telefoane care refuză http către IP-uri locale). Se rulează pe Pi.
#
# NU e nevoie de sudo. Dacă totuși e rulat cu sudo, la final dă certificatele
# înapoi utilizatorului real, ca serviciul (care rulează ca acel user) să le
# poată citi.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$DIR"

IP="$(hostname -I | awk '{print $1}')"
HOST="$(hostname)"

echo "==> Generez certificat pentru IP $IP și host $HOST.local …"

# openssl >= 1.1.1 acceptă -addext; dacă nu, folosim un fișier de config
if openssl req -help 2>&1 | grep -q -- "-addext"; then
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$DIR/key.pem" -out "$DIR/cert.pem" \
    -days 3650 -subj "/CN=CloudPrint" \
    -addext "subjectAltName=IP:$IP,DNS:$HOST.local,DNS:localhost"
else
  CONF="$(mktemp)"
  cat > "$CONF" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = CloudPrint
[ext]
subjectAltName = IP:$IP, DNS:$HOST.local, DNS:localhost
EOF
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$DIR/key.pem" -out "$DIR/cert.pem" \
    -days 3650 -config "$CONF"
  rm -f "$CONF"
fi

chmod 640 "$DIR/key.pem"

# dacă am fost rulați cu sudo, dăm fișierele înapoi userului real
if [ -n "${SUDO_USER:-}" ]; then
  chown "$SUDO_USER" "$DIR/cert.pem" "$DIR/key.pem" 2>/dev/null || true
fi

echo "==> Gata. Certificatul e în $DIR/"
echo "    Repornește serviciul:  sudo systemctl restart cloud-print"
echo "    Apoi accesează:        https://$IP:8080  (acceptă avertismentul)"
