#!/usr/bin/env bash
# Instalare CloudPrint pe Raspberry Pi (rulează pe Pi, din directorul proiectului)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SUDO_USER:-pi}"

echo "==> Instalare pachete (CUPS + Flask)…"
sudo apt-get update
sudo apt-get install -y cups python3-flask

echo "==> Adaug utilizatorul '$APP_USER' în grupul lpadmin…"
sudo usermod -aG lpadmin "$APP_USER"

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
echo "  sudo cupsctl --remote-admin   # activează administrarea din rețea"
echo "  apoi deschide http://$IP:631 și mergi la Administration -> Add Printer"
