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
- **Istoric printări** — ce s-a printat, când și cu ce opțiuni (nume, dată,
  imprimantă, copii, alb-negru/color etc.). Fișierele nu se salvează — doar
  jurnalul, ca să știi ce a trecut prin imprimantă
- **Acces simplu de pe telefon** — rulează pe `http` (fără certificat, fără
  avertismente, exact ca interfața routerului); `https` opțional pentru
  telefoanele rare care refuză http
- **Ușor pentru Pi Zero W** — doar Flask + comenzile CUPS + o mică bază SQLite
  (din biblioteca standard Python); toată randarea grea (previzualizarea PDF)
  se face în browserul clientului, nu pe Pi

## Instalare pe Raspberry Pi

```bash
git clone https://github.com/aaldescu/cloud-print.git
cd cloud-print
./install.sh
```

Scriptul instalează CUPS și Flask, configurează serviciul systemd și pornește
aplicația. La final îți afișează adresa, de exemplu `http://192.168.1.42:8080`.

### Configurarea imprimantei în CUPS (o singură dată)

Scriptul de instalare activează deja administrarea din rețea. Deschide:

```
https://<ip-ul-pi>:631/admin
```

**Atenție: cu `https`, nu `http`** — altfel CUPS afișează „Upgrade Required".
Browserul va avertiza că certificatul nu e de încredere (e autosemnat, e normal
pe rețeaua locală) — apasă *Advanced → Continue*. Apoi **Administration →
Add Printer** și adaugă imprimanta (USB sau de rețea). Utilizatorul/parola sunt
cele de login pe Pi (utilizatorul trebuie să fie în grupul `lpadmin` — scriptul
îl adaugă; dă logout/login dacă tocmai ai rulat installul).

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

- `POST /api/upload` — salvează fișierul temporar (se șterge automat după 6h)
- `GET /files/<id>` — servește fișierul pentru previzualizare
- `POST /api/print` — construiește comanda `lp` cu opțiunile alese
  (`sides=two-sided-long-edge`, `print-color-mode=monochrome`, `page-ranges` etc.)
  și înregistrează printarea în istoric
- `GET /api/history`, `DELETE /api/history` — istoricul printărilor
- `GET /api/printers`, `GET /api/jobs`, `POST /api/jobs/<id>/cancel` — stare și coadă

Fișierele încărcate sunt **temporare** (șterse automat după câteva ore) — nu se
salvează pe Pi. Se păstrează doar **istoricul** (nume, dată, opțiuni) într-o bază
SQLite (`cloudprint.db`), ca să știi ce s-a printat și când.

### Acces de pe telefon

Implicit aplicația rulează pe **`http://<ip>:8080`** — se deschide direct pe
telefon și pe laptop, fără certificat și fără avertismente, exact ca interfața
routerului. Pentru o rețea de casă e suficient.

**HTTPS (opțional).** Doar dacă vreun telefon refuză `http` către IP-uri locale
(ex. Chrome cu „Always use secure connections"), generezi un certificat
self-signed și aplicația pornește automat pe https:

```bash
./gen-cert.sh                       # FĂRĂ sudo, ca serviciul să poată citi cheia
sudo systemctl restart cloud-print
```

Dacă găsește `certs/cert.pem` + `certs/key.pem`, pornește pe `https://<ip>:8080`
(prima dată browserul cere *Advanced → Continue*, certificatul fiind autosemnat).
Ca să revii la http, șterge folderul `certs/` și repornește serviciul. Dacă
certificatul devine necitibil, aplicația revine automat pe http în loc să crape.

## Note

- Aplicația este gândită pentru **rețeaua locală** — nu o expune direct pe
  internet (nu are autentificare).
- Pentru documente Word/LibreOffice, salvează-le ca PDF înainte de încărcare
  (conversia pe un Pi Zero W ar fi prea lentă).
