# ------------------------------
# 0) LIBRERIE
# ------------------------------

# [GENERICHE]
import requests                     # serve per leggere la pagina interne
from datetime import datetime       # serve per ottenere data odierna
import time                         # serve per lo sleep
import os                           # serve per ottenere path progetto attuale
import pandas as pd                 # serve per strutturare i dati prima di metterli nel google sheet                 
import inspect                      # serve per avere info sui log (funzione chiamante)
import traceback                    # serve per avere info sui log (stack di chiamate)
import numbers                      # serve per per verificare se una variabile è numerica
import random                       # serve per per generare numeri casuali
import logging                      # serve per i log
import sys                          # serve per vedere i log su docker
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
import psutil                       # serve per monitorare l'uso di ram/cpu
import signal                       # serve per gestire segnali di terminazione processo

# [SQL]
import psycopg2                     # serve per connettersi a db postgre-sql
from supabase import create_client  # serve per connettersi al db in cloud (supabase)

# [INVIO MAIL]
import smtplib 
from email.message import EmailMessage

# [GOOGLE]: google api e google sheet
import gspread                                                      # serve per comunicare con google sheet
from oauth2client.service_account import ServiceAccountCredentials  # serve per comunicare con google api

# [BEAUTIFULSOUP]: serve per lo scraping statico (homepage di vinted)
from bs4 import BeautifulSoup       

# [SELENIUM]: serve per lo scraping dinamico (pagine annunci)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException


# ------------------------------
# 1) VARIABILI GLOBALI
# ------------------------------
# [VARIABILI GLOBALI]
driver = None
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
numeric_level = getattr(logging, log_level, logging.INFO)
logging.basicConfig(level=numeric_level, format='[%(asctime)s] [%(levelname)s] %(message)s')

log_err_file = "log_errori.txt"   # file di log locale

sql_supbase_url = os.environ["SUPABASE_URL"]
sql_supbase_key = os.environ["SUPABASE_KEY"]
email_tracker_user = os.environ["VINTED_MAIL_USER"]
email_tracker_pass = os.environ["VINTED_MAIL_PASS"]

#os.environ['DISPLAY'] = ':99' # necessario per eseguire chrome in docker

# ------------------------------
# 2) FUNZIONI
# ------------------------------
# [FUNZIONI LATO SQL]
def sql_connection():
    sql_url = sql_supbase_url
    sql_key = sql_supbase_key
    
    try:
        sql = create_client(sql_url, sql_key)
    except Exception as e:
        logging.error(f"[EXCEPTION]: 'sql_connectio': impossibile connettersi a supabase")
        save_exception(sql, e, "sql_connection")
    return sql

def save_exception(sql, error, info = "", note = ""):    
    global id_sessione
    
    log_errore = {
        "sessione": id_sessione if 'id_sessione' in globals() else int(time.time()),
        "funzione": inspect.stack()[1].function,
        "tipo": type(error).__name__,
        "descrizione": str(error),
        "stack": traceback.format_exc(),
        "info": info,
        "note": note
    }
    
    try:
        if sql:  # Controlla che sql non sia None
            sql.table("log_errori").insert(log_errore).execute()
    except Exception as e:
        logging.error(f"[EXCEPTION]: 'save_exception': impossibile salvare errore log a db -> salvo su file locale")
        with open(log_err_file, "a", encoding="utf-8") as f:
            f.write(str(log_errore) + os.linesep)
            
    return

def ricerca_ready(sql, homepage):
    try:
        if int_format(homepage.cnt_ripetizioni) <= 0:
            sql.table("ricerche") \
                .update({"cnt_ripetizioni": int_format(homepage.cnt_max_ripetizioni)}) \
                .eq("id", int_format(homepage.id)) \
                .execute()
            return True
        else:
            sql.table("ricerche") \
                .update({"cnt_ripetizioni": (int_format(homepage.cnt_ripetizioni) - 1)}) \
                .eq("id", int_format(homepage.id)) \
                .execute()
            return False
        
    except Exception as e:
        logging.error(f"[EXCEPTION]: 'ricerca_ready': impossibile aggiornare cnt_ripetizioni per homepage {homepage.link}")
        save_exception(sql, e, "ricerca_ready check cnt_ripetizioni")
        return False
        

# [FUNZIONI DI SCRAPING]
def safe_find_text(driver, by, locator, default= ""):
    try:
        return driver.find_element(by, locator).text.strip()
    except NoSuchElementException:
        logging.error(f"[EXCEPTION]: 'safe_find_text': impossibile trovare il dato con locator {locator}")
        return default
    
def fetch_annunci_urls(sql, homepage):
    try:
        html = requests.get(homepage.link, headers={ "User-Agent": "Mozilla/5.0" }) # richiesta lettura pagina html (homepage vinted)
        html.raise_for_status()

        soup = BeautifulSoup(html.content, "html.parser")                 # ristrutturazione come formato beautifulsoup
        
        soup_href = soup.find_all("a", class_="new-item-box__overlay new-item-box__overlay--clickable") # (scraping) link degli annunci
    except Exception as e:
        logging.error(f"[EXCEPTION]: 'fetch_annunci_urls': impossibile fare scraping homepage {homepage.link}")
        save_exception(sql, e, "fetch_annunci_urls scraping")
        return []
    
    urls = []
    cnt = 1
    for soup in soup_href:
        try:
            urls.append(soup["href"])               # link al singolo annuncio
            cnt += 1
            if ( cnt > homepage.max_annunci) :  # limite di annunci da leggere per ciascuna homepage
                break
        except Exception as e:
            logging.error(f"[EXCEPTION]: 'fetch_annunci_urls': impossibile recuperare url annunci da {homepage.link}")
            save_exception(sql, e, "fetch_annunci_urls loop")
            continue
    
    return urls                                 # lista dei link degli annunci

def fetch_info(sql, homepage, annuncio_url, driver):
    try:
        driver.get(annuncio_url)                             # lettura pagina html con scraping dinamico
        time.sleep(5)
    except Exception as e:
        save_exception(sql, e, "fetch_info driver.get")
        return {}
    
    try:        # reperimento dati prodotto
        categoria = homepage.categoria
        ricerca = homepage.ricerca
        link = annuncio_url
        titolo = safe_find_text(driver, By.XPATH, "//h1[contains(@class, 'web_ui__Text__text')]")
        descrizione = safe_find_text(driver, By.XPATH, "//div[@itemprop='description']//span[@class='web_ui__Text__text web_ui__Text__body web_ui__Text__left web_ui__Text__format']/span")
        prezzo_netto = price_format(safe_find_text(driver, By.XPATH, "//p[contains(@class, 'web_ui__Text__text')]"))
        prezzo_lordo = price_format(safe_find_text(driver, By.XPATH, "//div[contains(@class, 'web_ui__Text__text')]"))
        prezzo_spedizione = price_format(safe_find_text(driver, By.XPATH, "//*[@data-testid='item-shipping-banner--suffix']"))
        prezzo_soglia = price_format(homepage.prezzo)
        condizioni = safe_find_text(driver, By.CSS_SELECTOR, "div.summary-max-lines-4 > span.web_ui__Text__text.web_ui__Text__body.web_ui__Text__left")
        nazione = safe_find_text(driver, By.XPATH, "//div[contains(@class, 'u-flexbox u-align-items-baseline')]/div[last()]")
        caricato = safe_find_text(driver, By.XPATH, "//div[@itemprop='upload_date']/span")
        offerta = price_format(prezzo_lordo) <= price_format(prezzo_soglia)

        prodotto = {"sessione": id_sessione,
                    "categoria": categoria if categoria != None else "",
                    "ricerca": ricerca if ricerca != None else "",
                    "titolo": titolo if titolo != None else "",
                    "link": link if link != None else "",
                    "descrizione": descrizione if descrizione != None else "",
                    "prezzo_netto": prezzo_netto,
                    "prezzo_lordo": prezzo_lordo,
                    "prezzo_spedizione": prezzo_spedizione,
                    "prezzo_soglia": prezzo_soglia,
                    "caricato": caricato if caricato != None else "",
                    "condizioni": condizioni if condizioni != None else "",
                    "nazione": nazione if nazione != None else "",
                    "note": "",
                    "offerta": offerta,
                   }
        
    except Exception as e:
        save_exception(sql, e, "fetch_info dati prodotto")
        prodotto = {"sessione": id_sessione,
                    "categoria": categoria if categoria != None else "",
                    "ricerca": ricerca if ricerca != None else "",
                    "titolo": None,
                    "link": link if link != None else "",
                    "descrizione": None,
                    "prezzo_netto": None,
                    "prezzo_lordo": None,
                    "prezzo_spedizione": None,
                    "prezzo_soglia": None,
                    "caricato": None,
                    "condizioni": None,
                    "nazione": None,
                    "note": f"ERRORE: {e}",
                    "offerta": False
                   }
    
    return prodotto                 # info del prodotto del singolo annuncio

# [FUNZIONI MAIL]
def send_mail(sql, homepage, prodotti):
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[VINTED TRACKER] - {homepage.categoria} - {homepage.ricerca}"
        msg["From"] = email_tracker_user
        msg["To"] = homepage.email if homepage.email != None and homepage.email != None else email_tracker_user
        
        msg_txt = ""
        for prodotto in prodotti:
            if prodotto["offerta"] == True:
                msg_txt += ("\n\n---------------------\n"
                            f"LINK: {prodotto['link']}\n"
                            f"TITOLO: {prodotto['titolo']} \n"
                            f"DESCRIZIONE: {prodotto['descrizione']}\n"
                            f"CONDIZIONE: {prodotto['condizioni']}\n"
                            f"CARICATO: {prodotto['caricato']} \n"
                            f"PREZZO: {price_format_str(prodotto['prezzo_netto'])} / {price_format_str(prodotto['prezzo_lordo'])} / {price_format_str(prodotto['prezzo_spedizione'])}\n"
                            f"PREZZO TOT: {price_format_str(price_format(prodotto['prezzo_lordo']) + price_format(prodotto['prezzo_spedizione']))} \n"
                            "---------------------"
                            )
                        
        if  (len(msg_txt.strip()) > 0) :
            msg.set_content(f"Riepilogo offerte trovate per \n"
                            f"CATEGORIA: {homepage.categoria}  \n"
                            f"RICERCA: {homepage.ricerca} \n"
                            f"PREZZO SOGLIA: {price_format_str(homepage.prezzo)} \n"
                            + msg_txt)
            
    except Exception as e:
        logging.error(f"[EXCEPTION]: 'send_mail': impossibile completare dati mail")
        save_exception(sql, e, "send_mail setup", f"FROM: {msg['From']} - TO: {msg['To']} - TEXT: {msg_txt}")
        return

    # Invia la mail tramite SMTP
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(email_tracker_user, email_tracker_pass)
            smtp.send_message(msg)
    except Exception as e:
        logging.error(f"[EXCEPTION]: 'send_mail': impossibile inviare mail a {msg['To']}")
        save_exception(sql, e, "send_mail invio", f"FROM: {msg['From']} - TO: {msg['To']} - TEXT: {msg_txt}")
        return
    
    return

# [FUNZIONI UTILITY]
def int_format(numero):
    try:
        return int(numero)
    except:
        logging.error(f"[EXCEPTION]: 'int_format': impossibile convertire {numero} in intero")
        return 0

def price_format(prezzo):
    if prezzo == None:
        return None
    
    if isinstance(prezzo, numbers.Number):
        return float(prezzo)
        
    prezzo = prezzo.replace("€", "").strip()
    prezzo = prezzo.replace(",", ".").strip()
    prezzo = prezzo.replace("da", "").strip()
    prezzo = prezzo.replace(" ", "").strip()
    
    try:
        prezzo = float(prezzo)
    except:
        logging.error(f"[EXCEPTION]: 'price_format': impossibile convertire {prezzo} in prezzo float")
        prezzo = 0.0
    return prezzo

def price_format_str(prezzo):
    try:
        return f"{price_format(prezzo):.2f}€"
    except:
        logging.error(f"[EXCEPTION]: 'price_format_str': impossibile convertire {prezzo} in prezzo formattato")
        return "ERROR €"


def create_optimized_driver():      # serve per oracle server che ha ram limitata a 1GB
    options = webdriver.ChromeOptions()
    
    # Opzioni esistenti (mantieni)
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    # AGGIUNGI queste per ottimizzare RAM:
    options.add_argument("--memory-pressure-off")
    options.add_argument("--max_old_space_size=400")  # Max 400MB per V8
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-images")  # Non carica immagini (risparmia RAM)
    options.add_argument("--single-process")  # Un solo processo
    
    return webdriver.Chrome(options=options)

def check_memory():
    memory = psutil.virtual_memory()
    logging.info(f"RAM: {memory.percent}% usata, {memory.available/1024/1024:.0f}MB disponibili")
    
    if memory.percent > 85:  # Se supera 85% RAM
        logging.warning(f"[EXCEPTION - WARNING] RAM alta! Potrebbe servire restart driver: RAM: {memory.percent}% usata, {memory.available/1024/1024:.0f}MB disponibili")
        return True
    return False

def signal_handler(sig, frame):
    """Gestisce la chiusura graceful del programma"""
    logging.info("Ricevuto segnale di chiusura...")
    global driver
    if driver:
        try:
            driver.quit()
            logging.info("Driver Selenium chiuso correttamente")
        except:
            logging.error("[EXCEPTION] Errore nella chiusura del driver")
    sys.exit(0)


# ------------------------------
# 3) MAIN
# ------------------------------
if __name__ == "__main__":
    
    logging.info("----------------------------------------")
    logging.info("--- INIZIO ESECUZIONE VINTED TRACKER ---")
    logging.info("----------------------------------------")
    
    # Registra i signal handler
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Terminazione sistema
    logging.info("Signal handlers registrati")
    
    intervallo = 15 * 60  # 15 minuti
    path_progetto = os.path.dirname(os.path.abspath(__file__))
    
    sql = sql_connection()

    while True:
        id_sessione = int(time.time())   # secondi dall'epoch
        start = time.time()
        
        logging.info(f"--- Inizio Sessione {id_sessione} ---")
        
        # --- Creazione driver se non esiste ---
        if driver is None:
            try:
                logging.info(f"Installazione driver selenium")
                options = webdriver.ChromeOptions()
                options.add_argument("--headless=new")  # headless moderno
                options.add_argument("--no-sandbox")    # necessario in Docker
                options.add_argument("--disable-dev-shm-usage")  # evita problemi memoria condivisa
                options.add_argument("--disable-gpu")   # se serve

                #[DA LOCALE PER TEST] nel caso vada installato manualmente il driver
                #driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),options=options)
                #[DA DOCKER] nel caso sia già installato (già presente sulll'immagine base di docker)
                #driver = webdriver.Chrome(options=options)
                #[PER SERVER ORACLE]
                driver = create_optimized_driver()
                
            except Exception as e:
                logging.error(f"[EXCEPTION]: Installazione driver selenium ---")
                save_exception(sql, e, "driver selenium")
                time.sleep(60)  # attendi un minuto prima di riprovare
                continue
        
        # --- Recupero ricerche ---
        try:
            logging.info(f"Recupero homepage da ricercare dal db")
            #ricerche = sql.table("ricerche").select("*").execute()
            #ricerche = pd.DataFrame(ricerche.data)
            ricerche_result = sql.table("ricerche").select("*").execute()
            if hasattr(ricerche_result, "data") and ricerche_result.data is not None:
                ricerche = pd.DataFrame(ricerche_result.data)
            else:
                logging.error(f"[EXCEPTION]: Select * From ricerche did not return data: {getattr(ricerche_result, 'error', 'Unknown error')}")
                time.sleep(60)
                continue
        except Exception as e:
            logging.error(f"[EXCEPTION]: Select * From ricerche")
            save_exception(sql, e, "fetch ricerche")
            sql = sql_connection()
            time.sleep(60)
            continue
        
        # --- Loop sulle homepage ---
        for homepage in ricerche.itertuples(index=False):
            prodotti = []
            if not homepage.abilitato:
                logging.info(f"{homepage.categoria} - {homepage.ricerca} - {homepage.link} non attiva -> skip")
                continue

            if ricerca_ready(sql, homepage):
                logging.info(f"{homepage.categoria} - {homepage.ricerca} - {homepage.link} attiva -> avvio ricerca annunci")
                try:
                    annunci_urls = fetch_annunci_urls(sql, homepage)
                except Exception as e:
                    logging.error(f"[EXCEPTION]: fetch_annunci_urls -> skip homepage")
                    save_exception(sql, e, "fetch_annunci_urls")
                    continue

                for annuncio in annunci_urls:
                    try:
                        logging.info(f"{annuncio} -> avvio ricerca info prodotto")
                        prodotti.append(fetch_info(sql, homepage, annuncio, driver))
                        time.sleep(random.uniform(0.5, 1.5))
                    except Exception as e:
                        logging.error(f"[EXCEPTION]: fetch_info loop -> skip annuncio")
                        save_exception(sql, e, "fetch_info loop")
                        continue

                if prodotti:
                    try:
                        logging.info(f"Inizio invio mail")
                        send_mail(sql, homepage, prodotti)
                        logging.info(f"Inizio salvataggio dati a db (prodotti)")
                        prodotti_df = pd.DataFrame(prodotti).to_dict(orient="records")
                        sql.table("prodotti").insert(prodotti_df).execute()
                    except Exception as e:
                        logging.error(f"[EXCEPTION]: invio mail / inserimento prodotti a db")
                        save_exception(sql, e, "inserimento prodotti / invio mail")
                        sql = sql_connection()
                        
                if check_memory():      # controlla RAM driver
                    try:
                        driver.quit()
                        driver = None  # Verrà ricreato al prossimo ciclo
                        time.sleep(5)
                    except:
                        pass
        
        # --- Pulizia duplicati ---
        try:
            logging.info(f"Inizio eliminazione duplicati")
            sql.rpc("delete_old_duplicates").execute()
        except Exception as e:
            logging.error(f"[EXCEPTION]: esecuzione delete_old_duplicates per eliminazione duplicati")
            save_exception(sql, e, "delete_old_duplicates")
            sql = sql_connection()

        # --- Calcolo sleep per intervallo fisso ---
        durata = time.time() - start
        logging.info(f"--- Fine Sessione {id_sessione} - Durata: {durata:.2f} sec ---")
        logging.info(f"--- Tempo alla prossima esecuzione {intervallo - durata} sec ---")
        if durata < intervallo:
            time.sleep(intervallo - durata)

        # --- Ri-creazione driver ogni ciclo (opzionale) ---
        try:
            logging.info(f"Chiusura driver selenium")
            driver.quit()
            driver = None
        except:
            logging.error(f"[EXCEPTION] Chiusura driver selenium")
            driver = None