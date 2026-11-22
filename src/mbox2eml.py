#!/usr/bin/env python3
"""Convertit un fichier mbox en fichiers .eml individuels.

Usage :
    mbox2eml.py SOURCE [DESTINATION]

SOURCE : fichier au format mbox (doit exister).
DESTINATION : dossier où écrire les .eml ; par défaut « mbox.d »
dans le dossier contenant le fichier source.

Chaque message est écrit sous la forme :
    <date>_<expéditeur>_<objet limité à 50 caractères>.eml
"""

import argparse
import re
import sys
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from mailbox import mbox
from pathlib import Path

# Caractères interdits dans un nom de fichier (Windows + séparateurs Unix + contrôle)
CARACTERES_INTERDITS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def nettoyer(texte, longueur_max=None):
    """Rend une chaîne utilisable dans un nom de fichier."""
    texte = CARACTERES_INTERDITS.sub("", texte)
    texte = re.sub(r"\s+", " ", texte).strip().rstrip(".")
    if longueur_max is not None:
        texte = texte[:longueur_max].strip().rstrip(".")
    return texte


def decoder_entete(valeur):
    # noinspection GrazieStyle
    """Décode un en-tête encodé RFC 2047 (ex. =?utf-8?Q?...?=)."""
    if not valeur:
        return ""
    try:
        return str(make_header(decode_header(valeur)))
    except Exception:
        return valeur


def nom_date(message):
    """Date du message au format AAAAMMJJ_HHMMSS."""
    try:
        date = parsedate_to_datetime(message.get("Date"))
    except Exception:
        return "sansdate"
    if date is None:
        return "sansdate"
    return date.strftime("%Y%m%d_%H%M%S")


def nom_expediteur(message):
    """Adresse e-mail de l'expéditeur, assainie"""
    expediteur = parseaddr(message.get("From", ""))[1]
    return nettoyer(expediteur) or "inconnu"


def nom_objet(message):
    """Objet décodé et limité à 50 caractères."""
    objet = nettoyer(decoder_entete(message.get("Subject", "")), longueur_max=50)
    return objet or "sansobjet"


def chemin_unique(chemin):
    """Retourne un chemin non utilisé, avec suffixe -n en cas de collision."""
    if not chemin.exists():
        return chemin
    n = 1
    while True:
        candidat = chemin.with_name(f"{chemin.stem}-{n}{chemin.suffix}")
        if not candidat.exists():
            return candidat
        n += 1


def main():
    analyseur = argparse.ArgumentParser(
        description="Convertit un fichier mbox en fichiers .eml individuels."
    )
    analyseur.add_argument("source", help="fichier source au format mbox")
    analyseur.add_argument(
        "destination",
        nargs="?",
        default=None,
        help="dossier des .eml (par défaut : mbox.d à côté du fichier source)",
    )
    args = analyseur.parse_args()

    source = Path(args.source)
    if not source.is_file():
        analyseur.error(f"le fichier source n'existe pas : {source}")

    if args.destination:
        destination = Path(args.destination)
    else:
        destination = source.parent / "mbox.d"

    if destination.exists() and not destination.is_dir():
        analyseur.error(f"la destination existe et n'est pas un dossier : {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    try:
        boite = mbox(str(source))
    except Exception as erreur:
        sys.exit(f"impossible de lire la boîte mbox {source} : {erreur}")

    total = 0
    for message in boite:
        nom = f"{nom_date(message)}_{nom_expediteur(message)}_{nom_objet(message)}.eml"
        fichier = chemin_unique(destination / nom)
        fichier.write_bytes(message.as_bytes())
        total += 1
        print(f"mail {total}: fichier: {fichier.name}")

    if total == 0:
        sys.exit(f"aucun message trouvé dans {source} (le fichier est-il bien au format mbox ?)")
    print(f"{total} message(s) écrit(s) dans {destination}")


if __name__ == "__main__":
    main()
