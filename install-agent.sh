#!/usr/bin/env bash
# Instalare AGENT CloudPrint pe Raspberry Pi (mod agent).
# Agentul nu pornește niciun server web — doar iese pe internet către serverul
# cloud (Dokploy), trage joburile și le printează local prin CUPS.
# Rulează pe Pi, din directorul proiectului:  ./install-agent.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
# utilizatorul real, indiferent dacă scriptul e rulat direct sau cu sudo
APP_USER="${SUDO_USER:-$(id -un)}"
ENV_FILE="/etc/cloud-print-agent.env"

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "Eroare: utilizatorul '$APP_USER' nu există." >&2
  exit 1
fi

echo "==> Instalare pachete (CUPS + Flask + requests)…"
sudo apt-get update
sudo apt-get install -y cups python3-flask python3-requests

echo "==> Adaug utilizatorul '$APP_USER' în grupul lpadmin…"
sudo usermod -aG lpadmin "$APP_USER"

# ---------------------------------------------------------------- configurare
# Valorile pot veni din mediu (CLOUDPRINT_CLOUD_URL / CLOUDPRINT_AGENT_TOKEN /
# CLOUDPRINT_POLL_INTERVAL) sau se citesc interactiv. Dacă există deja un fișier
# de configurare, valorile lui devin implicite (poți doar apăsa Enter).
existing_url=""; existing_token=""; existing_interval=""
if [ -f "$ENV_FILE" ]; then
  existing_url="$(sudo sed -n 's/^CLOUDPRINT_CLOUD_URL=//p' "$ENV_FILE" | head -1)"
  existing_token="$(sudo sed -n 's/^CLOUDPRINT_AGENT_TOKEN=//p' "$ENV_FILE" | head -1)"
  existing_interval="$(sudo sed -n 's/^CLOUDPRINT_POLL_INTERVAL=//p' "$ENV_FILE" | head -1)"
fi

URL="${CLOUDPRINT_CLOUD_URL:-$existing_url}"
TOKEN="${CLOUDPRINT_AGENT_TOKEN:-$existing_token}"
INTERVAL="${CLOUDPRINT_POLL_INTERVAL:-$existing_interval}"

if [ -z "$URL" ]; then
  read -rp "Adresa serverului cloud (ex. https://print.domeniul-tau.com): " URL
fi
URL="${URL%/}"  # fără slash la final
case "$URL" in
  http://*|https://*) ;;
  *) echo "Eroare: URL-ul trebuie să înceapă cu http:// sau https://" >&2; exit 1 ;;
esac

if [ -z "$TOKEN" ]; then
  # -s: nu afișa tokenul pe ecran în timp ce-l tastezi
  read -rsp "Token agent (același ca CLOUDPRINT_AGENT_TOKEN de pe server): " TOKEN
  echo
fi
if [ -z "$TOKEN" ]; then
  echo "Eroare: tokenul nu poate fi gol." >&2
  exit 1
fi

[ -z "$INTERVAL" ] && INTERVAL=4

echo "==> Scriu configurarea în $ENV_FILE…"
sudo tee "$ENV_FILE" >/dev/null <<EOF
CLOUDPRINT_CLOUD_URL=$URL
CLOUDPRINT_AGENT_TOKEN=$TOKEN
CLOUDPRINT_POLL_INTERVAL=$INTERVAL
EOF
sudo chmod 600 "$ENV_FILE"

echo "==> Instalez serviciul systemd (cloud-print-agent)…"
sed "s|/home/pi/cloud-print|$APP_DIR|g; s|User=pi|User=$APP_USER|g" \
  "$APP_DIR/cloud-print-agent.service" | sudo tee /etc/systemd/system/cloud-print-agent.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now cloud-print-agent

echo
echo "Gata! Agentul CloudPrint rulează și trage joburi de la:"
echo "  $URL"
echo
echo "Verifică logul (ar trebui să scrie 'conectat la ...'):"
echo "  journalctl -u cloud-print-agent -n 20 --no-pager"
echo
echo "Dacă imprimanta nu e configurată încă, adaug-o din interfața CUPS:"
echo "  https://$(hostname -I | awk '{print $1}'):631/admin  (CUPS cere httpS!)"
echo
echo "Notă: dacă abia acum ai fost adăugat în grupul lpadmin, dă logout/login"
echo "  (sau 'newgrp lpadmin') ca apartenența la grup să devină activă."
