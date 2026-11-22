"""Fabriques partagées pour construire des .eml et des conversations de test."""
import base64
import quopri

CORPS_ACCENTUE = ("Chère Madame,\n\nMerci pour votre mail !\n\n"
                  "J'ai plaisir à vous mettre en insertion le catalogue de notre "
                  "promotion à Neyruz.\n\nAnalysez-le et pour toute question "
                  "n'hésitez pas à me contacter.")


def qp_iso8859(texte):
    """Encode un texte en quoted-printable iso-8859-1 (corps MIME)."""
    return quopri.encodestring(texte.encode('iso-8859-1')).decode('ascii')


def eml_simple(message_id="test1@exemple.fr", sujet="Catalogue promotion",
               texte=CORPS_ACCENTUE, avec_message_id=True):
    """Un .eml simple-part text/plain iso-8859-1 quoted-printable."""
    entete_id = f"Message-ID: <{message_id}>\n" if avec_message_id else ""
    return (f"{entete_id}"
            f"From: Jean Exemple <jean@exemple.fr>\n"
            f"To: Marie Dupont <marie@exemple.fr>\n"
            f"Subject: {sujet}\n"
            f"Date: Mon, 09 Nov 2026 10:00:00 +0100\n"
            f"MIME-Version: 1.0\n"
            f'Content-Type: text/plain; charset="iso-8859-1"\n'
            f"Content-Transfer-Encoding: quoted-printable\n"
            f"\n"
            f"{qp_iso8859(texte)}")


def eml_multipart(message_id="test1@exemple.fr", sujet="Catalogue promotion",
                  texte=CORPS_ACCENTUE, pieces_jointes=(), avec_message_id=True):
    """Un .eml multipart/mixed : part text/plain iso-8859-1 + pièces jointes base64.

    pieces_jointes : séquence de (nom, contenu_bytes).
    """
    entete_id = f"Message-ID: <{message_id}>\n" if avec_message_id else ""
    parties = ""
    for nom, contenu in pieces_jointes:
        parties += (f"--BOUND\n"
                    f'Content-Type: application/pdf; name="{nom}"\n'
                    f"Content-Transfer-Encoding: base64\n"
                    f'Content-Disposition: attachment; filename="{nom}"\n'
                    f"\n"
                    f"{base64.encodebytes(contenu).decode('ascii')}")
    return (f"{entete_id}"
            f"From: Jean Exemple <jean@exemple.fr>\n"
            f"To: Marie Dupont <marie@exemple.fr>\n"
            f"Subject: {sujet}\n"
            f"Date: Mon, 09 Nov 2026 10:00:00 +0100\n"
            f"MIME-Version: 1.0\n"
            f'Content-Type: multipart/mixed; boundary="BOUND"\n'
            f"\n"
            f"--BOUND\n"
            f'Content-Type: text/plain; charset="iso-8859-1"\n'
            f"Content-Transfer-Encoding: quoted-printable\n"
            f"\n"
            f"{qp_iso8859(texte)}\n"
            f"{parties}"
            f"--BOUND--\n")


def eml_multipart_alternative(message_id="test1@exemple.fr", sujet="Catalogue promotion",
                              texte=CORPS_ACCENTUE):
    """Un .eml multipart/alternative avec part text/plain iso-8859-1 (bug historique des accents)."""
    return (f"Message-ID: <{message_id}>\n"
            f"From: Jean Exemple <jean@exemple.fr>\n"
            f"To: Marie Dupont <marie@exemple.fr>\n"
            f"Subject: {sujet}\n"
            f"Date: Mon, 09 Nov 2026 11:00:00 +0100\n"
            f"MIME-Version: 1.0\n"
            f'Content-Type: multipart/alternative; boundary="BOUND"\n'
            f"\n"
            f"--BOUND\n"
            f'Content-Type: text/plain; charset="iso-8859-1"\n'
            f"Content-Transfer-Encoding: quoted-printable\n"
            f"\n"
            f"{qp_iso8859(texte)}\n"
            f"--BOUND\n"
            f'Content-Type: text/html; charset="iso-8859-1"\n'
            f"Content-Transfer-Encoding: quoted-printable\n"
            f"\n"
            f"<html><body><p>Version HTML</p></body></html>\n"
            f"--BOUND--\n")


def eml_sans_charset(message_id="test3@exemple.fr", sujet="Sans charset",
                     texte=CORPS_ACCENTUE):
    """Un .eml text/plain sans paramètre charset (repli utf-8 puis iso-8859-1)."""
    return (f"Message-ID: <{message_id}>\n"
            f"From: Jean Exemple <jean@exemple.fr>\n"
            f"To: Marie Dupont <marie@exemple.fr>\n"
            f"Subject: {sujet}\n"
            f"Date: Mon, 09 Nov 2026 12:00:00 +0100\n"
            f"MIME-Version: 1.0\n"
            f"Content-Type: text/plain\n"
            f"Content-Transfer-Encoding: quoted-printable\n"
            f"\n"
            f"{qp_iso8859(texte)}")


def conversation_test(**surcharge):
    """Une conversation minimale pour generate_reports."""
    conv = {
        "sujet": "Test Rapport", "sujet_normalise": "Test Rapport",
        "date_debut": "2026-11-09T10:00:00", "date_fin": "2026-11-09T11:00:00",
        "nombre_messages": 1,
        "messages": [{
            "message_id": "test1@exemple.fr", "in_reply_to": "",
            "timestamp": "2026-11-09T10:00:00", "sujet": "Test Rapport",
            "fichier_source": "/data/mail1.eml",
            "expediteur_nom": "Jean Exemple", "expediteur_email": "jean@exemple.fr",
            "destinataires": {"to": [{"nom": "Marie", "email": "marie@exemple.fr"}],
                              "cc": [], "bcc": []},
            "contenu_nettoye": "Chère Madame, voici le catalogue demandé.",
            "pieces_jointes": []
        }]
    }
    conv.update(surcharge)
    return conv
