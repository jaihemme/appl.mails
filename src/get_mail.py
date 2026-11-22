from pathlib import Path
from email.iterators import _structure
from email import message_from_bytes
from email.policy import default
from email.utils import parseaddr
from bs4 import BeautifulSoup, Comment
import re


def html2text(contenu_html):
    soup = BeautifulSoup(contenu_html, "html.parser")

    # --- Supprime les balises Microsoft (o:, w:, v:, m:, etc.) restantes ---
    for tag in soup.find_all(re.compile(r'^[a-z]+:[a-z0-9]+$', re.IGNORECASE)):
        tag.decompose()

    # --- Supprime les commentaires (dont blocs conditionnels Word) ---
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # --- Supprime les scripts / styles ---
    for tag in soup(["script", "style", "meta", "link"]):
        tag.decompose()

    # --- Supprime les blocs cités (réponses précédentes dans le fil email) ---
    for bq in soup.find_all("blockquote", attrs={"type": "cite"}):
        bq.decompose()

    # --- Remplace les <br> par des retours à la ligne ---
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # --- Extraction du texte ---
    text = soup.get_text(separator="\n")

    # --- Nettoyage des lignes vides multiples et espaces superflus ---
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]  # supprime lignes vides
    text = "\n".join(lines)

    return text


dossier = Path('mbox_PPE')
fichier = "2024-08-23_12-17-48_PPE_Nierlet_8_à_Neyruz_-_Estimation_ECAB_-_mercred_Marie-Christine_Marf.eml"


file_path = dossier / fichier
with open(file_path, 'rb') as f:
#    msg = BytesParser(policy=policy.default).parse(f)
    msg = message_from_bytes(f.read(), policy=default)
print(f"multipart message: {msg.is_multipart()}")
print(_structure(msg, ))

date_header = msg.get('Date', '')
from_header = msg.get('From', '')
from1 = parseaddr(from_header)
to_header = msg.get('To', '')
subject_header = msg.get('Subject', '')
body = msg.get_body(preferencelist=("html", "plain"))
content_type = msg.get_content_type()
payload = msg.get_payload(decode=True)

# Extraire le corps
body = ''
attachments = []

if msg.is_multipart():
    for part in msg.walk():
        content_type = part.get_content_type()
        print(f"content_type: {content_type}")
        if content_type == "text/html":
            content = part.get_content()
            texte = html2text(content)
            print(texte)

# print(msg.__str__())
print("fin")