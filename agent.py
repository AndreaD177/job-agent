"""
╔══════════════════════════════════════════════════════════════╗
║         AGENTE DI MONITORAGGIO OFFERTE DI LAVORO             ║
║         Andrea Di Stefano — Perito Elettrotecnico            ║
╚══════════════════════════════════════════════════════════════╝

Cosa fa questo agente ogni mattina:
  1. Visita le pagine /careers delle aziende nella lista
  2. Estrae le offerte di lavoro pubblicate
  3. Chiede a Gemini di valutare la rilevanza (score 0-10)
  4. Per le offerte con score >= 7, cerca il contatto HR con Hunter.io
  5. Gemini scrive un'email di candidatura personalizzata
  6. Invia le email tramite Gmail
  7. Invia un report riassuntivo a te
"""

import os
import json
import smtplib
import requests
import time
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# ── Carica variabili d'ambiente (.env in locale, Secrets su GitHub) ──────────
load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
HUNTER_API_KEY      = os.getenv("HUNTER_API_KEY")
GMAIL_USER          = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL     = os.getenv("RECIPIENT_EMAIL")

# ── Configura Gemini ──────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")   # gratuito, veloce

# ═════════════════════════════════════════════════════════════════════════════
# SEZIONE 1 — PROFILO PROFESSIONALE
# Modifica questa sezione con le tue competenze reali
# ═════════════════════════════════════════════════════════════════════════════

PROFILO = """
Nome: Andrea Di Stefano
Titolo: Perito Industriale Elettrotecnico
Albo: Iscritto all'Albo dei Periti Industriali di Monza e Brianza
Abilitazione: Firma progetti elettrici, dichiarazioni di rispondenza DM 37/2008

COMPETENZE TECNICHE:
- Progettazione elettrica BT/MT (schemi unifilari, multifilo, layout quadri)
- Programmazione PLC Siemens TIA Portal V18 (S7-300, S7-400, S7-1200, S7-1500)
- Automazione package e bordo macchina in zone classificate
- Zone classificate ATEX: Zone 0/1/2 Gas, Zone 20/21/22 Polveri
- Classificazione zone e selezione apparecchiature Ex (IEC 60079, ATEX 2014/34/EU)
- Dichiarazioni di rispondenza quadri elettrici e MCC
- Software ElectroCad per schemi elettrici
- Documentazione tecnica: as-built, dossier ATEX, relazioni di calcolo
- Ispezioni in cantiere Italia ed Estero

SETTORE PRINCIPALE: Oil & Gas, Petrolchimica, Impianti compressori

ESPERIENZE CAMPO:
- Startup e commissioning package bordo macchina in zone ATEX
- Trasferte: Italia, Messico (settore oil & gas)
- Pre-commissioning, loop check, energizzazione quadri
- Troubleshooting su impianti in esercizio

NORME: IEC 60079, ATEX 2014/34/EU, CEI 64-8, IEC 61508/SIL, CEI EN 60204-1
"""

# ═════════════════════════════════════════════════════════════════════════════
# SEZIONE 2 — LISTA AZIENDE DA MONITORARE
# Aggiungi o rimuovi aziende modificando questo dizionario
# ═════════════════════════════════════════════════════════════════════════════

AZIENDE = [
    {
        "nome": "Saipem",
        "dominio": "saipem.com",
        "careers_url": "https://www.saipem.com/en/careers/job-opportunities",
        "paese": "Italia"
    },
    {
        "nome": "Eni",
        "dominio": "eni.com",
        "careers_url": "https://www.eni.com/en-IT/careers/job-opportunities.html",
        "paese": "Italia"
    },
    {
        "nome": "Maire Tecnimont",
        "dominio": "mairetecnimont.com",
        "careers_url": "https://www.mairetecnimont.com/en/careers",
        "paese": "Italia"
    },
    {
        "nome": "Baker Hughes",
        "dominio": "bakerhughes.com",
        "careers_url": "https://careers.bakerhughes.com/global/en/search-results",
        "paese": "USA/Italia"
    },
    {
        "nome": "Tecnicas Reunidas",
        "dominio": "tecnicasreunidas.es",
        "careers_url": "https://www.tecnicasreunidas.es/en/careers/job-offers",
        "paese": "Spagna"
    },
    {
        "nome": "Burckhardt Compression",
        "dominio": "burckhardtcompression.com",
        "careers_url": "https://www.burckhardtcompression.com/en/careers/job-openings",
        "paese": "Svizzera"
    },
    {
        "nome": "Nuovo Pignone (Baker Hughes)",
        "dominio": "bakerhughes.com",
        "careers_url": "https://careers.bakerhughes.com/global/en/search-results?keywords=electrical",
        "paese": "Italia"
    },
    {
        "nome": "Snam",
        "dominio": "snam.it",
        "careers_url": "https://www.snam.it/it/lavora-con-noi/opportunita-di-lavoro/",
        "paese": "Italia"
    },
]

# ═════════════════════════════════════════════════════════════════════════════
# MODULO 1 — WEB SCRAPER
# ═════════════════════════════════════════════════════════════════════════════

def scrape_offerte(azienda: dict) -> list[dict]:
    """
    Visita la pagina careers dell'azienda ed estrae titolo e testo delle offerte.
    Restituisce una lista di dizionari {titolo, testo, url, azienda}.
    """
    offerte = []
    print(f"  Scraping: {azienda['nome']}...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"
            )
            # Timeout 20 secondi per caricare la pagina
            page.goto(azienda["careers_url"], timeout=20000, wait_until="domcontentloaded")
            time.sleep(2)  # attendi rendering JavaScript

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Cerca link che contengono parole tipiche delle offerte di lavoro
        parole_chiave_url = ["job", "position", "vacancy", "career", "opportunit",
                             "role", "opening", "lavoro", "offerta", "posizione"]

        link_offerte = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            testo_link = a.get_text(strip=True).lower()
            if any(p in href for p in parole_chiave_url) or any(p in testo_link for p in parole_chiave_url):
                titolo = a.get_text(strip=True)
                if len(titolo) > 10:  # filtra link troppo corti
                    url_completo = a["href"]
                    if not url_completo.startswith("http"):
                        base = "/".join(azienda["careers_url"].split("/")[:3])
                        url_completo = base + url_completo
                    link_offerte.append({"titolo": titolo, "url": url_completo})

        # Prendi al massimo 10 offerte per azienda
        for link in link_offerte[:10]:
            offerte.append({
                "titolo":  link["titolo"],
                "testo":   link["titolo"],  # testo base (il titolo)
                "url":     link["url"],
                "azienda": azienda["nome"],
                "dominio": azienda["dominio"],
            })

        print(f"    → {len(offerte)} offerte trovate")

    except Exception as e:
        print(f"    ✗ Errore su {azienda['nome']}: {e}")

    return offerte


# ═════════════════════════════════════════════════════════════════════════════
# MODULO 2 — FILTRO AI CON GEMINI
# ═════════════════════════════════════════════════════════════════════════════

def valuta_offerta(offerta: dict) -> dict:
    """
    Chiede a Gemini di valutare la rilevanza dell'offerta rispetto al profilo.
    Restituisce l'offerta arricchita con score e motivazione.
    """
    prompt = f"""Sei un recruiter specializzato nel settore Oil & Gas e automazione industriale.

PROFILO DEL CANDIDATO:
{PROFILO}

OFFERTA DI LAVORO:
Azienda: {offerta['azienda']}
Titolo: {offerta['titolo']}
Dettagli: {offerta['testo'][:800]}

ISTRUZIONI:
Valuta da 0 a 10 quanto questa offerta è adatta al candidato.
Considera: zona classificata ATEX, PLC Siemens, Oil & Gas, progettazione elettrica,
commissioning, disponibilità trasferte.

Rispondi SOLO con questo formato JSON, nessun altro testo:
{{
  "score": 8,
  "motivo": "Ruolo perfettamente in linea con esperienza ATEX e PLC Siemens",
  "punti_forza": ["ATEX", "TIA Portal", "commissioning"],
  "oggetto_email": "Candidatura Electrical Engineer ATEX — Andrea Di Stefano"
}}"""

    try:
        response = model.generate_content(prompt)
        testo = response.text.strip()

        # Rimuove eventuali blocchi ```json ... ```
        if "```" in testo:
            testo = testo.split("```")[1]
            if testo.startswith("json"):
                testo = testo[4:]

        risultato = json.loads(testo)
        offerta.update(risultato)
        print(f"    Score {risultato['score']}/10 — {offerta['titolo'][:50]}")

    except Exception as e:
        print(f"    ✗ Errore valutazione Gemini: {e}")
        offerta["score"] = 0
        offerta["motivo"] = "Errore nella valutazione"
        offerta["punti_forza"] = []
        offerta["oggetto_email"] = ""

    return offerta


# ═════════════════════════════════════════════════════════════════════════════
# MODULO 3 — RICERCA CONTATTO CON HUNTER.IO
# ═════════════════════════════════════════════════════════════════════════════

def cerca_contatto(dominio: str) -> dict:
    """
    Usa Hunter.io per trovare l'email HR o hiring manager dell'azienda.
    Piano gratuito: 25 ricerche/mese.
    """
    if not HUNTER_API_KEY:
        return {"email": None, "nome": None}

    try:
        url = f"https://api.hunter.io/v2/domain-search"
        params = {
            "domain":  dominio,
            "api_key": HUNTER_API_KEY,
            "limit":   5,
            "type":    "personal",
        }
        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        emails = data.get("data", {}).get("emails", [])

        # Cerca prima HR, recruiter, talent acquisition
        parole_hr = ["hr", "recruit", "talent", "people", "human", "career", "hiring"]
        for email_data in emails:
            posizione = (email_data.get("position") or "").lower()
            if any(p in posizione for p in parole_hr):
                return {
                    "email": email_data["value"],
                    "nome":  f"{email_data.get('first_name', '')} {email_data.get('last_name', '')}".strip(),
                }

        # Se non trova HR, usa il primo contatto disponibile
        if emails:
            e = emails[0]
            return {
                "email": e["value"],
                "nome":  f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
            }

    except Exception as e:
        print(f"    ✗ Errore Hunter.io: {e}")

    return {"email": None, "nome": None}


# ═════════════════════════════════════════════════════════════════════════════
# MODULO 4 — REDAZIONE EMAIL CON GEMINI
# ═════════════════════════════════════════════════════════════════════════════

def scrivi_email(offerta: dict, contatto: dict) -> str:
    """
    Chiede a Gemini di scrivere un'email di candidatura personalizzata.
    """
    nome_destinatario = contatto.get("nome") or "Gentile Responsabile HR"
    punti = ", ".join(offerta.get("punti_forza", []))

    prompt = f"""Sei Andrea Di Stefano, perito elettrotecnico specializzato in Oil & Gas e zone ATEX.
Scrivi un'email di candidatura professionale in italiano per questa offerta.

OFFERTA:
Azienda: {offerta['azienda']}
Posizione: {offerta['titolo']}
Motivo rilevanza: {offerta.get('motivo', '')}
Punti di forza da evidenziare: {punti}

DESTINATARIO: {nome_destinatario}

ISTRUZIONI PER L'EMAIL:
- Tono professionale ma diretto
- Lunghezza: 150-200 parole (non di più)
- Menziona 2-3 competenze specifiche collegate all'offerta (ATEX, TIA Portal, commissioning)
- Cita l'esperienza di trasferte (Italia, Messico) se rilevante
- Includi disponibilità immediata
- Firma: Andrea Di Stefano | info@andreadistefano.eu | +39 392 384 9709
- Scrivi SOLO il corpo dell'email, senza oggetto, senza "Corpo:" all'inizio"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"    ✗ Errore scrittura email Gemini: {e}")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# MODULO 5 — INVIO EMAIL TRAMITE GMAIL
# ═════════════════════════════════════════════════════════════════════════════

def invia_email(destinatario: str, oggetto: str, corpo: str) -> bool:
    """
    Invia un'email tramite Gmail SMTP.
    Richiede una "App Password" Gmail (non la password normale).
    Come ottenerla: myaccount.google.com → Sicurezza → Password app
    """
    if not all([GMAIL_USER, GMAIL_APP_PASSWORD, destinatario]):
        print("    ✗ Credenziali Gmail mancanti o email destinatario non trovata")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = oggetto
        msg["From"]    = GMAIL_USER
        msg["To"]      = destinatario

        msg.attach(MIMEText(corpo, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, destinatario, msg.as_string())

        print(f"    ✓ Email inviata a {destinatario}")
        return True

    except Exception as e:
        print(f"    ✗ Errore invio email: {e}")
        return False


def invia_report(offerte_rilevanti: list, offerte_totali: int):
    """
    Invia un report riassuntivo giornaliero a te stesso.
    """
    if not RECIPIENT_EMAIL:
        return

    oggi = date.today().strftime("%d/%m/%Y")
    oggetto = f"[Job Agent] Report {oggi} — {len(offerte_rilevanti)} offerte rilevanti"

    righe = [f"Report giornaliero del {oggi}", "=" * 40, ""]
    righe.append(f"Offerte totali analizzate: {offerte_totali}")
    righe.append(f"Offerte rilevanti (score ≥ 7): {len(offerte_rilevanti)}")
    righe.append("")

    if offerte_rilevanti:
        righe.append("OFFERTE RILEVANTI:")
        righe.append("-" * 40)
        for o in offerte_rilevanti:
            righe.append(f"\n• {o['azienda']} — {o['titolo']}")
            righe.append(f"  Score: {o['score']}/10")
            righe.append(f"  {o.get('motivo', '')}")
            righe.append(f"  URL: {o['url']}")
            email_dest = o.get("email_inviata")
            if email_dest:
                righe.append(f"  Email inviata a: {email_dest}")
            else:
                righe.append("  Email: contatto non trovato")
    else:
        righe.append("Nessuna offerta rilevante trovata oggi.")

    righe.append("\n" + "=" * 40)
    righe.append("Andrea Di Stefano — Job Agent automatico")

    invia_email(RECIPIENT_EMAIL, oggetto, "\n".join(righe))


# ═════════════════════════════════════════════════════════════════════════════
# MAIN — ORCHESTRAZIONE DELL'AGENTE
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print(f"  JOB AGENT AVVIATO — {date.today().strftime('%d/%m/%Y')}")
    print("="*60 + "\n")

    tutte_le_offerte = []
    offerte_rilevanti = []
    report = []

    # ── FASE 1: Scraping ──────────────────────────────────────
    print("FASE 1 — Scraping siti aziendali...")
    for azienda in AZIENDE:
        offerte = scrape_offerte(azienda)
        tutte_le_offerte.extend(offerte)
        time.sleep(1)  # pausa tra un sito e l'altro

    print(f"\nTotale offerte raccolte: {len(tutte_le_offerte)}\n")

    # ── FASE 2: Filtro AI ─────────────────────────────────────
    print("FASE 2 — Valutazione AI con Gemini...")
    for offerta in tutte_le_offerte:
        offerta = valuta_offerta(offerta)
        time.sleep(0.5)  # evita rate limit Gemini

        if offerta.get("score", 0) >= 7:
            offerte_rilevanti.append(offerta)

    print(f"\nOfferte rilevanti (score ≥ 7): {len(offerte_rilevanti)}\n")

    # ── FASE 3: Ricerca contatti + Invio email ────────────────
    print("FASE 3 — Ricerca contatti e invio email...")
    for offerta in offerte_rilevanti:
        print(f"\n  → {offerta['azienda']}: {offerta['titolo'][:50]}")

        # Cerca contatto HR
        contatto = cerca_contatto(offerta["dominio"])
        print(f"    Contatto: {contatto.get('email') or 'non trovato'}")

        # Scrivi email personalizzata
        corpo_email = scrivi_email(offerta, contatto)

        # Invia email se il contatto è stato trovato
        if contatto.get("email") and corpo_email:
            oggetto = offerta.get("oggetto_email",
                       f"Candidatura {offerta['titolo']} — Andrea Di Stefano")
            inviata = invia_email(contatto["email"], oggetto, corpo_email)
            offerta["email_inviata"] = contatto["email"] if inviata else None
        else:
            offerta["email_inviata"] = None

        # Salva nel report
        report.append({
            "data":          date.today().isoformat(),
            "azienda":       offerta["azienda"],
            "titolo":        offerta["titolo"],
            "url":           offerta["url"],
            "score":         offerta["score"],
            "motivo":        offerta.get("motivo", ""),
            "contatto":      contatto.get("email"),
            "email_inviata": offerta.get("email_inviata"),
        })

        time.sleep(1)

    # ── FASE 4: Salva report JSON (scaricabile da GitHub) ─────
    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport salvato: report.json")

    # ── FASE 5: Invia report via email a te stesso ────────────
    print("\nFASE 4 — Invio report riepilogativo...")
    invia_report(offerte_rilevanti, len(tutte_le_offerte))

    print("\n" + "="*60)
    print(f"  AGENTE COMPLETATO")
    print(f"  Analizzate: {len(tutte_le_offerte)} offerte")
    print(f"  Rilevanti:  {len(offerte_rilevanti)} offerte")
    print(f"  Email inviate: {sum(1 for o in offerte_rilevanti if o.get('email_inviata'))}")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
