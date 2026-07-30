# 🖨️ CloudPrint

Server local de printare pentru **Raspberry Pi** (inclusiv Pi Zero W). Rulează în
rețeaua ta locală și oferă o interfață web modernă din care oricine din casă poate
printa de pe telefon sau laptop — fără drivere, fără cabluri. Comunicarea cu
imprimanta se face prin **CUPS**.

## Cuprins

- [Funcționalități](#funcționalități)
- [De ce ai nevoie](#de-ce-ai-nevoie)
- [Instalare rapidă](#instalare-rapidă)
- [Configurarea imprimantei în CUPS](#configurarea-imprimantei-în-cups)
- [Acces de pe telefon](#acces-de-pe-telefon)
- [Gestionarea serviciului](#gestionarea-serviciului)
- [Actualizare](#actualizare)
- [Depanare](#depanare)
- [Rulare manuală (dezvoltare)](#rulare-manuală-dezvoltare)
- [Cum funcționează](#cum-funcționează)
- [Note](#note)

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
- **Istoric printări** — ce s-a printat, când și cu ce opțiuni. Fișierele nu se
  salvează — doar jurnalul, ca să știi ce a trecut prin imprimantă
- **Acces simplu de pe telefon** — rulează pe `http` (fără certificat, fără
  avertismente, exact ca interfața routerului); `https` opțional
- **Ușor pentru Pi Zero W** — doar Flask + comenzile CUPS + o mică bază SQLite
  (din biblioteca standard Python); toată randarea grea (previzualizarea PDF)
  se face în browserul clientului, nu pe Pi

## De ce ai nevoie

- Un **Raspberry Pi** cu **Raspberry Pi OS** (merge și pe Pi Zero W), conectat la
  rețeaua ta (WiFi sau cablu)
- O **imprimantă** — USB (legată la Pi) sau de rețea (WiFi/Ethernet)
- Acces la Pi prin **SSH** sau direct cu tastatură+monitor

> **Notă despre utilizator:** imaginile noi de Raspberry Pi OS nu mai au userul
> implicit `pi`. Scriptul de instalare folosește automat utilizatorul cu care îl
> rulezi — nu trebuie să faci nimic special.

## Instalare rapidă

Pe Pi, în terminal:

```bash
git clone https://github.com/aaldescu/cloud-print.git
cd cloud-print
./install.sh
```

Scriptul face totul automat:

1. instalează **CUPS** și **Flask**
2. te adaugă în grupul `lpadmin` (ca să poți administra imprimante)
3. activează administrarea CUPS din rețea (`cupsctl --remote-admin`)
4. instalează și pornește serviciul **systemd** (`cloud-print`), care va porni
   automat la fiecare boot

La final îți afișează adresa, de exemplu:

```
Gata! CloudPrint rulează la:  http://192.168.1.42:8080
```

> ⚠️ După prima instalare, dă **logout/login** (sau `newgrp lpadmin`) o dată, ca
> apartenența la grupul `lpadmin` să devină activă — altfel CUPS nu-ți acceptă
> parola când adaugi imprimanta.

## Configurarea imprimantei în CUPS

Se face **o singură dată**. Deschide interfața CUPS:

```
https://<ip-ul-pi>:631/admin
```

> **Atenție: cu `https`, nu `http`.** CUPS refuză pagina de administrare pe http
> simplu și afișează „Upgrade Required". Browserul va avertiza despre certificat
> (e autosemnat de CUPS, normal pe rețea locală) → apasă *Advanced → Continue*.

Autentifică-te cu **userul și parola de login pe Pi**, apoi
**Administration → Add Printer**.

### Imprimantă USB

Apare în lista „Local Printers". O selectezi, dai Continue, alegi driverul
sugerat și gata.

### Imprimantă de rețea (WiFi/Ethernet)

1. Conectează imprimanta la aceeași rețea ca Pi-ul și află-i IP-ul.
2. La **Add Printer**, cel mai probabil apare deja la „Discovered Network
   Printers" ca `... (driverless)` — selecteaz-o pe aceea.
3. Dacă nu apare, alege **Internet Printing Protocol (ipp)** și pune la
   Connection:
   ```
   ipp://<ip-imprimanta>/ipp/print
   ```
4. La **nume** pune ceva **fără spații** (ex. `HP_M140w`) — numele apare în
   CloudPrint.
5. La driver alege **IPP Everywhere** dacă există (majoritatea imprimantelor
   moderne, ex. HP LaserJet M140w, îl suportă — nu-ți trebuie driver de la
   producător). Dacă nu apare, instalează driverele HP și reîncearcă:
   ```bash
   sudo apt-get install -y printer-driver-hpcups hplip
   ```

### Setează imprimanta implicită și testeaz-o

```bash
lpoptions -d HP_M140w      # imprimanta implicită (pune numele tău)
lpstat -p                  # apare și e "idle"?
echo "test CloudPrint" | lp
```

Odată adăugată în CUPS, imprimanta apare automat în CloudPrint (dropdown-ul de
imprimante) — dă refresh la pagină.

## Acces de pe telefon

Implicit aplicația rulează pe **`http://<ip-ul-pi>:8080`** — se deschide direct
pe telefon și pe laptop, fără certificat și fără avertismente, exact ca interfața
routerului. Pentru o rețea de casă e suficient.

Ca să nu ții minte IP-ul, poți încerca și `http://<hostname>.local:8080` (ex.
`http://raspberrypi.local:8080`). Adaugă pagina la ecranul principal al
telefonului („Add to Home Screen") și o deschizi ca pe o aplicație.

### HTTPS (opțional)

Doar dacă vreun telefon refuză `http` către IP-uri locale (ex. Chrome cu
„Always use secure connections" activat), generezi un certificat self-signed și
aplicația pornește automat pe https:

```bash
./gen-cert.sh                       # FĂRĂ sudo, ca serviciul să poată citi cheia
sudo systemctl restart cloud-print
```

Dacă găsește `certs/cert.pem` + `certs/key.pem`, aplicația pornește pe
`https://<ip>:8080` (prima dată browserul cere *Advanced → Continue*).
Ca să revii la http, șterge folderul `certs/` și repornește serviciul. Dacă
certificatul devine necitibil, aplicația revine automat pe http în loc să crape.

## Gestionarea serviciului

```bash
systemctl status cloud-print        # rulează? (caută "active (running)")
sudo systemctl restart cloud-print  # repornește
sudo systemctl stop cloud-print     # oprește
sudo systemctl start cloud-print    # pornește
journalctl -u cloud-print -n 30 --no-pager   # ultimele mesaje / erori
```

## Actualizare

```bash
cd cloud-print
git pull
sudo systemctl restart cloud-print
```

Baza de date cu istoricul (`cloudprint.db`) se creează singură și se păstrează
între actualizări.

## Depanare

**„CloudPrint nu se deschide în browser"**
Verifică întâi că serviciul rulează: `systemctl is-active cloud-print`. Dacă zice
altceva decât `active`, pornește-l și vezi eroarea:
```bash
sudo systemctl restart cloud-print
journalctl -u cloud-print -n 30 --no-pager
```

**„Nu se deschide pe telefon (loop / nu se încarcă nimic)"**
De obicei telefonul nu ajunge la Pi în rețea. Testează pe telefon
`http://<ip-ul-pi>:631` (pagina CUPS):
- dacă **nici** asta nu se încarcă → telefonul e pe altă rețea (date mobile sau
  WiFi „Guest"), ori routerul are **AP/Client isolation** activat (blochează
  comunicarea între dispozitive). Pune telefonul pe WiFi-ul principal.
- dacă CUPS **se** încarcă → rețeaua e ok, e doar aplicația: verifică IP-ul și
  portul `8080`.

**„CUPS zice Upgrade Required la Administration"**
Accesează cu **`https://<ip>:631/admin`** (cu httpS), nu http.

**„usermod: user 'pi' does not exist" la instalare**
Imaginile noi de Raspberry Pi OS nu mai au userul `pi`. Versiunea actuală a
scriptului folosește userul curent — dă `git pull` și rulează din nou
`./install.sh`.

**Imprimanta nu apare în CloudPrint**
Verifică în CUPS că e adăugată și „idle" (`lpstat -p`). Dă refresh la pagina
CloudPrint (dropdown-ul de imprimante se reîncarcă).

**IP-ul Pi-ului se schimbă după reboot**
Rezervă-i un **IP fix** din router (DHCP reservation / Reserved IP), ca adresa
`http://<ip>:8080` să rămână constantă. (Dacă folosești https, la schimbarea
IP-ului trebuie regenerat certificatul cu `./gen-cert.sh`.)

## Rulare manuală (dezvoltare)

Fără systemd, direct din terminal:

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

Endpoint-uri:

- `POST /api/upload` — salvează fișierul temporar (se șterge automat după câteva ore)
- `GET /files/<id>` — servește fișierul pentru previzualizare
- `POST /api/print` — construiește comanda `lp` cu opțiunile alese
  (`sides=two-sided-long-edge`, `print-color-mode=monochrome`, `page-ranges` etc.)
  și înregistrează printarea în istoric
- `GET /api/history`, `DELETE /api/history` — istoricul printărilor
- `GET /api/printers`, `GET /api/jobs`, `POST /api/jobs/<id>/cancel` — stare și coadă

Fișierele încărcate sunt **temporare** (șterse automat) — nu se salvează pe Pi.
Se păstrează doar **istoricul** (nume, dată, opțiuni) într-o bază SQLite
(`cloudprint.db`).

## Note

- Aplicația este gândită pentru **rețeaua locală** — nu o expune direct pe
  internet (nu are autentificare).
- Pentru documente Word/LibreOffice, salvează-le ca **PDF** înainte de încărcare
  (conversia pe un Pi Zero W ar fi prea lentă).
