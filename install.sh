#!/usr/bin/env bash
# Instalare CloudPrint pe Raspberry Pi (rulează pe Pi, din directorul proiectului)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
# utilizatorul real, indiferent dacă scriptul e rulat direct sau cu sudo
APP_USER="${SUDO_USER:-$(id -un)}"
if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "Eroare: utilizatorul '$APP_USER' nu există." >&2
  exit 1
fi

echo "==> Instalare pachete (CUPS + Flask)…"
sudo apt-get update
sudo apt-get install -y cups python3-flask

echo "==> Adaug utilizatorul '$APP_USER' în grupul lpadmin…"
sudo usermod -aG lpadmin "$APP_USER"

echo "==> Activez administrarea CUPS din rețea…"
sudo cupsctl --remote-admin
sudo systemctl restart cups

echo "==> Instalez serviciul systemd…"
sed "s|/home/pi/cloud-print|$APP_DIR|g; s|User=pi|User=$APP_USER|g" \
  "$APP_DIR/cloud-print.service" | sudo tee /etc/systemd/system/cloud-print.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now cloud-print

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Gata! CloudPrint rulează la:  http://$IP:8080"
echo
echo "Dacă imprimanta nu e configurată încă, adaug-o din interfața CUPS:"
echo "  deschide  https://$IP:631/admin  (cu httpS!)"
echo "  browserul va avertiza despre certificat — apasă 'Advanced' -> 'Continue'"
echo "  apoi Administration -> Add Printer (user/parola de login pe Pi)"
echo
echo "Notă: dacă ai rulat installul înainte de acest fix, reautentifică-te"
echo "(logout/login sau 'newgrp lpadmin') ca grupul lpadmin să devină activ."
