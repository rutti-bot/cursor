import requests
import time
import logging
import csv
import os
import json

# ==========================================
# 1. KONFIGURATION & API KEYS
# ==========================================
TEST_MODUS = True             # Auf False setzen für den echten Durchlauf!
MAX_TEST_DATENSAETZE = 5

WECLAPP_DOMAIN = os.environ.get("WECLAPP_DOMAIN", "https://performanat.weclapp.com")
WECLAPP_TOKEN = os.environ["WECLAPP_TOKEN"]

HUBSPOT_TOKEN = os.environ["HUBSPOT_TOKEN"]

# --- DYNAMISCHER PFAD ZUR CSV DATEI ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_MAPPING_FILE = os.path.join(SCRIPT_DIR, "mail_mapping.csv")

# --- LOGGING KONFIGURIEREN ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(os.path.join(SCRIPT_DIR, "attachment_import.txt"), mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

WECLAPP_HEADERS = {
    "AuthenticationToken": WECLAPP_TOKEN,
    "Content-Type": "application/json"
}

HS_HEADERS_JSON = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}",
    "Content-Type": "application/json"
}

HS_HEADERS_FILE = {
    "Authorization": f"Bearer {HUBSPOT_TOKEN}"
}

# ==========================================
# 2. HELPER FUNKTIONEN
# ==========================================

def get_weclapp_documents_for_email(weclapp_mail_id):
    """Sucht nach verknuepften Dokumenten/Anhaengen einer weclapp E-Mail
    ueber den /document Endpunkt mit entityId + entityName."""

    found_doc_ids = set()

    # Die archivedEmail-Entity selbst enthaelt laut OpenAPI-Spec KEINE
    # Attachment-Felder (documentIds, attachments, mailAttachments existieren
    # nicht). Die Anhaenge werden als eigenstaendige 'document'-Entities
    # gespeichert und ueber entityId + entityName verknuepft.
    # Daher: direkt den /document-Endpunkt abfragen.

    doc_query_url = f"{WECLAPP_DOMAIN}/webapp/api/v2/document"

    # entityId UND entityName sind beide noetig, damit weclapp die Zuordnung
    # zur archivedEmail herstellen kann.
    params = {
        "entityId": weclapp_mail_id,
        "entityName": "archivedEmail",
        "pageSize": 100
    }
    doc_res = requests.get(doc_query_url, headers=WECLAPP_HEADERS, params=params)

    if doc_res.status_code == 200:
        doc_data = doc_res.json().get("result", [])
        if isinstance(doc_data, list):
            for doc in doc_data:
                doc_id = doc.get("id")
                if doc_id:
                    found_doc_ids.add((str(doc_id), doc.get("name", f"attachment_{doc_id}")))
                    logging.info(f"  -> Dokument {doc_id} ('{doc.get('name')}') fuer Mail {weclapp_mail_id} gefunden.")
    else:
        logging.error(f"  -> Fehler bei Dokumenten-Abfrage fuer Mail {weclapp_mail_id}: {doc_res.status_code} - {doc_res.text[:300]}")

    # --- Anhaenge herunterladen ---
    attachments = []

    if not found_doc_ids:
        logging.info(f"  -> Keine Anhaenge fuer Mail {weclapp_mail_id} gefunden.")
        return attachments

    logging.info(f"  -> Lade {len(found_doc_ids)} Anhang/Anhaenge herunter...")

    for doc_id, doc_name in found_doc_ids:
        download_url = f"{WECLAPP_DOMAIN}/webapp/api/v2/document/id/{doc_id}/download"
        download_res = requests.get(download_url, headers=WECLAPP_HEADERS)

        if download_res.status_code == 200:
            attachments.append({
                "name": doc_name,
                "content": download_res.content
            })
            logging.info(f"  -> Anhang heruntergeladen: {doc_name}")
        else:
            logging.warning(f"  -> Konnte Datei-Inhalt fuer Dokument {doc_id} nicht laden. (Status: {download_res.status_code})")

    return attachments

def upload_file_to_hubspot(filename, file_content):
    """Laedt eine Datei in das HubSpot File-System hoch und gibt die File-ID zurueck."""
    url = "https://api.hubapi.com/files/v3/files"

    files = {
        'file': (filename, file_content, 'application/octet-stream'),
        'options': (None, json.dumps({
            "access": "PRIVATE",
            "overwrite": False
        }), 'application/json'),
        'folderPath': (None, '/weclapp_mail_attachments', 'text/plain')
    }

    res = requests.post(url, headers=HS_HEADERS_FILE, files=files)

    if res.status_code in [200, 201]:
        return str(res.json().get("id"))
    else:
        logging.error(f"Fehler beim Upload zu HubSpot ({filename}): {res.text}")
        return None

def link_attachments_to_hs_email(hs_email_id, hs_file_ids):
    """Fuegt die hochgeladenen Dateien an die bestehende E-Mail in HubSpot an."""
    if not hs_file_ids:
        return True

    url = f"https://api.hubapi.com/crm/v3/objects/emails/{hs_email_id}"

    payload = {
        "properties": {
            "hs_attachment_ids": ";".join(hs_file_ids)
        }
    }

    res = requests.patch(url, headers=HS_HEADERS_JSON, json=payload)

    if res.status_code == 200:
        logging.info(f"{len(hs_file_ids)} Anhang/Anhaenge erfolgreich an HubSpot-E-Mail {hs_email_id} angehaengt.")
        return True
    else:
        logging.error(f"Fehler beim Verknuepfen der Anhaenge mit HubSpot-E-Mail {hs_email_id}: {res.text}")
        return False

# ==========================================
# 3. HAUPTSCHLEIFE
# ==========================================

def main():
    logging.info("Starte weclapp -> HubSpot Anhang-Migration...")

    if not os.path.exists(CSV_MAPPING_FILE):
        logging.error(f"Mapping-Datei '{CSV_MAPPING_FILE}' nicht gefunden. Bitte zuerst das E-Mail-Skript ausfuehren.")
        return

    processed_count = 0

    with open(CSV_MAPPING_FILE, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            if TEST_MODUS and processed_count >= MAX_TEST_DATENSAETZE:
                logging.info(f"\nTest-Limit von {MAX_TEST_DATENSAETZE} E-Mails erreicht. Beende Skript.")
                break

            weclapp_mail_id = row.get("weclapp_mail_id")
            hs_email_id = row.get("hubspot_email_id")

            if not weclapp_mail_id or not hs_email_id:
                continue

            logging.info(f"\nPruefe weclapp E-Mail {weclapp_mail_id} auf Anhaenge...")

            attachments = get_weclapp_documents_for_email(weclapp_mail_id)

            if not attachments:
                continue

            hs_file_ids = []

            for att in attachments:
                hs_file_id = upload_file_to_hubspot(att["name"], att["content"])
                if hs_file_id:
                    hs_file_ids.append(hs_file_id)

            if hs_file_ids:
                link_attachments_to_hs_email(hs_email_id, hs_file_ids)
                processed_count += 1

            time.sleep(0.2)

    logging.info("\nAnhang-Import abgeschlossen.")

if __name__ == "__main__":
    main()
