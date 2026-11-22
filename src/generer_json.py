#!/usr/bin/env python3
"""
Script de génération de JSON structuré pour analyse IA à partir de fichiers .eml.

Fonctionnalités :
- Parsing RFC 822 avec gestion des encodages (UTF-8, ISO-8859-1, Windows-1252)
- Nettoyage du contenu (suppression signatures, historiques cités)
- Regroupement par conversation basé sur le nom de fichier
- Export JSON structuré pour consommation IA
"""

import argparse
import html.parser
import json
import re
import sys
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from bs4 import BeautifulSoup, Comment


# =============================================================================
# CONFIGURATION DES REGEX (Multi-langues)
# =============================================================================

# Motifs de citation pour détecter le début de l'historique
CITATION_PATTERNS = [
    r'^Le\s.*\s+écrit\s*:',           # Français: "Le 28 avr. 2024 à 14:30, Jean Dupont a écrit :"
    r'^On\s.*\swrote:',              # Anglais: "On Tue, Apr 28, 2024 at 2:30 PM Jean Dupont wrote:"
    r'^Von:',                        # Allemand: "Von: Jean Dupont"
    r'^De:',                         # Français/Espagnol: "De: Jean Dupont"
    r'^Da:',                         # Italien: "Da: Jean Dupont"
    r'^Il giorno.*scrive:',           # Italien: "Il giorno 28 apr 2024, alle ore 14:30, Jean Dupont scrive:"
    r'^Am\s.*\sum\s.*\schrieb:',      # Allemand: "Am 28.04.2024 um 14:30 schrieb Jean Dupont:"
    r'^>+',                          # Citations standard > ou >>> 
    r'^\s*-{5,}.*(?:Original Message|Message original|Message d\'origine|Originalnachricht)',
    r'^\s*---.*Forwarded message.*---',
    r'^\s*----------\s*Forwarded message',
]

# Motifs de signature pour détecter la fin du message
SIGNATURE_PATTERNS = [
    r'^-- ',                         # Signature standard Unix
    r'^__',                          # Alternative
    r'^Cordialement',                # Français
    r'^Bien à vous',                 # Français
    r'^Bien cordialement',          # Français
    r'^Salutations',                 # Français
    r'^Best regards',                # Anglais
    r'^Kind regards',                # Anglais
    r'^Regards',                     # Anglais
    r'^Sincerely',                   # Anglais
    r'^Mit freundlichen Grüßen',     # Allemand
    r'^MfG',                         # Allemand (abréviation)
    r'^Sent from my iPhone',         # Mobile signature
    r'^Envoyé de mon iPhone',        # Mobile signature FR
    r'^Sent from my Android',        # Mobile signature
    r'^Envoyé depuis mon mobile',     # Mobile signature FR
]

# =============================================================================
# FONCTIONS DE PARSING
# =============================================================================

class HTMLToText(html.parser.HTMLParser):
    """Convertisseur HTML -> texte brut simple."""
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)

    def get_text(self):
        return ''.join(self.text).strip()

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

def parser_eml(file_path):
    """
    Parse un fichier .eml et extrait ses métadonnées et contenu.

    Args:
        file_path (Path): Chemin vers le fichier .eml

    Returns:
        dict: {
            'date': str (ISO format),
            'from': str,
            'to': str,
            'subject': str,
            'message_id': str,
            'in_reply_to': str,
            'body': str,
            'attachments': list,
            'error': str or None
        }
    """
    try:
        with open(file_path, 'rb') as f:
            msg = BytesParser(policy=policy.default).parse(f)

        # Extraire les en-têtes
        date_header = msg.get('Date', '')
        from_header = msg.get('From', '')
        to_header = msg.get('To', '')
        subject_header = msg.get('Subject', '')
        messageid_header = msg.get('Message-ID', '')
        inreplyto_header = msg.get('In-Reply-To', '')

        # Extraire le corps
        body = ''
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Pièce jointe
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename:
                        attachments.append(filename)
                    continue

                # Contenu texte
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        body = payload.decode(charset, errors='replace')
                    except (UnicodeDecodeError, LookupError):
                        # Essayer d'autres encodages courants
                        for encoding in ['utf-8', 'iso-8859-1', 'windows-1252']:
                            try:
                                body = payload.decode(encoding, errors='replace')
                                break
                            except:
                                continue
                elif content_type == "text/html" and not body:
                    content = part.get_content()
                    body = html2text(content)
        else:
            # Message simple (non multipart)
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            content_type = msg.get_content_type()

            if content_type == "text/html":
                try:
                    html_content = payload.decode(charset, errors='replace')
                    converter = HTMLToText()
                    converter.feed(html_content)
                    body = converter.get_text()
                except:
                    body = ''
            else:
                try:
                    body = payload.decode(charset, errors='replace')
                except (UnicodeDecodeError, LookupError):
                    for encoding in ['utf-8', 'iso-8859-1', 'windows-1252']:
                        try:
                            body = payload.decode(encoding, errors='replace')
                            break
                        except:
                            continue

        # Parser la date
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_header)
            date_iso = dt.strftime('%Y-%m-%dT%H:%M:%S') if dt else None
        except:
            date_iso = None

        return {
            'date': date_iso,
            'from': from_header,
            'to': to_header,
            'subject': subject_header,
            'message_id': messageid_header,
            'in_reply_to': inreplyto_header,
            'body': body,
            'attachments': attachments,
            'error': None
        }

    except Exception as e:
        return {
            'date': None,
            'from': None,
            'to': None,
            'subject': None,
            'message_id': None,
            'in_reply_to': None,
            'body': None,
            'attachments': [],
            'error': str(e)
        }


# =============================================================================
# FONCTIONS DE NETTOYAGE
# =============================================================================


def nettoyer_contenu(corps_brut):
    """
    Nettoie le contenu du message en supprimant :
    1. L'historique (citations et messages originaux)
    2. La signature
    3. Les lignes vides multiples en début/fin

    Args:
        corps_brut (str): Contenu brut du message

    Returns:
        tuple: (contenu_nettoye: str, a_ete_coupe: bool)
    """
    if not corps_brut or not corps_brut.strip():
        return "", False

    lignes = corps_brut.splitlines()

    # Compiler les regex
    citation_regex = re.compile('|'.join(CITATION_PATTERNS), re.IGNORECASE | re.MULTILINE)
    signature_regex = re.compile('|'.join(SIGNATURE_PATTERNS), re.IGNORECASE | re.MULTILINE)

    # Trouver la première ligne de citation (début de l'historique)
    coupe_citation_idx = None
    for i, ligne in enumerate(lignes):
        if citation_regex.match(ligne):
            coupe_citation_idx = i
            break

    # Trouver la première ligne de signature (fin du message)
    coupe_signature_idx = None
    for i in range(len(lignes)-1, -1, -1):
        if signature_regex.match(lignes[i]):
            coupe_signature_idx = i
            break

    # Déterminer les limites
    start = 0
    end = len(lignes)

    # Couper à la première citation trouvée
    if coupe_citation_idx is not None:
        end = coupe_citation_idx

    # Couper à la signature SI le texte restant a assez de contenu
    if coupe_signature_idx is not None and end > coupe_signature_idx:
        # Vérifier qu'il reste au moins 3 lignes après la coupe de signature
        if (end - start) > 3 or (coupe_signature_idx - start) >= 3:
            end = min(end, coupe_signature_idx)

    # Extraire les lignes à conserver
    lignes_nettoyees = lignes[start:end]

    # Nettoyage final : supprimer les lignes vides multiples
    texte = '\n'.join(lignes_nettoyees)
    texte = re.sub(r'\n{3,}', '\n\n', texte)  # Remplacer 3+ sauts par 2
    texte = texte.strip()

    a_ete_coupe = (coupe_citation_idx is not None) or (coupe_signature_idx is not None)

    return texte, a_ete_coupe


# =============================================================================
# FONCTIONS D'EXTRACTION DEPUIS LE NOM DE FICHIER
# =============================================================================


def extraire_infos_depuis_nom_fichier(nom_fichier):
    """
    Extrait sujet_nettoye et expediteur_nom depuis le nom de fichier.

    Format attendu: AAAA-MM-JJ_HH-MM-SS_Sujet_Nettoye_Expediteur.eml

    Args:
        nom_fichier (str): Nom du fichier .eml

    Returns:
        tuple: (date_heure_str, sujet_nettoye, expediteur_nom)
    """
    # Enlever l'extension .eml
    nom_sans_ext = nom_fichier.replace('.eml', '')

    # Split par underscore
    parties = nom_sans_ext.split('_')

    if len(parties) < 4:
        # Format invalide, retourner des valeurs par défaut
        return None, nom_sans_ext, "inconnu"

    # Les 2 premières parties = date et heure
    date_part = parties[0]
    heure_part = parties[1]

    # La dernière partie = expéditeur
    expediteur_nom = parties[-1]

    # Tout ce qui est entre = sujet nettoyé
    sujet_nettoye = '_'.join(parties[2:-1])

    # Reconstruire date_heure
    date_heure_str = f"{date_part}_{heure_part}"

    return date_heure_str, sujet_nettoye, expediteur_nom


def convertir_date_heure_en_iso(date_heure_str):
    """
    Convertit AAAA-MM-JJ_HH-MM-SS en ISO format YYYY-MM-DDTHH:MM:SS

    Args:
        date_heure_str (str): Date et heure au format AAAA-MM-JJ_HH-MM-SS

    Returns:
        str: Date au format ISO ou None
    """
    if not date_heure_str:
        return None

    try:
        parts = date_heure_str.split('_')
        if len(parts) != 2:
            return None

        date_part = parts[0]
        heure_part = parts[1].replace('-', ':')

        dt_str = f"{date_part} {heure_part}"
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        return dt.strftime('%Y-%m-%dT%H:%M:%S')
    except:
        return None


# =============================================================================
# FONCTIONS PRINCIPALES
# =============================================================================


def traiter_dossier(dossier_path):
    """
    Traite tous les fichiers .eml d'un dossier.

    Args:
        dossier_path (Path): Chemin vers le dossier

    Returns:
        dict: Structure complète prête pour le JSON
    """
    dossier = Path(dossier_path)
    eml_files = sorted(dossier.glob('*.eml'))

    if not eml_files:
        print(f"Aucun fichier .eml trouvé dans {dossier}")
        return None

    print(f"Traitement de {len(eml_files)} fichier(s) .eml...")

    # Dictionnaire pour regrouper par sujet
    conversations = {}
    total_fichiers = 0
    erreurs = 0

    for eml_file in eml_files:
        print(f"  Traitement: {eml_file.name}")
        total_fichiers += 1

        try:
            # Extraire infos du nom de fichier
            date_heure_str, sujet_nettoye, expediteur_nom = extraire_infos_depuis_nom_fichier(eml_file.name)

            if date_heure_str is None:
                print(f"    [AVERTISSEMENT] Format de nom invalide: {eml_file.name}")
                erreurs += 1
                continue

            timestamp = convertir_date_heure_en_iso(date_heure_str)

            # Parser le fichier .eml
            metadata = parser_eml(eml_file)

            if metadata['error']:
                print(f"    [ERREUR] Parsing échoué: {metadata['error']}")
                erreurs += 1
                continue

            # Utiliser la date du nom de fichier si celle de l'en-tête est manquante
            if not metadata['date']:
                metadata['date'] = timestamp

            # Nettoyer le contenu
            contenu_nettoye, a_ete_coupe = nettoyer_contenu(metadata['body'])

            # Créer l'objet message
            message = {
                "fichier_source": eml_file.name,
                "timestamp": metadata['date'] or timestamp or "1970-01-01T00:00:00",
                "message_id": metadata['message_id'],
                "in_reply_to": metadata['in_reply_to'],
                "expediteur_nom": parseaddr(metadata['from'] or "inconnu")[0],
                "expediteur_email": parseaddr(metadata['from'] or "inconnu")[1],
                "destinataires": metadata['to'] or "inconnu",
                "sujet": metadata['subject'] or "",
                "contenu_nettoye": contenu_nettoye,
                "pieces_jointes": metadata['attachments'],
                "a_ete_coupe": a_ete_coupe
            }

            # Ajouter à la conversation correspondante
            if sujet_nettoye not in conversations:
                conversations[sujet_nettoye] = {
                    "messages": [],
                    "sujet_normalise": sujet_nettoye.replace('_', ' '),
                    "date_debut": None,
                    "date_fin": None
                }

            conversations[sujet_nettoye]["messages"].append(message)

        except Exception as e:
            print(f"    [ERREUR] Erreur inattendue: {str(e)}")
            erreurs += 1
            continue

    # Structurer les conversations
    conversations_list = []

    for sujet, conv_data in conversations.items():
        # Trier les messages par timestamp
        conv_data["messages"].sort(key=lambda x: x["timestamp"])

        # Déterminer date_debut et date_fin
        timestamps = [m["timestamp"] for m in conv_data["messages"]]
        conv_data["date_debut"] = min(timestamps) if timestamps else None
        conv_data["date_fin"] = max(timestamps) if timestamps else None
        conv_data["nombre_messages"] = len(conv_data["messages"])

        conversations_list.append(conv_data)

    # Trier les conversations par date_debut
    conversations_list.sort(key=lambda x: x["date_debut"] or "9999-99-99T99:99:99")

    # Créer la structure finale
    result = {
        "meta": {
            "total_fichiers": total_fichiers,
            "total_conversations": len(conversations_list),
            "date_generation": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            "fichiers_erreur": erreurs
        },
        "conversations": conversations_list
    }

    return result


def exporter_json(data, output_path):
    """
    Exporte les données en JSON.

    Args:
        data (dict): Structure à exporter
        output_path (Path): Chemin du fichier de sortie
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)

    print(f"JSON généré: {output_path}")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description='Génère un JSON structuré pour analyse IA à partir de fichiers .eml.'
    )
    parser.add_argument(
        'dossier',
        nargs='?',
        default=None,
        help='Chemin du dossier contenant les fichiers .eml (optionnel)'
    )

    args = parser.parse_args()

    # Sélection du dossier
    if args.dossier is None:
        dossier = input("Chemin du dossier contenant les fichiers .eml: ").strip()
    else:
        dossier = args.dossier

    dossier_path = Path(dossier)

    # Validation
    if not dossier_path.is_dir():
        print(f"Erreur: '{dossier_path}' n'est pas un dossier valide.", file=sys.stderr)
        sys.exit(1)

    # Traitement
    result = traiter_dossier(dossier_path)

    if result is None:
        sys.exit(0)

    # Export JSON
    output_path = dossier_path / 'projet_conversations.json'
    exporter_json(result, output_path)

    # Résumé
    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    print(f"Dossier analysé: {dossier_path.absolute()}")
    print(f"Fichiers traités: {result['meta']['total_fichiers']}")
    print(f"Conversations identifiées: {result['meta']['total_conversations']}")
    print(f"Erreurs: {result['meta']['fichiers_erreur']}")

    if result['meta']['total_conversations'] > 0:
        avg_messages = sum(
            conv['nombre_messages'] for conv in result['conversations']
        ) / result['meta']['total_conversations']
        print(f"Moyenne messages/conversation: {avg_messages:.1f}")
    print("=" * 60)


if __name__ == '__main__':
    main()
