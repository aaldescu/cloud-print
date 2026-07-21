# 🖨️ CloudPrint

Server local de printare pentru **Raspberry Pi** (inclusiv Pi Zero W). Rulează în
rețeaua ta locală și oferă o interfață web modernă din care oricine din casă poate
printa de pe telefon sau laptop — fără drivere, fără cabluri.

## Funcționalități

- **Încărcare simplă** — trage fișierul în pagină sau alege-l de pe dispozitiv
  (PDF, JPG, PNG, GIF, TXT, până la 50 MB)
- **Previzualizare ca în dialogul de printare** — paginile PDF sunt randate în
  browser (PDF.js, inclus local — nu e nevoie de internet), cu zoom și numerotare
- **Previzualizare live a opțiunilor** — alb-negru se vede direct pe pagini, iar
  paginile excluse din interval sunt estompate
- **Presetări rapide** — 📄 Document (A4, alb-negru, față-verso), 🖼️ Foto
  (color, o față), ✏️ Ciornă (calitate redusă)
- **Opțiuni complete** — copii, față-verso (margine lungă/scurtă), alb-negru/color,
  format hârtie, orientare, interval de pagini, calitate, încadrare în pagină
- **Coadă de printare** — vezi joburile active și anulează-le cu un click
- **Ușor pentru Pi Zero W** — doar Flask + comenzile CUPS; toată randarea grea
  (previzualizarea PDF) se face în browserul clientului, nu pe Pi

## Instalare pe Raspberry Pi

```bash
git clone https://github.com/aaldescu/cloud-print.git
cd cloud-print
./install.sh
```

Scriptul instalează CUPS și Flask, configurează serviciul systemd și pornește
aplicația. La final îți afișează adresa, de exemplu `http://192.168.1.42:8080`.

### Configurarea imprimantei în CUPS (o singură dată)

```bash
sudo cupsctl --remote-admin        # permite administrarea din rețea
```

Apoi deschide `http://<ip-ul-pi>:631` → **Administration → Add Printer** și
adaugă imprimanta (USB sau de rețea). Utilizatorul/parola sunt cele de login pe Pi.

Setează-o ca implicită:

```bash
lpoptions -d numele_imprimantei
```

### Verificare rapidă

```bash
lpstat -p          # imprimanta apare și e "idle"?
lp /etc/hostname   # trimite un test simplu
```

## Rulare manuală (pentru dezvoltare)

```bash
pip install -r requirements.txt
python3 app.py                # pornește pe http://0.0.0.0:8080
PORT=5000 python3 app.py      # sau pe alt port
```

## Cum funcționează

```
telefon / laptop ──(WiFi)──▶ Flask (Pi)──▶ lp / lpstat (CUPS) ──▶ imprimantă
        ▲                        │
        └── PDF.js randează ◀────┘ servește fișierul încărcat
            previzualizarea
```

- `POST /api/upload` — salvează fișierul (nume aleator, curățat automat după 24h)
- `GET /files/<id>` — servește fișierul pentru previzualizare
- `POST /api/print` — construiește comanda `lp` cu opțiunile alese
  (`sides=two-sided-long-edge`, `print-color-mode=monochrome`, `page-ranges` etc.)
- `GET /api/printers`, `GET /api/jobs`, `POST /api/jobs/<id>/cancel` — stare și coadă

## Note

- Aplicația este gândită pentru **rețeaua locală** — nu o expune direct pe
  internet (nu are autentificare).
- Pentru documente Word/LibreOffice, salvează-le ca PDF înainte de încărcare
  (conversia pe un Pi Zero W ar fi prea lentă).
