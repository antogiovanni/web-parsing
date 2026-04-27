from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from collections import Counter
from urllib.parse import urlparse
from src.parser import esegui_estrazione, RisultatoParser, DOMAIN_CONFIGS
import uvicorn
import re
import json
import os
import mistune
from bs4 import BeautifulSoup

app = FastAPI(title="Backend Estrazione e Valutazione")

class RichiestaParse(BaseModel):
    url: str
    html_text: str

class RichiestaValutazione(BaseModel):
    parsed_text: str  
    gold_text: str    

class TokenLevelEval(BaseModel):
    precision: float
    recall: float
    f1: float

class RispostaValutazione(BaseModel):
    token_level_eval: TokenLevelEval
    x_eval: dict = {}

def remove_markdown(md: str) -> str:
    if not md: 
        return ""
    # Converte il markdown in HTML
    html = mistune.html(str(md))
    soup = BeautifulSoup(html, "html.parser")
    
    # Rimuove i tag lasciando il testo in-place
    for tag in soup.find_all(True):
        tag.unwrap()
        
    testo = str(soup)
    # Collassa spazi orizzontali e nuove linee multiple in una sola
    testo = re.sub(r'[ \t]+', ' ', testo)
    testo = re.sub(r'\n+', '\n', testo)
    
    return testo.strip()

@app.get("/domains")
def ottieni_domini():
    percorso_file = "domains.json" 
    if os.path.exists(percorso_file):
        with open(percorso_file, "r", encoding="utf-8") as f:
            lista_domini = json.load(f)
            # Ritorna l'oggetto con la chiave richiesta!
            return {"domains": lista_domini}
    return {"domains": []}

@app.get("/parse", response_model=RisultatoParser)
async def esegui_get_parse(url: str = Query(...)):
    dominio = urlparse(url).netloc
    
    # Controllo dominio
    if os.path.exists("domains.json"):
        with open("domains.json", "r", encoding="utf-8") as f:
            domini_validi = json.load(f)
            if dominio not in domini_validi:
                raise HTTPException(status_code=400, detail="Dominio non supportato")

    # Risolve incoerenza treccani?
    html_salvato = None
    try:
        gs = await recupera_full_gold_standard(dominio)
        for entry in gs.get("gold_standard", []):
            # Rimuoviamo gli slash finali (/)
            url_salvato = entry.get("url", "").rstrip("/")
            url_richiesto = url.rstrip("/")
            
            if url_salvato == url_richiesto:
                html_salvato = entry.get("html_text")
                break
    except Exception:
        pass 

    risultato = await esegui_estrazione(url=url, html_text=html_salvato)

    # Controllo pagina vuota/404
    if not risultato.success or not risultato.parsed_text or risultato.parsed_text.strip() == "":
        raise HTTPException(status_code=400, detail="URL irraggiungibile o pagina vuota")

    return risultato

@app.post("/parse", response_model=RisultatoParser)
async def esegui_post_parse(dati: RichiestaParse):
    dominio = urlparse(dati.url).netloc
    
    # Stesso controllo del dominio anche qui per sicurezza
    if os.path.exists("domains.json"):
        with open("domains.json", "r", encoding="utf-8") as f:
            domini_validi = json.load(f)
            if dominio not in domini_validi:
                raise HTTPException(status_code=400, detail="Dominio non supportato")

    risultato = await esegui_estrazione(url=dati.url, html_text=dati.html_text)

    # Controllo pagina vuota/404
    if not risultato.success or not risultato.parsed_text or risultato.parsed_text.strip() == "":
        raise HTTPException(status_code=400, detail="URL irraggiungibile o pagina vuota")

    return risultato

@app.get("/gold_standard")
async def recupera_gold_standard(url: str = Query(..., description="L'URL di cui cercare il Gold Standard")):
    dominio = urlparse(url).netloc
    nome_file = f"{dominio}_gs.json"

    cartella_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Dalla cartella principale, entriamo in gs_data e puntiamo al file
    percorso_file = os.path.join(cartella_base, "gs_data", nome_file)

    if os.path.exists(percorso_file):
        try:
            with open(percorso_file, "r", encoding="utf-8") as f:
                dati = json.load(f)
        
            for elemento in dati.get("gold_standard", []):
                if elemento.get("url") == url:
                    print(f"URL '{url}' trovato all'interno del JSON!")
                    return elemento
            
            print(f" ERRORE: file accessibile ma url: '{url}' mancante")
            raise HTTPException(status_code=404, detail="L'URL non è presente nel file JSON del Gold Standard.")
            
        except json.JSONDecodeError:
            print("ERRORE: non è possibile eseguire lettura o file scritto male.")
            raise HTTPException(status_code=500, detail="Il file JSON è corrotto o malformato.")
    else:
        raise HTTPException(status_code=404, detail="File del Gold Standard non trovato per questo dominio.")

@app.get("/full_gold_standard")
async def recupera_full_gold_standard(domain: str = Query(..., description="Il dominio da cercare")):
    
    # Se il grader invia un url completo prendiamo solo il dominio
    if "http" in domain:
        dominio_pulito = urlparse(domain).netloc
    else:
        dominio_pulito = domain
        
    nome_file = f"{dominio_pulito}_gs.json"
    cartella_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    percorso_file = os.path.join(cartella_base, "gs_data", nome_file)

    if os.path.exists(percorso_file):
        try:
            with open(percorso_file, "r", encoding="utf-8") as f:
                dati = json.load(f)
                # Restituisce l'intero contenuto
                return dati 
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Il file JSON è corrotto o malformato.")
    else:
        raise HTTPException(status_code=404, detail="Dominio non supportato o Gold Standard non trovato.")

@app.post("/evaluate", response_model=RispostaValutazione)
async def valuta_parsing(dati: RichiestaValutazione):
    try:
        t_p = remove_markdown(dati.parsed_text)
        t_g = remove_markdown(dati.gold_text)

        tokens_p = t_p.lower().split()
        tokens_g = t_g.lower().split()

        if not tokens_p or not tokens_g:
            return RispostaValutazione(token_level_eval=TokenLevelEval(precision=0.0, recall=0.0, f1=0.0))

        # Counter per fare l'intersezione "Bag of Words"
        c_p = Counter(tokens_p)
        c_g = Counter(tokens_g)
        intersezione = sum((c_p & c_g).values())
        
        p = intersezione / len(tokens_p)
        r = intersezione / len(tokens_g)
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0

        return RispostaValutazione(
            token_level_eval=TokenLevelEval(precision=round(p, 4), recall=round(r, 4), f1=round(f1, 4))
        )
    except Exception as e:
        return RispostaValutazione(token_level_eval=TokenLevelEval(precision=0.0, recall=0.0, f1=0.0))

@app.get("/full_gs_eval", response_model=RispostaValutazione)
async def valutazione_aggregata(domain: str = Query(...)):
    try:
        gs_data = await recupera_full_gold_standard(domain)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Dominio non supportato")

    voci_gs = gs_data.get("gold_standard", [])
    n_voci = len(voci_gs)

    if n_voci == 0:
        return RispostaValutazione(token_level_eval=TokenLevelEval(precision=0.0, recall=0.0, f1=0.0))

    precision_tot, recall_tot, f1_tot = 0.0, 0.0, 0.0
    count_validi = 0

    for entry in voci_gs:
        url = entry.get("url")
        html_salvato = entry.get("html_text", "")
        testo_oro = entry.get("gold_text", "")

        risultato = await esegui_estrazione(url=url, html_text=html_salvato)
        testo_estratto = risultato.parsed_text if risultato.success and risultato.parsed_text else ""

        testo_p_pulito = remove_markdown(testo_estratto)
        testo_g_pulito = remove_markdown(testo_oro)

        tokens_p = testo_p_pulito.lower().split()
        tokens_g = testo_g_pulito.lower().split()

        if tokens_p and tokens_g:
            c_p = Counter(tokens_p)
            c_g = Counter(tokens_g)
            intersezione = sum((c_p & c_g).values())
            
            p = intersezione / len(tokens_p)
            r = intersezione / len(tokens_g)
            f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0

            precision_tot += p
            recall_tot += r
            f1_tot += f
            count_validi += 1

    if count_validi == 0:
        return RispostaValutazione(token_level_eval=TokenLevelEval(precision=0.0, recall=0.0, f1=0.0))

    return RispostaValutazione(
        token_level_eval=TokenLevelEval(
            precision=round(precision_tot / count_validi, 4),
            recall=round(recall_tot / count_validi, 4),
            f1=round(f1_tot / count_validi, 4)
        )
    )
