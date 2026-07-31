# Imagine pentru modul CLOUD (se deployează pe Dokploy / orice host Docker).
# NU are nevoie de CUPS — nu printează, doar servește interfața web și coada
# de joburi. Printarea o face agentul care rulează pe Raspberry Pi.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# datele persistente (baza SQLite, fișierele temporare, cheia de sesiune)
# stau într-un volum montat aici — vezi CLOUDPRINT_DATA_DIR
ENV CLOUDPRINT_MODE=cloud \
    CLOUDPRINT_DATA_DIR=/data \
    PORT=8080

EXPOSE 8080

# SQLite => o singură instanță; 2 workers + threads e suficient pentru uz casnic
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", \
     "--timeout", "120", "app:app"]
