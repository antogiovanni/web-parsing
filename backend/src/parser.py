import asyncio
import json
from urllib.parse import urlparse
from pydantic import BaseModel
from typing import Optional
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
import re

class RisultatoParser(BaseModel):
    url: str
    domain: str
    title: Optional[str] = None
    html_text: Optional[str] = None   # HTML grezzo richiesto
    parsed_text: Optional[str] = None # Markdown pulito richiesto
    success: bool
    error: Optional[str] = None

DOMAIN_CONFIGS = {
    "en.wikipedia.org": {
        "css_selector": ".mw-parser-output",
        "excluded_tags": ["table", "figure", "img"],
        "excluded_selector": ".hatnote, .navigation-not-searchable, .shortdescription",
        "word_count_threshold": 15
    },
    "www.treccani.it": {
        #"css_selector": "article", # Manteniamo commentato per evitare l'errore del testo vuoto
        "excluded_tags": ["nav", "footer", "script", "style", "aside", "figure", "img"],
        "excluded_selector": "aside, .breadcrumb, [class='tag'], [class='cat'], [class='correlat'], [class='related'], [class*='sidebar'], .metadata, .widget",
        "word_count_threshold": 15
    },
    "www.aljazeera.com": {
        # Escludiamo tutto ciò che è contorno: header, footer, navigazione laterale
        "excluded_tags": ["nav", "footer", "script", "style", "aside", "figure", "img", "header"],
        # Escludiamo i banner delle newsletter, pubblicità, e widget correlati tipici di Al Jazeera
        "excluded_selector": ".ad-unit, .newsletter-banner, .more-on, .social-share, .article__featured-image, [data-testid='social-share'], [data-testid='global-header'], .site-header, .accessibility-links, #menu-header",
        "word_count_threshold": 15
    }
}

def pulisci_markdown_wiki(testo_md: str) -> str:
    if not testo_md:
        return ""

    # Pulizia Bibliografia e Link Esterni
    pattern_fine_pagina = r'\n##+\s+(References|Bibliography|External links|See also|Further reading|Note|Bibliografia|Voci correlate|Collegamenti esterni)\b'
    parti = re.split(pattern_fine_pagina, testo_md, flags=re.IGNORECASE)
    testo_pulito = parti[0] 

    # Pulizia note
    testo_pulito = re.sub(r'\[[^\]]*\]\([^)]*#cite[^)]*\)', '', testo_pulito, flags=re.IGNORECASE)
    testo_pulito = re.sub(r'\([^)]*#cite[^)]*\)', '', testo_pulito, flags=re.IGNORECASE)
    testo_pulito = re.sub(r'\[\d+\]', '', testo_pulito) 

    # Pulizia Link Normali e Residui
    testo_pulito = re.sub(r'\[?\[edit\]\(.*?\)\]?', '', testo_pulito, flags=re.IGNORECASE)
    testo_pulito = re.sub(r'\[([^\]]+)\]\(.*?\)', r'\1', testo_pulito)
    testo_pulito = re.sub(r' "[^"]+"\)', '', testo_pulito)
    
    # 3. Pulizia Fonetica IPA (Molto più intelligente)
    # Intercetta il blocco parentesi se contiene roba come (/mɪˈnɜːrvə/ o la parola Latin/Etruscan
    testo_pulito = re.sub(r' \([^)]*(/[^)]*/|Latin:|Greek:|Etruscan:|IPA)[^)]*\)', '', testo_pulito, flags=re.IGNORECASE)
    testo_pulito = re.sub(r'\[\]', '', testo_pulito)
    testo_pulito = re.sub(r'\*\*\^\*\*', '', testo_pulito)
    testo_pulito = re.sub(r'\^\s*', '', testo_pulito)

    # 4. RIMOZIONE FORMATTAZIONE (Grassetto, Corsivo e Titoli)
    #testo_pulito = testo_pulito.replace('**', '')       
    #testo_pulito = re.sub(r'_([^_]+)_', r'\1', testo_pulito) 
    #testo_pulito = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', testo_pulito) 
    #testo_pulito = re.sub(r'^#+\s*', '', testo_pulito, flags=re.MULTILINE)  

    # Spaziature finali
    testo_pulito = re.sub(r'\n{3,}', '\n\n', testo_pulito)
    testo_pulito = re.sub(r'\[citation needed\]', '', testo_pulito, flags=re.IGNORECASE)
    
    # Rimozione spazi vuoti prima di virgole, punti e due punti (es: "parola ," -> "parola,")
    testo_pulito = re.sub(r'\s+([.,;:!])', r'\1', testo_pulito)
    
    # Pulizia eventuali doppie virgole residue (es: "parola,," -> "parola,")
    testo_pulito = testo_pulito.replace(',,', ',')
    
    # Gestisce "a capo" multipli
    testo_pulito = re.sub(r'\n{3,}', '\n\n', testo_pulito)
    
    return testo_pulito.strip()

def pulisci_markdown_treccani(testo_md: str) -> str:
    if not testo_md:
        return ""

    testo_pulito = re.sub(r'\[([^\]]+)\]\(.*?\)', r'\1', testo_md) 
    testo_pulito = re.sub(r'\[\]\(http.*?\)', '', testo_pulito)   
    #testo_pulito = testo_pulito.replace('**', '')       
    testo_pulito = re.sub(r'◆\s*', '', testo_pulito) 
    #testo_pulito = re.sub(r'_([^_]+)_', r'\1', testo_pulito) 
    #testo_pulito = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', testo_pulito) 
    #testo_pulito = re.sub(r'^#+\s*', '', testo_pulito, flags=re.MULTILINE)

    # Dividiamo il testo usando le parole chiave. \s*
    pattern_inizio = r'(?:Dal vocabolario|Vocabolario on line|Enciclopedia on line)\s*'
    parti_inizio = re.split(pattern_inizio, testo_pulito, flags=re.IGNORECASE)
    
    if len(parti_inizio) > 1:
        # Prende il testo DOPO l'ultima parola chiave trovata, 
        # Non prende categorie laterali e i finti menu
        testo_pulito = parti_inizio[-1] 
    else:
        # Se non trova i titoletti, taglia fino alla fine del menu
        testo_pulito = re.sub(r'^.*?(?:Lavora con noi|Cataloghi)\s*', '', testo_pulito, count=1, flags=re.IGNORECASE | re.DOTALL)

    # Taglio pie pagina
    pattern_fine = r'(?:\n\s*©|\n\s*Abbiamo a cuore la tua privacy|\n\s*Vai alla definizione|\n\s*\{"priclt")'
    testo_pulito = re.split(pattern_fine, testo_pulito, maxsplit=1, flags=re.IGNORECASE)[0]

    # Pulizia testo specifico e spaziatura
    testo_pulito = re.sub(r'^MAPPA\s*', '', testo_pulito, flags=re.MULTILINE)
    testo_pulito = re.sub(r'\s+([.,;:!])', r'\1', testo_pulito)
    testo_pulito = re.sub(r'\n{3,}', '\n\n', testo_pulito)

    return testo_pulito.strip()

def pulisci_markdown_aljazeera(testo_md: str) -> str:
    if not testo_md:
        return ""

    # 1. Rimuove link vuoti (es. l'icona autore o la home: [](https://www...))
    testo_pulito = re.sub(r'\[\]\(.*?\)', '', testo_md)
    
    # 2. Estrae il testo dai link rimanenti e rimuove le immagini
    testo_pulito = re.sub(r'\[([^\]]+)\]\(.*?\)', r'\1', testo_pulito)
    testo_pulito = re.sub(r'!\[.*?\]\(.*?\)', '', testo_pulito)
    
    # Elimina le righe che iniziano con "By "
    testo_pulito = re.sub(r'^By\s+.*$', '', testo_pulito, flags=re.MULTILINE | re.IGNORECASE)
    
    # Elimina le righe che iniziano con "Published On "
    testo_pulito = re.sub(r'^Published On\s+.*$', '', testo_pulito, flags=re.MULTILINE | re.IGNORECASE)

    # Elimina in blocco la sezione delle notizie consigliate (da "Recommended Stories" fino a "end of list")
    # [\s\S]*? serve a catturare qualsiasi carattere (compresi gli "a capo") in modo chirurgico
    testo_pulito = re.sub(r'Recommended Stories[\s\S]*?end of list', '', testo_pulito, flags=re.IGNORECASE)
    
    junk_patterns = [
        r'^Advertisement\s*$',
        r'^ListenListen.*$',
        r'^Save\s*$',
        r'^Click here to share.*$',
        r'^share-nodes\s*$',
        r'^Share\s*$',
        r'^facebookxwhatsapp.*$',
        r'^googleAdd Al Jazeera.*$',
        r'^notification-important.*$',
        r'^Yes, keep me updated\s*$',
        r'^aj-logo\s*$',
        r'^Your browser does not support.*$',
        r'^audio-.*$',
        r'^close\s*$'
    ]
    
    # Uniamo tutti i pattern per cancellare queste righe intere
    pattern_spazzatura = r'(?:' + '|'.join(junk_patterns) + r')'
    testo_pulito = re.sub(pattern_spazzatura, '', testo_pulito, flags=re.IGNORECASE | re.MULTILINE)

    # Rimuove il grassetto Markdown (**testo**) senza toccare gli asterischi dentro le parole (es. sh**hole)
    testo_pulito = re.sub(r'\*\*([^*]+)\*\*', r'\1', testo_pulito)
    testo_pulito = re.sub(r'_([^_]+)_', r'\1', testo_pulito)
    testo_pulito = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'\1', testo_pulito)
    testo_pulito = re.sub(r'^#+\s*', '', testo_pulito, flags=re.MULTILINE)

    testo_pulito = re.sub(r'^(?:Read more|Keep reading|Watch|Sign up for).*$', '', testo_pulito, flags=re.IGNORECASE | re.MULTILINE)
    testo_pulito = re.sub(r'^(?:Play Video|Video Duration).*$', '', testo_pulito, flags=re.IGNORECASE | re.MULTILINE)

    # Questa regex cerca l'inizio del tipico banner GDPR di Al Jazeera e taglia tutto ciò che segue.
    pattern_cookie_banner = r'(?:\n\s*You rely on Al Jazeera for truth and transparency|\n\s*We and our \d+ partners store and access personal data)'
    testo_pulito = re.split(pattern_cookie_banner, testo_pulito, maxsplit=1, flags=re.IGNORECASE)[0]
    
    # Pulizia spazi e punteggiatura
    testo_pulito = re.sub(r'\s+([.,;:!])', r'\1', testo_pulito)
    # Riduce le sequenze di spazi vuoti e "a capo" multipli generati dalla rimozione delle righe precedenti
    testo_pulito = re.sub(r'\n{3,}', '\n\n', testo_pulito)

    return testo_pulito.strip()

CLEANING_DISPATCHER = {
    "en.wikipedia.org": pulisci_markdown_wiki,
    "www.treccani.it": pulisci_markdown_treccani,
    "www.aljazeera.com": pulisci_markdown_aljazeera
}
async def esegui_estrazione(url: str, html_text: str = None) -> RisultatoParser:
    dominio = urlparse(url).netloc
    regole_speciali = DOMAIN_CONFIGS.get(dominio, {})

    browser_cfg = BrowserConfig(headless=True) 
    
    crawler_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        magic=True,
        **regole_speciali  # Questo applica correttamente css_selector ed excluded_selector!
    )
    
    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            
            # Switch dinamico: URL web vs Stringa HTML
            target_per_crawler = f"raw:{html_text}" if html_text else url
            
            result = await crawler.arun(url=target_per_crawler, config=crawler_cfg)
            
            if result.success and not result.markdown.startswith("Crawl4AI Error"):
                
                # Recupera la funzione giusta dal dizionario (di default non fa nulla se il dominio è ignoto)
                funzione_di_pulizia = CLEANING_DISPATCHER.get(dominio, lambda x: x)
                testo_finale = funzione_di_pulizia(result.markdown)
                html_di_riferimento = html_text if html_text else result.html

                titolo = "Senza Titolo"
                if hasattr(result, 'metadata') and isinstance(result.metadata, dict):
                    titolo = result.metadata.get('title', "Senza Titolo")
                # Fallback: se siamo in modalità raw HTML, metadata potrebbe essere vuoto, quindi guardiamo l'HTML
                elif html_di_riferimento:
                    match = re.search(r'<title>(.*?)</title>', html_di_riferimento, re.IGNORECASE)
                    if match:
                        titolo = match.group(1).replace(" - Wikipedia", "").strip()
                
                return RisultatoParser(
                    success=True, 
                    url=url,
                    domain=dominio,
                    title=titolo,
                    html_text=html_di_riferimento,
                    parsed_text=testo_finale,
                    error=None
                )
            else:
                messaggio_errore = result.error_message or result.markdown
                return RisultatoParser(
                    success=False, 
                    url=url,
                    domain=dominio,
                    error=f"Fallimento o espressione non valida: {messaggio_errore}"
                )
                
    except Exception as e:
        return RisultatoParser(
            success=False, 
            url=url,
            domain=dominio,
            error=f"Eccezione di sistema: {str(e)}"
        )