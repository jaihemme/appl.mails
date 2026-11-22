"""Tests de src/eml2json_update.py : parsing .eml, pièces jointes, fusion JSON."""
import re
from pathlib import Path
import eml2json_update as e2j
from utilitaires import (CORPS_ACCENTUE, conversation_test, eml_multipart,
                         eml_multipart_alternative, eml_sans_charset, eml_simple)

CONTENU_PDF = bytes(range(256)) * 20  # 5120 octets


def ecrire(tmp_path, nom, contenu):
    chemin = tmp_path / nom
    chemin.write_text(contenu, encoding='utf-8')
    return str(chemin)


def message_test(message_id, sujet="Catalogue", timestamp="2026-11-09T10:00:00",
                 in_reply_to=""):
    """Un message déjà parsé, prêt pour merge_message_into_conversations."""
    return {"message_id": message_id, "in_reply_to": in_reply_to, "sujet": sujet,
            "timestamp": timestamp, "expediteur_nom": "Jean",
            "expediteur_email": "jean@exemple.fr",
            "destinataires": {"to": [], "cc": [], "bcc": []},
            "contenu_nettoye": "corps", "pieces_jointes": [],
            "forwarded_message": None}


# -------------------------------------------------------------- corps / charset


def test_corps_iso8859_1_simple_part(tmp_path):
    f = ecrire(tmp_path, "simple.eml", eml_simple())
    r = e2j.parse_email_file(f)
    assert r is not None
    assert "Chère Madame" in r["contenu_nettoye"]
    assert "n'hésitez pas à me contacter" in r["contenu_nettoye"]
    assert r["expediteur_email"] == "jean@exemple.fr"
    assert r["expediteur_nom"] == "Jean Exemple"
    assert r["sujet"] == "Catalogue promotion"
    assert r["message_id"] == "test1@exemple.fr"
    assert r["timestamp"]  # date parsée


def test_corps_iso8859_1_multipart_alternative(tmp_path):
    # cas historique : le corps multipart était décodé en dur en utf-8
    f = ecrire(tmp_path, "multipart.eml", eml_multipart_alternative())
    r = e2j.parse_email_file(f)
    assert "Chère Madame" in r["contenu_nettoye"]
    assert "\ufffd" not in r["contenu_nettoye"]


def test_charset_absent_repli_utf8_latin1(tmp_path):
    f = ecrire(tmp_path, "sanscharset.eml", eml_sans_charset())
    r = e2j.parse_email_file(f)
    assert "Chère Madame" in r["contenu_nettoye"]


def test_charset_invalide_repli_latin1(tmp_path):
    contenu = eml_simple().replace('charset="iso-8859-1"', 'charset="x-inconnu"')
    r = e2j.parse_email_file(ecrire(tmp_path, "bad.eml", contenu))
    assert "Chère Madame" in r["contenu_nettoye"]


def test_charset_declare_faux_contenu_latin1(tmp_path):
    # charset déclaré utf-8 mais contenu latin-1 : le repli iso-8859-1 doit sauver
    contenu = eml_simple().replace('charset="iso-8859-1"', 'charset="utf-8"')
    r = e2j.parse_email_file(ecrire(tmp_path, "faux.eml", contenu))
    assert "Chère Madame" in r["contenu_nettoye"]
    assert "\ufffd" not in r["contenu_nettoye"]


def test_decode_payload_direct():
    part = type("P", (), {"get_content_charset": lambda self: "iso-8859-1"})()
    assert e2j._decode_payload(part, b"Ch\xe8re") == "Chère"
    assert e2j._decode_payload(part, None) == ""
    assert e2j._decode_payload(part, "déjà décodé") == "déjà décodé"


# ------------------------------------------------------------ pièces jointes


def test_pieces_jointes_enregistrees_avec_chemin(tmp_path):
    f = ecrire(tmp_path, "mail.eml",
               eml_multipart(pieces_jointes=[("catalogue.pdf", CONTENU_PDF)]))
    dossier = tmp_path / "PJ"
    r = e2j.parse_email_file(f, attachment_dir=str(dossier))

    pj = r["pieces_jointes"]
    assert len(pj) == 1
    assert pj[0]["nom"] == "catalogue.pdf"
    assert pj[0]["type"] == "application/pdf"
    assert pj[0]["taille"] == len(CONTENU_PDF)
    assert "payload" not in pj[0]  # le base64 ne doit pas alourdir le JSON
    chemin = Path(pj[0]["chemin"])
    assert chemin.is_absolute()
    assert chemin.name == "test1@exemple.fr_catalogue.pdf"
    assert chemin.read_bytes() == CONTENU_PDF


def test_sans_attachment_dir_pas_de_chemin(tmp_path):
    f = ecrire(tmp_path, "mail.eml",
               eml_multipart(pieces_jointes=[("catalogue.pdf", CONTENU_PDF)]))
    r = e2j.parse_email_file(f)
    assert r["pieces_jointes"][0]["taille"] == len(CONTENU_PDF)
    assert "chemin" not in r["pieces_jointes"][0]
    assert not (tmp_path / "PJ").exists()


def test_meme_piece_jointe_deux_mails_prefixe_message_id(tmp_path):
    f1 = ecrire(tmp_path, "mail1.eml",
                eml_multipart(message_id="test1@exemple.fr",
                              pieces_jointes=[("catalogue.pdf", b"A")]))
    f2 = ecrire(tmp_path, "mail2.eml",
                eml_multipart(message_id="test2@exemple.fr",
                              pieces_jointes=[("catalogue.pdf", b"BB")]))
    dossier = tmp_path / "PJ"
    p1 = e2j.parse_email_file(f1, attachment_dir=str(dossier))["pieces_jointes"][0]
    p2 = e2j.parse_email_file(f2, attachment_dir=str(dossier))["pieces_jointes"][0]
    assert Path(p1["chemin"]).name == "test1@exemple.fr_catalogue.pdf"
    assert Path(p2["chemin"]).name == "test2@exemple.fr_catalogue.pdf"
    assert Path(p1["chemin"]).read_bytes() == b"A"
    assert Path(p2["chemin"]).read_bytes() == b"BB"


def test_homonymes_dans_un_message_suffixe_n(tmp_path):
    f = ecrire(tmp_path, "mail.eml",
               eml_multipart(pieces_jointes=[("catalogue.pdf", b"A"),
                                             ("catalogue.pdf", b"BB")]))
    r = e2j.parse_email_file(f, attachment_dir=str(tmp_path / "PJ"))
    noms = sorted(Path(p["chemin"]).name for p in r["pieces_jointes"])
    assert noms == ["test1@exemple.fr_catalogue-1.pdf",
                    "test1@exemple.fr_catalogue.pdf"]


def test_sans_message_id_nom_par_hash(tmp_path):
    f = ecrire(tmp_path, "mail.eml",
               eml_multipart(avec_message_id=False,
                             pieces_jointes=[("catalogue.pdf", b"A")]))
    r = e2j.parse_email_file(f, attachment_dir=str(tmp_path / "PJ"))
    nom = Path(r["pieces_jointes"][0]["chemin"]).name
    assert re.fullmatch(r"[0-9a-f]{12}_catalogue\.pdf", nom)


def test_dry_run_n_ecrit_rien(tmp_path):
    f = ecrire(tmp_path, "mail.eml",
               eml_multipart(pieces_jointes=[("catalogue.pdf", CONTENU_PDF)]))
    dossier = tmp_path / "PJ"
    r = e2j.parse_email_file(f, attachment_dir=str(dossier), dry_run=True)
    assert not dossier.exists()  # aucune écriture en dry-run
    chemin_attendu = str((dossier / "test1@exemple.fr_catalogue.pdf").resolve())
    assert r["pieces_jointes"][0]["chemin"] == chemin_attendu  # chemin projeté
    # un run réel derrière crée bien le fichier
    r = e2j.parse_email_file(f, attachment_dir=str(dossier))
    assert Path(r["pieces_jointes"][0]["chemin"]).read_bytes() == CONTENU_PDF


# ------------------------------------------------------- transfert / nettoyage


def test_message_transfere(tmp_path):
    corps = (CORPS_ACCENTUE + "\n\n-----Original Message-----\n"
             "From: bob@exemple.fr\nDate: Fri, 06 Nov 2026 09:00:00 +0100\n"
             "Subject: demande initiale\n\nAncien contenu.\n")
    f = ecrire(tmp_path, "tr.eml", eml_simple(sujet="TR: Catalogue", texte=corps))
    r = e2j.parse_email_file(f)
    assert r["forwarded_message"]["auteur"] == "bob@exemple.fr"
    assert r["forwarded_message"]["sujet"] == "demande initiale"
    assert r["forwarded_message"]["date"].startswith("Fri, 06 Nov")
    # la partie transférée est retirée du contenu nettoyé
    assert "Ancien contenu" not in r["contenu_nettoye"]


def test_message_non_transfere(tmp_path):
    r = e2j.parse_email_file(ecrire(tmp_path, "simple.eml", eml_simple()))
    assert r["forwarded_message"] is None


def test_clean_body_signature_et_citations():
    corps = "Bonjour.\n\n> ancien message\n\n-- \nJean Exemple\ntél. 079 000 00 00"
    assert e2j._clean_body(corps) == "Bonjour."


# ------------------------------------------------------------- fonctions divers


def test_normalize_subject():
    assert e2j.normalize_subject("Re: TR: [v1.2]  Catalogue   ") == "Catalogue"
    assert e2j.normalize_subject("") == ""
    assert e2j.normalize_subject("Fwd: Sujet") == "Sujet"


def test_parse_address():
    assert e2j._parse_address("Alice Dupont <alice@ex.fr>") == ("Alice Dupont", "alice@ex.fr")
    assert e2j._parse_address("bob@ex.fr") == ("", "bob@ex.fr")
    assert e2j._parse_address("") == ("", "")


def test_parse_recipients():
    liste = e2j._parse_recipients('"Marie D" <marie@x.fr>, carol@y.fr')
    assert liste == [{"nom": "Marie D", "email": "marie@x.fr"},
                     {"nom": "", "email": "carol@y.fr"}]
    assert e2j._parse_recipients("") == []


def test_fichier_inexistant(tmp_path):
    assert e2j.parse_email_file(str(tmp_path / "absent.eml")) is None


# --------------------------------------------------------------- fusion JSON


def test_merge_nouvelle_conversation_et_doublon(tmp_path):
    data = e2j.load_json(str(tmp_path / "inexistant.json"))
    ok, _ = e2j.merge_message_into_conversations(data, message_test("id1"))
    assert ok
    assert data["meta"]["nombre_messages"] == 1
    assert data["meta"]["nombre_conversations"] == 1
    assert len(data["conversations"][0]["messages"]) == 1

    ok, raison = e2j.merge_message_into_conversations(data, message_test("id1"))
    assert not ok and "already exists" in raison
    assert data["meta"]["nombre_messages"] == 1


def test_merge_sans_message_id():
    ok, raison = e2j.merge_message_into_conversations(
        {"meta": {"nombre_messages": 0, "nombre_conversations": 0}, "conversations": []},
        {"sujet": "sans id"})
    assert not ok and "no valid message_id" in raison


def test_merge_reponse_meme_conversation(tmp_path):
    data = e2j.load_json(str(tmp_path / "inexistant.json"))
    e2j.merge_message_into_conversations(data, message_test("id1"))
    m2 = message_test("id2", timestamp="2026-11-09T11:00:00", in_reply_to="id1")
    ok, _ = e2j.merge_message_into_conversations(data, m2)
    assert ok
    conv = data["conversations"][0]
    assert conv["nombre_messages"] == 2
    assert [m["message_id"] for m in conv["messages"]] == ["id1", "id2"]  # trié par date
    assert conv["date_fin"] == "2026-11-09T11:00:00"


def test_merge_reponse_par_sujet_normalise(tmp_path):
    data = e2j.load_json(str(tmp_path / "inexistant.json"))
    e2j.merge_message_into_conversations(data, message_test("id1", sujet="Catalogue"))
    # pas de in_reply_to mais même sujet normalisé ("Re: " retiré)
    m2 = message_test("id2", sujet="Re: Catalogue")
    ok, _ = e2j.merge_message_into_conversations(data, m2)
    assert ok
    assert data["meta"]["nombre_conversations"] == 1  # même conversation


def test_merge_sujet_different_nouvelle_conversation(tmp_path):
    data = e2j.load_json(str(tmp_path / "inexistant.json"))
    e2j.merge_message_into_conversations(data, message_test("id1", sujet="A"))
    e2j.merge_message_into_conversations(data, message_test("id2", sujet="B"))
    assert data["meta"]["nombre_conversations"] == 2
    assert data["meta"]["nombre_messages"] == 2


# ------------------------------------------------------------------ JSON I/O


def test_load_save_json_roundtrip(tmp_path):
    chemin = tmp_path / "conversations.json"
    data = e2j.load_json(str(chemin))  # inexistant -> structure par défaut
    assert data["meta"]["nombre_messages"] == 0
    assert data["conversations"] == []

    data["conversations"].append({"sujet": "Résumé é"})
    assert e2j.save_json(str(chemin), data)
    # ensure_ascii=False : les accents restent littéraux dans le fichier
    assert "Résumé é" in chemin.read_text(encoding="utf-8")

    recharge = e2j.load_json(str(chemin))
    assert recharge["conversations"][0]["sujet"] == "Résumé é"


def test_load_json_casse(tmp_path):
    casse = tmp_path / "casse.json"
    casse.write_text("{cassé", encoding="utf-8")
    data = e2j.load_json(str(casse))
    assert data["conversations"] == []
    assert "nombre_messages" in data["meta"]


def test_load_json_sans_conversations(tmp_path):
    minimal = tmp_path / "minimal.json"
    minimal.write_text('{"autre": 1}', encoding="utf-8")
    data = e2j.load_json(str(minimal))
    assert data["conversations"] == []
    assert "meta" in data
