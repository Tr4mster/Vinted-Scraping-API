# vinted_tracker_github.py
# Versione ottimizzata per GitHub Actions (senza while loop)

# ------------------------------
# 0) LIBRERIE (identiche al tuo codice originale)
# ------------------------------

import requests
from datetime import datetime
import time
import os
import pandas as pd
import inspect
import traceback
import numbers
import random
import logging
import sys
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
import psutil
import signal

import psycopg2
from supabase import create_client

import smtplib 
from email.message import EmailMessage

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException

# ------------------------------
# 1) VARIABILI GLOBALI
# ------------------------------
driver = None
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
numeric_level = getattr(logging, log_level, logging.INFO)
logging.basicConfig(
    level=numeric_level, 
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('vinted_tracker.log', encoding='utf-8')
    ]
)

log_err_file = "log_errori.txt"

sql_supbase_url = os.getenv("SUPABASE_URL")
sql_supbase_key = os.getenv("SUPABASE_KEY")
email_tracker_user = os.getenv("VINTED_MAIL_USER")
email_tracker_pass = os.getenv("VINTED_MAIL_PASS")

# ------------------------------
# 2) FUNZIONI (identiche al tuo codice)
# ------------------------------

def sql_connection():
    sql_url = sql_supbase_url
    sql_key = sql_supbase_key
    
    try:
        sql = create_client(sql_url, sql_key)
        logging.info("✅ Connessione Supabase stabilita")
    except Exception as e:
        logging.error(f"❌ Impossibile connettersi a Supabase: {e}")
        save_exception(None, e, "sql_connection")
        raise
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
        if sql:
            sql.table("log_errori").insert(log_errore).execute()
    except Exception as e:
        logging.error(f"❌ Impossibile salvare errore su DB -> salvo su file locale")
        with open(log_err_file, "a", encoding="utf-8") as f:
            f.write(str(log_errore) + os.linesep)

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
        logging.error(f"❌ Errore aggiornamento cnt_ripetizioni per {homepage.link}")
        save_exception(sql, e, "ricerca_ready")
        return False

def safe_find_text(driver, by, locator, default=""):
    try:
        return driver.find_element(by, locator).text.strip()
    except NoSuchElementException:
        logging.debug(f"⚠️ Elemento non trovato: {locator}")
        return default

def fetch_annunci_urls(sql, homepage):
    try:
        logging.info(f"🔍 Scraping homepage: {homepage.categoria} - {homepage.ricerca}")
        html = requests.get(homepage.link, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        html.raise_for_status()

        soup = BeautifulSoup(html.content, "html.parser")
        soup_href = soup.find_all("a", class_="new-item-box__overlay new-item-box__overlay--clickable")
        
        urls = []
        for i, soup in enumerate(soup_href):
            if i >= homepage.max_annunci:
                break
            try:
                urls.append(soup["href"])
            except Exception as e:
                logging.warning(f"⚠️ Errore recupero URL annuncio #{i}: {e}")
                continue
                
        logging.info(f"📋 Trovati {len(urls)} annunci per {homepage.categoria}")
        return urls
        
    except Exception as e:
        logging.error(f"❌ Errore scraping homepage {homepage.link}: {e}")
        save_exception(sql, e, "fetch_annunci_urls")
        return []

def fetch_info(sql, homepage, annuncio_url, driver):
    try:
        logging.debug(f"📄 Elaboro annuncio: {annuncio_url}")
        driver.get(annuncio_url)
        time.sleep(random.uniform(3, 7))  # Random delay
    except Exception as e:
        save_exception(sql, e, "fetch_info driver.get")
        return {}
    
    try:
        # [CODICE IDENTICO AL TUO - solo con più logging]
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

        prodotto = {
            "sessione": id_sessione,
            "categoria": categoria or "",
            "ricerca": ricerca or "",
            "titolo": titolo or "",
            "link": link or "",
            "descrizione": descrizione or "",
            "prezzo_netto": prezzo_netto,
            "prezzo_lordo": prezzo_lordo,
            "prezzo_spedizione": prezzo_spedizione,
            "prezzo_soglia": prezzo_soglia,
            "caricato": caricato or "",
            "condizioni": condizioni or "",
            "nazione": nazione or "",
            "note": "",
            "offerta": offerta,
        }
        
        if offerta:
            logging.info(f"🎯 OFFERTA TROVATA: {titolo} - {price_format_str(prezzo_lordo)}")
        
        return prodotto
        
    except Exception as e:
        logging.error(f"❌ Errore elaborazione annuncio {annuncio_url}: {e}")
        save_exception(sql, e, "fetch_info dati prodotto")
        return {
            "sessione": id_sessione,
            "categoria": categoria or "",
            "ricerca": ricerca or "",
            "titolo": None,
            "link": link or "",
            "note": f"ERRORE: {e}",
            "offerta": False
        }

def send_mail(sql, homepage, prodotti):
    try:
        # Filtra solo le offerte
        offerte = [p for p in prodotti if p.get("offerta", False)]
        
        if not offerte:
            logging.info(f"📭 Nessuna offerta trovata per {homepage.categoria} - {homepage.ricerca}")
            return
            
        logging.info(f"📧 Invio mail con {len(offerte)} offerte per {homepage.categoria}")
        
        msg = EmailMessage()
        msg["Subject"] = f"🎯 [VINTED] {len(offerte)} offerte - {homepage.categoria} - {homepage.ricerca}"
        msg["From"] = email_tracker_user
        msg["To"] = homepage.email if homepage.email else email_tracker_user
        
        msg_txt = f"🔍 RICERCA: {homepage.ricerca}\n💰 SOGLIA: {price_format_str(homepage.prezzo)}\n\n"
        
        for i, prodotto in enumerate(offerte, 1):
            msg_txt += (f"\n{'='*50}\n"
                       f"🏷️ OFFERTA #{i}\n"
                       f"📌 LINK: {prodotto['link']}\n"
                       f"📝 TITOLO: {prodotto['titolo']}\n"
                       f"💬 DESCRIZIONE: {prodotto['descrizione'][:200]}...\n"
                       f"🔧 CONDIZIONI: {prodotto['condizioni']}\n"
                       f"📅 CARICATO: {prodotto['caricato']}\n"
                       f"💵 PREZZO: {price_format_str(prodotto['prezzo_netto'])} / {price_format_str(prodotto['prezzo_lordo'])} + {price_format_str(prodotto['prezzo_spedizione'])}\n"
                       f"💰 TOTALE: {price_format_str(price_format(prodotto['prezzo_lordo']) + price_format(prodotto['prezzo_spedizione']))}\n"
                       f"{'='*50}")
        
        msg.set_content(msg_txt)
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(email_tracker_user, email_tracker_pass)
            smtp.send_message(msg)
            
        logging.info(f"✅ Mail inviata con successo a {msg['To']}")
        
    except Exception as e:
        logging.error(f"❌ Errore invio mail: {e}")
        save_exception(sql, e, "send_mail")

# [FUNZIONI UTILITY - identiche al tuo codice]
def int_format(numero):
    try:
        return int(numero)
    except:
        return 0

def price_format(prezzo):
    if prezzo is None:
        return None
    if isinstance(prezzo, numbers.Number):
        return float(prezzo)
    prezzo = str(prezzo).replace("€", "").replace(",", ".").replace("da", "").replace(" ", "").strip()
    try:
        return float(prezzo)
    except:
        return 0.0

def price_format_str(prezzo):
    try:
        return f"{price_format(prezzo):.2f}€"
    except:
        return "ERROR €"

def create_github_driver():
    """Driver ottimizzato per GitHub Actions"""
    options = webdriver.ChromeOptions()
    
    # Opzioni per GitHub Actions
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins") 
    options.add_argument("--disable-images")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    try:
        return webdriver.Chrome(options=options)
    except Exception as e:
        logging.error(f"❌ Errore creazione driver Chrome: {e}")
        raise

def signal_handler(sig, frame):
    """Gestisce chiusura graceful"""
    logging.info("🛑 Ricevuto segnale di chiusura...")
    global driver
    if driver:
        try:
            driver.quit()
            logging.info("✅ Driver chiuso correttamente")
        except:
            pass
    sys.exit(0)

# ------------------------------
# 3) MAIN - VERSIONE GITHUB ACTIONS
# ------------------------------

def main():
    global id_sessione, driver
    
    logging.info("🚀 " + "="*60)
    logging.info("🚀 AVVIO VINTED TRACKER - GITHUB ACTIONS")
    logging.info("🚀 " + "="*60)
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    id_sessione = int(time.time())
    start_time = time.time()
    driver = None
    sql = None
    
    try:
        # Connessione DB
        logging.info("🔗 Connessione a Supabase...")
        sql = sql_connection()
        
        # Setup driver
        logging.info("🌐 Inizializzazione Chrome driver...")
        driver = create_github_driver()
        logging.info("✅ Chrome driver pronto")
        
        # Recupero ricerche
        logging.info("📋 Recupero ricerche dal database...")
        ricerche_result = sql.table("ricerche").select("*").execute()
        
        if not hasattr(ricerche_result, "data") or not ricerche_result.data:
            logging.error("❌ Nessuna ricerca trovata nel database")
            return False
            
        ricerche = pd.DataFrame(ricerche_result.data)
        ricerche_attive = ricerche[ricerche['abilitato'] == True]
        
        logging.info(f"📊 Trovate {len(ricerche)} ricerche totali, {len(ricerche_attive)} attive")
        
        if ricerche_attive.empty:
            logging.warning("⚠️ Nessuna ricerca attiva trovata")
            return True
        
        # Elaborazione homepage
        total_prodotti = 0
        total_offerte = 0
        
        for homepage in ricerche_attive.itertuples(index=False):
            try:
                logging.info(f"🔄 Elaboro: {homepage.categoria} - {homepage.ricerca}")
                
                if not ricerca_ready(sql, homepage):
                    logging.info(f"⏭️ Skip (cnt_ripetizioni: {homepage.cnt_ripetizioni})")
                    continue
                
                # Scraping annunci
                annunci_urls = fetch_annunci_urls(sql, homepage)
                if not annunci_urls:
                    logging.warning(f"⚠️ Nessun annuncio trovato per {homepage.categoria}")
                    continue
                
                prodotti = []
                for j, annuncio_url in enumerate(annunci_urls):
                    try:
                        logging.info(f"📄 Annuncio {j+1}/{len(annunci_urls)}")
                        prodotto = fetch_info(sql, homepage, annuncio_url, driver)
                        if prodotto:
                            prodotti.append(prodotto)
                            total_prodotti += 1
                            if prodotto.get("offerta", False):
                                total_offerte += 1
                        
                        # Delay casuale tra annunci
                        time.sleep(random.uniform(1, 3))
                        
                    except Exception as e:
                        logging.error(f"❌ Errore annuncio {j+1}: {e}")
                        continue
                
                # Salvataggio e invio mail
                if prodotti:
                    try:
                        # Salva su DB
                        prodotti_df = pd.DataFrame(prodotti).to_dict(orient="records")
                        sql.table("prodotti").insert(prodotti_df).execute()
                        logging.info(f"💾 Salvati {len(prodotti)} prodotti")
                        
                        # Invia mail se ci sono offerte
                        send_mail(sql, homepage, prodotti)
                        
                    except Exception as e:
                        logging.error(f"❌ Errore salvataggio/mail: {e}")
                        save_exception(sql, e, "salvataggio prodotti")
                
                # Delay tra homepage
                time.sleep(random.uniform(2, 5))
                
            except Exception as e:
                logging.error(f"❌ Errore homepage {homepage.categoria}: {e}")
                save_exception(sql, e, f"homepage {homepage.categoria}")
                continue
        
        # Pulizia duplicati
        try:
            logging.info("🧹 Pulizia duplicati...")
            sql.rpc("delete_old_duplicates").execute()
            logging.info("✅ Pulizia completata")
        except Exception as e:
            logging.error(f"❌ Errore pulizia duplicati: {e}")
            save_exception(sql, e, "delete_old_duplicates")
        
        # Statistiche finali
        durata = time.time() - start_time
        logging.info("🏁 " + "="*60)
        logging.info(f"🏁 SESSIONE {id_sessione} COMPLETATA")
        logging.info(f"⏱️  DURATA: {durata:.2f} secondi")
        logging.info(f"📊 PRODOTTI TOTALI: {total_prodotti}")
        logging.info(f"🎯 OFFERTE TROVATE: {total_offerte}")
        logging.info("🏁 " + "="*60)
        
        return True
        
    except Exception as e:
        logging.error(f"💥 ERRORE CRITICO: {e}")
        logging.error(f"📚 Stack trace: {traceback.format_exc()}")
        if sql:
            save_exception(sql, e, "main execution")
        return False
        
    finally:
        # Cleanup
        if driver:
            try:
                driver.quit()
                logging.info("🔧 Driver chiuso")
            except:
                logging.warning("⚠️ Errore chiusura driver")

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

