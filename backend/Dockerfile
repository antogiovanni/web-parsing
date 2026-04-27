# Usa un'immagine Python 3.11 leggera come base
FROM python:3.11-slim

# Imposta la cartella di lavoro principale dentro il container
WORKDIR /app

# 1. Installa le librerie di sistema essenziali per i browser
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 2. Copia il file dei requisiti e installa le librerie Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Scarica Chromium e le sue dipendenze usando il modulo python 
# (Questo trucco evita l'errore "playwright: not found")
RUN python -m playwright install chromium
RUN python -m playwright install-deps chromium

# 4. Copia tutto il codice sorgente del backend
COPY src/ /app/src/

# 5. Espone la porta 8003 (Requisito dell'esonero)
EXPOSE 8003

# 6. Avvia il server FastAPI usando Uvicorn
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8003"]