#!/usr/bin/env python3
"""
Script d'extraction de métadonnées depuis des fichiers .eml (RFC 822).
Gère les encodages multiples, les champs manquants et génère un CSV structuré.
"""

import argparse
import csv
import sys
from pathlib import Path
from email.parser import BytesParser
from email.policy import default


def extract_metadata_from_eml(file_path):
    """
    Extrait les métadonnées clés d'un fichier .eml.

    CRITIQUE - Gestion de l'encodage :
    - BytesParser + policy=default : lit le fichier en mode binaire (évite les erreurs
      d'encodage à l'ouverture) et décode AUTOMATIQUEMENT les en-têtes MIME (RFC 2047).
      Exemples gérés :
        =?utf-8?B?8J+YgCB0ZXN0?= -> "Test test"
        =?ISO-8859-1?Q?J=F6rg?= -> "Jörg"
    - Pas besoin de decode_header() manuel : la policy default le fait pour nous.

    Args:
        file_path (Path): Chemin vers le fichier .eml

    Returns:
        dict: Métadonnées avec 'N/A' pour les champs manquants, 'ERREUR' si parsing échoué
    """
    try:
        with open(file_path, 'rb') as f:
            msg = BytesParser(policy=default).parse(f)

        return {
            'Nom_Fichier': file_path.name,
            # .get() retourne None si le champ est absent -> on utilise 'N/A'
            'Date': msg.get('Date', 'N/A') or 'N/A',
            'From': msg.get('From', 'N/A') or 'N/A',
            'To': msg.get('To', 'N/A') or 'N/A',
            'Subject': msg.get('Subject', 'N/A') or 'N/A',
            'Message-ID': msg.get('Message-ID', 'N/A') or 'N/A',
            'In-Reply-To': msg.get('In-Reply-To', 'N/A') or 'N/A'
        }
    except Exception as e:
        print(f"  [ERREUR] {file_path.name}: {str(e)}", file=sys.stderr)
        return {
            'Nom_Fichier': file_path.name,
            'Date': 'ERREUR',
            'From': 'ERREUR',
            'To': 'ERREUR',
            'Subject': 'ERREUR',
            'Message-ID': 'ERREUR',
            'In-Reply-To': 'ERREUR'
        }


def scan_eml_files(directory):
    """
    Parcourt un dossier et traite tous les fichiers .eml.

    Args:
        directory (Path): Dossier à analyser

    Returns:
        tuple: (liste_métadonnées, nombre_erreur)
    """
    eml_files = sorted(directory.glob('*.eml'))  # Tri pour sortie déterministe

    if not eml_files:
        print(f"Aucun fichier .eml trouvé dans {directory}")
        return [], 0

    print(f"Trouvé {len(eml_files)} fichier(s) .eml à traiter...")

    all_metadata = []
    error_count = 0

    for eml_file in eml_files:
        print(f"  Traitement: {eml_file.name}")
        metadata = extract_metadata_from_eml(eml_file)
        all_metadata.append(metadata)
        if metadata['Date'] == 'ERREUR':
            error_count += 1

    return all_metadata, error_count


def write_csv(output_path, metadata_list):
    """
    Génère un fichier CSV UTF-8 avec les métadonnées.

    CRITIQUE - Gestion de l'encodage :
    - encoding='utf-8' : garantit la compatibilité avec les accents et caractères spéciaux
    - errors='replace' : remplace les caractères non encodables par '?' au lieu de planter
    - newline='' : conforme à la RFC 4180 pour CSV
    """
    fieldnames = ['Nom_Fichier', 'Date', 'From', 'To', 'Subject', 'Message-ID', 'In-Reply-To']

    with open(output_path, 'w', newline='', encoding='utf-8', errors='replace') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metadata_list)

    print(f"\nCSV généré: {output_path}")


def main():
    # --- Configuration des arguments CLI ---
    parser = argparse.ArgumentParser(
        description='Extrait les métadonnées des fichiers .eml dans un dossier.'
    )
    parser.add_argument(
        'dossier',
        nargs='?',
        default=None,
        help='Chemin du dossier contenant les fichiers .eml (optionnel)'
    )

    args = parser.parse_args()

    # --- Sélection du dossier (CLI ou input utilisateur) ---
    if args.dossier is None:
        dossier = input("Chemin du dossier contenant les fichiers .eml: ").strip()
    else:
        dossier = args.dossier

    directory = Path(dossier)

    # --- Validation du dossier ---
    if not directory.is_dir():
        print(f"Erreur: '{directory}' n'est pas un dossier valide.", file=sys.stderr)
        sys.exit(1)

    # --- Traitement ---
    metadata_list, error_count = scan_eml_files(directory)

    if not metadata_list:
        print("Aucun fichier .eml à traiter.")
        sys.exit(0)

    # --- Génération du CSV ---
    output_path = directory / 'metadonnées_mails.csv'
    write_csv(output_path, metadata_list)

    # --- Résumé final (BONUS) ---
    print("\n" + "=" * 60)
    print("RÉSUMÉ DU TRAITEMENT")
    print("=" * 60)
    print(f"Dossier analysé      : {directory.absolute()}")
    print(f"Fichiers traités     : {len(metadata_list)}")
    print(f"Fichiers en erreur   : {error_count}")
    print(f"Fichier CSV généré   : {output_path}")
    print("=" * 60)


if __name__ == '__main__':
    main()
