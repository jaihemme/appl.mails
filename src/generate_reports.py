import argparse
import json
import logging
import os
import re
import hashlib
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# OpenAI settings for the narrative summaries
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TIMEOUT = 60  # seconds
# Limits to keep API requests reasonably sized
CONTENU_MAX_PAR_MESSAGE = 4000  # chars
CONTENU_MAX_TOTAL = 60000  # chars


def slugify(text):
    """Convert subject to a filesystem-safe filename."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    return re.sub(r'\s+', '_', text).strip('_')

def compute_conversation_hash(conversation):
    """Compute a hash based on message IDs and timestamps to detect changes."""
    hash_input = ""
    for msg in conversation.get('messages', []):
        hash_input += f"{msg.get('message_id', '')}|{msg.get('timestamp', '')}"
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

def get_attachment_filename(attachment_obj):
    """
    Convert attachment object to filename as per README: {date_creation}_{nom_original}
    Note: date_creation in JSON is often in RFC 2822 format (e.g., 'Fri, 13 Dec 2024...').
    We need to normalize it to YYYYMMDDHHMMSS.
    """
    date_str = attachment_obj.get('creation-date', '')
    nom = attachment_obj.get('nom', 'unknown')

    if not date_str:
        return nom

    try:
        # Try to parse RFC 2822 date
        dt = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S GMT')
        formatted_date = dt.strftime('%Y%m%d%H%M%S')
    except ValueError:
        # Fallback if date format differs
        formatted_date = "00000000000000"

    return f"{formatted_date}_{nom}"


def _summary_fallback(sujet, periode, nombre_messages, raison):
    """Fallback text used when the LLM narrative summary cannot be generated."""
    return (f"Résumé narratif indisponible ({raison}).\n\n"
            f"Cette conversation contient {nombre_messages} message(s) concernant « {sujet} » "
            f"sur la période {periode}.")


def _write_cache_entry(cache_dir, cle_cache, resume):
    """
    Store an LLM response in the cache (one JSON file per request).

    Args:
        cache_dir: Cache directory (created if missing; no-op when None).
        cle_cache: SHA-256 hash of the request, used as file name.
        resume: Narrative summary to store.
    """
    if not cache_dir:
        return
    try:
        dossier = Path(cache_dir)
        dossier.mkdir(parents=True, exist_ok=True)
        entree = {
            "model": OPENAI_MODEL,
            "date": datetime.now().isoformat(timespec='seconds'),
            "resume": resume,
        }
        with open(dossier / f"{cle_cache}.json", 'w', encoding='utf-8') as f:
            json.dump(entree, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logging.error(f"Could not write LLM cache entry: {e}")


def generate_llm_summary(conversation_data, cache_dir=None):
    """
    Generate a narrative summary of the conversation using the OpenAI API.

    Responses are cached in cache_dir, one JSON file per request keyed by the
    SHA-256 hash of the full request (model + prompts). The cache is checked
    before any API call; a cached summary is returned even without the API
    key. The API key is read from the OPENAI_API_KEY environment variable.
    When the key is missing and no cache entry exists, or when the API call
    fails, a fallback text is returned so that report generation is not
    interrupted.

    Args:
        conversation_data: Conversation dict from the JSON file.
        cache_dir: Directory of the LLM response cache (optional; no caching
            when None).

    Returns:
        Narrative summary text (or fallback text on failure).
    """
    messages = conversation_data.get('messages', [])
    sujet = conversation_data.get('sujet_normalise', '')
    periode = f"{conversation_data.get('date_debut', '')} → {conversation_data.get('date_fin', '')}"

    # Conversation text, truncated to keep the API request reasonably sized
    parties = []
    for m in messages:
        exp = m.get('expediteur_email', '') or 'Inconnu'
        ts = m.get('timestamp', '')
        contenu = (m.get('contenu_nettoye', '') or '')[:CONTENU_MAX_PAR_MESSAGE]
        parties.append(f"--- Message de {exp} ({ts}) ---\n{contenu}")
    texte = "\n\n".join(parties)
    if len(texte) > CONTENU_MAX_TOTAL:
        texte = texte[:CONTENU_MAX_TOTAL] + "\n\n[... contenu tronqué ...]"

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": ("Tu es un assistant qui rédige de courts résumés narratifs de "
                            "conversations par e-mail, en français, sur un ton neutre et factuel. "
                            "Réponds uniquement avec le résumé, sans commentaire ni mise en forme "
                            "Markdown.")
            },
            {
                "role": "user",
                "content": (f"Voici une conversation par e-mail « {sujet} » ({len(messages)} "
                            f"message(s), période {periode}).\n\n{texte}\n\n"
                            "Rédige un résumé narratif de quelques phrases : contexte, points clés "
                            "des échanges, décisions prises et suites à donner le cas échéant.")
            }
        ],
        "temperature": 0.3,
        "max_tokens": 600,
    }

    # Cache lookup, keyed by the hash of the full request (model + prompts)
    cle_cache = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()
    if cache_dir:
        cache_path = Path(cache_dir) / f"{cle_cache}.json"
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    resume = json.load(f)['resume']
                logging.info(f"LLM summary from cache: {cache_path.name}")
                return resume
            except (OSError, KeyError, ValueError) as e:
                logging.warning(f"Corrupted cache entry {cache_path.name} ({e}); API call required")

    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        logging.warning("OPENAI_API_KEY is not set; LLM summary skipped")
        print("Warning: OPENAI_API_KEY is not set; no LLM summary generated.")
        return _summary_fallback(sujet, periode, len(messages), "clé OPENAI_API_KEY absente")

    try:
        requete = urllib.request.Request(
            OPENAI_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(requete, timeout=OPENAI_TIMEOUT) as reponse:
            resultat = json.loads(reponse.read().decode('utf-8'))
        resume = resultat['choices'][0]['message']['content'].strip()
        total_tokens = resultat.get('usage', {}).get('total_tokens', '?')
        logging.info(f"LLM summary generated ({OPENAI_MODEL}, {total_tokens} tokens)")
        _write_cache_entry(cache_dir, cle_cache, resume)
        return resume
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')[:300]
        logging.error(f"OpenAI API HTTP error: {e.code} {detail}")
        print(f"Warning: OpenAI API error {e.code}; no LLM summary generated.")
        return _summary_fallback(sujet, periode, len(messages), f"erreur HTTP {e.code}")
    except Exception as e:
        logging.error(f"OpenAI API call failed: {e}")
        print(f"Warning: OpenAI API call failed ({e}); no LLM summary generated.")
        return _summary_fallback(sujet, periode, len(messages), f"appel API échoué : {e}")

def needs_update(conversation, rapports_dir):
    """Check if report needs to be created or updated."""
    slug = slugify(conversation['sujet_normalise'])
    report_path = Path(rapports_dir) / f"{slug}.md"

    if not report_path.exists():
        return True

    current_hash = compute_conversation_hash(conversation)

    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
        # Look for hidden hash in HTML comment
        match = re.search(r'<!-- hash: ([a-f0-9]+) -->', content)
        if match:
            stored_hash = match.group(1)
            return current_hash != stored_hash

    return True

def generate_report(conversation, rapports_dir, attachment_dir, llm_cache_dir=None):
    """Generate the Markdown report for a single conversation."""
    slug = slugify(conversation['sujet_normalise'])
    report_path = Path(rapports_dir) / f"{slug}.md"

    # Header
    lines = []
    lines.append(f"# {conversation['sujet_normalise']}")
    lines.append(f"**Période:** {conversation['date_debut'].replace('T', ' ')}"
                 f" - {conversation['date_fin'].replace('T', ' ')}")
    lines.append("")

    # Chapter 1: Messages
    msgs = conversation.get('messages', [])
    lines.append(f"## Messages ({len(msgs)})")

    # Table Header
    lines.append("| Date d'envoi | Sujet et Participants |")
    lines.append("| :--- | :--- |")

    for m in msgs:
        ts = m.get('timestamp', 'N/A')
        sujet = m.get('sujet', 'Sans sujet')
        source = m.get('fichier_source', '')

        # Expéditeur
        exp_nom = m.get('expediteur_nom', '')
        exp_email = m.get('expediteur_email', 'Inconnu')
        exp_full = f"{exp_nom} <{exp_email}>" if exp_nom else exp_email

        # Destinataires (to et cc uniquement)
        dests = m.get('destinataires', {})
        recipients_list = []
        for key in ['to', 'cc']:
            for r in dests.get(key, []):
                name = r.get('nom', '')
                email = r.get('email', '')
                recipients_list.append(f"{name} <{email}>" if name else email)
        dest_str = ", ".join(filter(None, recipients_list))

        source_link = f"[{sujet}]({quote(source)})" if source else sujet

        # Construction de la cellule Sujet (Sujet lien <br> Expéditeur -> Destinataires)
        participants = f"{exp_full} → {dest_str}" if dest_str else exp_full
        subject_cell = f"{source_link}<br>{participants}"

        lines.append(f"| {ts.replace('T', ' ')} | {subject_cell} |")

    lines.append("")

    # Chapter 2: Résumé
    lines.append("## Résumé")
    summary = generate_llm_summary(conversation, llm_cache_dir)
    lines.append(summary)
    lines.append("")

    # Chapter 3: Pièces jointes
    all_attachments = []
    for m in msgs:
        all_attachments.extend(m.get('pieces_jointes', []))

    if all_attachments:
        lines.append("## Pièces jointes")
        for att in all_attachments:
            # Absolute path recorded in the JSON by eml2json_update.py (preferred)
            chemin = att.get('chemin', '')
            if chemin and Path(chemin).exists():
                lines.append(f"- [{att.get('nom')}]({quote(chemin)})")
            else:
                filename = get_attachment_filename(att)
                att_path = Path(attachment_dir) / filename
                if att_path.exists():
                    lines.append(f"- [{att.get('nom')}]({quote(str(att_path))})")
                else:
                    lines.append(f"- {att.get('nom')} *(Fichier non trouvé : {filename})*")
        lines.append("")

    # Footer with hash for incremental updates
    conv_hash = compute_conversation_hash(conversation)
    lines.append(f"<!-- hash: {conv_hash} -->")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    return report_path

def main():
    parser = argparse.ArgumentParser(description="Generate conversation reports from email JSON.")
    parser.add_argument("--input", help="Input JSON file (e.g. ppe.json)")
    parser.add_argument("--rapports-dir", default=None,
                        help="Directory for output reports (default: reports.d next to the input JSON file)")
    parser.add_argument("--attachment-dir", default=None,
                        help="Directory for attachment files (default: attachments.d next to the input JSON file)")
    parser.add_argument("--llm-cache-dir", default=None,
                        help="Directory of the LLM response cache (default: openai_cache.d next to the input JSON file)")
    parser.add_argument("--force", action='store_true', help="Force update")

    args = parser.parse_args()

    input_file = args.input
    if not input_file:
        input_file = input("Please enter the path to the JSON file to process: ").strip()

    if not input_file or not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found.")
        return

    # Default reports directory: reports.d next to the input JSON file
    rapports_dir = args.rapports_dir or os.path.join(
        os.path.dirname(os.path.abspath(input_file)), 'reports.d'
    )

    # Default attachments directory: attachments.d next to the input JSON file
    attachment_dir = args.attachment_dir or os.path.join(
        os.path.dirname(os.path.abspath(input_file)), 'attachments.d'
    )

    # Default LLM cache directory: openai_cache.d next to the input JSON file
    llm_cache_dir = args.llm_cache_dir or os.path.join(
        os.path.dirname(os.path.abspath(input_file)), 'openai_cache.d'
    )

    # Ensure directories exist
    os.makedirs(rapports_dir, exist_ok=True)

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    conversations = data.get('conversations', [])
    print(f"Processing {len(conversations)} conversations...")

    updated_count = 0
    for conv in conversations:
        if needs_update(conv, rapports_dir) or args.force:
            report_path = generate_report(conv, rapports_dir, attachment_dir, llm_cache_dir)
            print(f"Updated: {report_path.name}")
            updated_count += 1

    print(f"\nDone. {updated_count} reports were created or updated.")

if __name__ == "__main__":
    main()
