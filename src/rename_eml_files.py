#!/usr/bin/env python3
"""
Script de renommage des fichiers .eml selon le format :
AAAA-MM-JJ_HH-MM-SS_Sujet_Nettoye_Expediteur.eml

Utilise le fichier metadonnées_mails.csv généré précédemment.
"""

import csv
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path


def nettoyer_chaine(chaine):
    """
    Nettoie une chaîne pour l'utiliser dans un nom de fichier.
    - Supprime les préfixes de réponse/transfert (case-insensitive) : Re:, RE:, Re_, RE_, Fwd:, Fwd_, TR:, TR_, RV:, R:, AW:
    - Supprime aussi les espaces qui suivent immédiatement ces préfixes.
    - Remplace les espaces par des underscores
    - Supprime les caractères non alphanumériques (sauf . @ _ -)
    - Supprime les sauts de ligne et tabulations
    - Tronque à 50 caractères max
    """
    if not chaine or chaine == 'N/A':
        return 'inconnu'

    # Préfixes possibles : Re, RE, Fwd, TR, RV, R, AW
    # suivis de ':' ou '_', puis des espaces éventuels
    PREFIX_PATTERN = re.compile(
        r'^(?:(?:re|fwd|tr|rv|r|aw)[:_]\s*)+',
        re.IGNORECASE
    )
    chaine = PREFIX_PATTERN.sub('', chaine)
    # Remplacer les espaces par des underscores
    chaine = chaine.replace(' ', '_')
    # Supprimer les caractères non autorisés dans les noms de fichiers
    chaine = re.sub(r'[^\w\.\-\@]', '', chaine)
    # Supprimer les underscores multiples consécutifs
    chaine = re.sub(r'_{2,}', '_', chaine)
    # Supprimer les underscores en début et fin
    chaine = chaine.strip('_')
    # Tronquer à 50 caractères
    return chaine[:50]


def extraire_email(entry):
    """
    Extrait l'adresse email de l'expéditeur si présente.
    Ex: "Jean Dupont <jean@domaine.fr>" -> "jean@domaine.fr"
        "jean@domaine.fr" -> "jean@domaine.fr"
        "N/A" -> "inconnu"
    """
    if not entry or entry == 'N/A':
        return 'inconnu'

    entry = entry.strip()

    # Cherche un email entre < >
    match = re.match(r'^(.*)<([^<>]+)>\s*$', entry)
    if match:
        text_part = match.group(1).strip().strip('"').strip()
        email = match.group(2).strip()
    else:
        # Pas de < >, on considère que c'est juste une adresse email
        text_part = ''
        email = entry.strip().strip('"')

    if text_part:
        name = text_part
    else:
        # Rien avant l'email -> on prend la partie avant le @
        name = email.split('@')[0]

    # Nettoyage : espaces -> underscore
    name = name.replace(' ', '_')

    # Limite à 20 caractères
    return name[:20]


def parser_date(date_str):
    """
    Parse une date RFC 2822 (ex: Tue, 28 Apr 2026 13:39:02 +0000)
    et retourne un datetime au format AAAA-MM-JJ_HH-MM-SS
    """
    if not date_str or date_str in ('N/A', 'ERREUR'):
        return '1970-01-01_00-00-00'

    try:
        # Essayer plusieurs formats courants
        for fmt in [
            '%a, %d %b %Y %H:%M:%S %z',  # Tue, 28 Apr 2026 13:39:02 +0000
            '%a, %d %b %Y %H:%M:%S',      # Tue, 28 Apr 2026 13:39:02
            '%d %b %Y %H:%M:%S %z',       # 28 Apr 2026 13:39:02 +0000
            '%d %b %Y %H:%M:%S',          # 28 Apr 2026 13:39:02
            '%Y-%m-%d %H:%M:%S %z',       # 2026-04-28 13:39:02 +0000
            '%Y-%m-%d %H:%M:%S',          # 2026-04-28 13:39:02
        ]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime('%Y-%m-%d_%H-%M-%S')
            except ValueError:
                continue

        # Si aucun format ne marche, essayer avec email.utils
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt:
            return dt.strftime('%Y-%m-%d_%H-%M-%S')

        return '1970-01-01_00-00-00'
    except Exception:
        return '1970-01-01_00-00-00'


def generer_nouveau_nom(row, dossier):
    """
    Génère le nouveau nom de fichier selon le format :
    AAAA-MM-JJ_HH-MM-SS_Sujet_Nettoye_Expediteur.eml
    """
    date_iso = parser_date(row['Date'])
    sujet_nettoye = nettoyer_chaine(row['Subject'])
    expediteur = extraire_email(row['From'])

    # Construction du nouveau nom
    nouveau_nom = f"{date_iso}_{sujet_nettoye}_{expediteur}.eml"

    # Vérifier qu'il n'y a pas de conflit
    ancien_fichier = dossier / row['Nom_Fichier']
    counter = 1
    while (dossier / nouveau_nom).exists() and (dossier / nouveau_nom).resolve() != ancien_fichier.resolve():
        nouveau_nom = f"{date_iso}_{sujet_nettoye}_{expediteur}_{counter}.eml"
        counter += 1

    return nouveau_nom


def renommer_fichiers(csv_path):
    """
    Renomme les fichiers .eml selon les métadonnées du CSV.
    """
    dossier = csv_path.parent
    log_path = dossier / 'renommage_log.txt'

    # Lire le CSV
    if not csv_path.exists():
        print(f"Erreur: Le fichier CSV {csv_path} n'existe pas.")
        sys.exit(1)

    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("Aucune métadonnée à traiter dans le CSV.")
        return

    print(f"Traitement de {len(rows)} fichier(s) à renommer...")

    # Ouvrir le fichier de log
    with open(log_path, 'w', encoding='utf-8') as log_file:
        log_file.write("ANCIEN NOM -> NOUVEAU NOM\n")
        log_file.write("=" * 60 + "\n")

        success_count = 0
        error_count = 0

        for row in rows:
            ancien_nom = row['Nom_Fichier']
            ancien_fichier = dossier / ancien_nom

            if not ancien_fichier.exists():
                print(f"  [AVERTISSEMENT] {ancien_nom} n'existe pas, ignoré.")
                log_file.write(f"{ancien_nom} -> ERREUR (fichier introuvable)\n")
                error_count += 1
                continue

            nouveau_nom = generer_nouveau_nom(row, dossier)
            nouveau_fichier = dossier / nouveau_nom

            try:
                # Renommer le fichier
                ancien_fichier.rename(nouveau_fichier)
                log_file.write(f"{ancien_nom} -> {nouveau_nom}\n")
                print(f"  Renommé: {ancien_nom} -> {nouveau_nom}")
                success_count += 1
            except Exception as e:
                print(f"  [ERREUR] Impossible de renommer {ancien_nom}: {e}")
                log_file.write(f"{ancien_nom} -> ERREUR ({str(e)})\n")
                error_count += 1

    print("\n" + "=" * 60)
    print("RÉSUMÉ DU RENOMMAGE")
    print("=" * 60)
    print(f"Fichiers renommés: {success_count}")
    print(f"Erreurs: {error_count}")
    print(f"Fichier log: {log_path}")
    print("=" * 60)


def main():
    # --- Configuration des arguments CLI ---
    parser = argparse.ArgumentParser(
        description='Renomme les fichiers .eml dans un dossier en <date><objet><expediteur>.eml.'
    )
    parser.add_argument(
        'dossier',
        nargs='?',
        default=None,
        help='Chemin du dossier contenant les fichiers .eml'
    )

    args = parser.parse_args()

    # --- Sélection du dossier (CLI ou input utilisateur) ---
    if args.dossier is None:
        dossier = input("Chemin du dossier contenant les fichiers .eml à renommer: ").strip()
    else:
        dossier = args.dossier

    directory = Path(dossier)

    # --- Validation du dossier ---
    if not directory.is_dir():
        print(f"Erreur: '{directory}' n'est pas un dossier valide.", file=sys.stderr)
        sys.exit(1)

    # Trouver le fichier CSV dans le répertoire courant
    csv_path = directory / 'metadonnées_mails.csv'

    if not csv_path.exists():
        print("Erreur: Le fichier metadonnées_mails.csv n'existe pas dans le répertoire courant.")
        print("Assurez-vous d'être dans le bon dossier ou spécifiez le chemin du CSV.")
        sys.exit(1)

    renommer_fichiers(csv_path)


if __name__ == '__main__':
    main()
