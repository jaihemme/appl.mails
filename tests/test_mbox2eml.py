"""Tests de src/mbox2eml.py : conversion mbox -> fichiers .eml individuels."""
import mailbox
import sys
from email.message import Message
import pytest
import mbox2eml


def creer_mbox(chemin, messages):
    """Écrit une mbox contenant les messages fournis.

    Chaque message est un dict {en-tête: valeur, ..., "_corps": texte du corps}.
    """
    boite = mailbox.mbox(str(chemin))
    for msg in messages:
        m = Message()
        for cle, valeur in msg.items():
            if cle != "_corps":
                m[cle] = valeur
        m.set_payload(msg["_corps"])
        boite.add(m)
    boite.flush()
    boite.close()


@pytest.fixture
def main_mbox2eml(monkeypatch):
    """Appelle mbox2eml.main() avec les arguments donnés."""
    def _run(*args):
        monkeypatch.setattr(sys, "argv", ["mbox2eml.py", *[str(a) for a in args]])
        mbox2eml.main()
    return _run


# ---------------------------------------------------------------- conversion


def test_destination_par_defaut_mbox_d(tmp_path, main_mbox2eml, capsys):
    source = tmp_path / "boite.mbox"
    creer_mbox(source, [
        {"From": "Alice Dupont <alice@exemple.fr>", "To": "bob@exemple.fr",
         "Subject": "Catalogue", "Date": "Mon, 20 Nov 2026 10:30:00 +0100",
         "_corps": "Bonjour,\n\nVoici le catalogue.\n"},
        {"From": "spam@evil.example", "_corps": "Sans en-tetes.\n"},
    ])
    main_mbox2eml(source)

    assert "2 message(s) écrit(s)" in capsys.readouterr().out
    noms = [f.name for f in (tmp_path / "mbox.d").iterdir()]
    assert noms == ["20261120_103000_alice@exemple.fr_Catalogue.eml",
                    "sansdate_spam@evil.example_sansobjet.eml"]


def test_objet_encode_rfc2047_et_tronque_a_50(tmp_path, main_mbox2eml):
    source = tmp_path / "boite.mbox"
    creer_mbox(source, [
        {"From": "Alice <alice@exemple.fr>",
         "Subject": ("=?utf-8?q?R=C3=A9union_de_projet_tr=C3=A8s_importante_"
                     "cette_semaine_pour_l=27=C3=A9quipe?="),
         "Date": "Mon, 20 Nov 2026 10:30:00 +0100", "_corps": "corps\n"},
    ])
    main_mbox2eml(source)
    noms = [f.name for f in (tmp_path / "mbox.d").iterdir()]
    # sujet décodé (accents, apostrophe) puis limité à 50 caractères
    assert noms == ["20261120_103000_alice@exemple.fr_"
                    "Réunion de projet très importante cette semaine po.eml"]


def test_caracteres_interdits_supprimes_du_nom(tmp_path, main_mbox2eml):
    source = tmp_path / "boite.mbox"
    creer_mbox(source, [
        {"From": "carol.martin@exemple.com", "Subject": 'Sans/Titre: "test"*',
         "Date": "Tue, 21 Nov 2026 08:00:00 +0100", "_corps": "x\n"},
    ])
    main_mbox2eml(source)
    noms = [f.name for f in (tmp_path / "mbox.d").iterdir()]
    assert noms == ["20261121_080000_carol.martin@exemple.com_SansTitre test.eml"]


def test_collision_de_noms_suffixe_n(tmp_path, main_mbox2eml):
    source = tmp_path / "boite.mbox"
    msg = {"From": "alice@exemple.fr", "Subject": "Doublon",
           "Date": "Mon, 20 Nov 2026 10:30:00 +0100", "_corps": "corps\n"}
    creer_mbox(source, [msg, dict(msg)])
    main_mbox2eml(source)
    noms = sorted(f.name for f in (tmp_path / "mbox.d").iterdir())
    assert noms == ["20261120_103000_alice@exemple.fr_Doublon-1.eml",
                    "20261120_103000_alice@exemple.fr_Doublon.eml"]


def test_destination_explicite(tmp_path, main_mbox2eml):
    source = tmp_path / "boite.mbox"
    creer_mbox(source, [{"From": "a@b.fr", "Subject": "S",
                         "Date": "Mon, 20 Nov 2026 10:30:00 +0100", "_corps": "x\n"}])
    main_mbox2eml(source, tmp_path / "sortie")
    assert not (tmp_path / "mbox.d").exists()
    assert len(list((tmp_path / "sortie").iterdir())) == 1


def test_contenu_eml_preserve(tmp_path, main_mbox2eml):
    source = tmp_path / "boite.mbox"
    creer_mbox(source, [{"From": "Alice Dupont <alice@exemple.fr>", "To": "bob@exemple.fr",
                         "Subject": "Catalogue", "Date": "Mon, 20 Nov 2026 10:30:00 +0100",
                         "_corps": "Bonjour,\n\nVoici le catalogue.\n"}])
    main_mbox2eml(source)
    eml = (tmp_path / "mbox.d"
           / "20261120_103000_alice@exemple.fr_Catalogue.eml").read_bytes()
    assert eml.startswith(b"From: Alice Dupont <alice@exemple.fr>")
    assert b"To: bob@exemple.fr" in eml
    assert b"Subject: Catalogue" in eml
    assert b"Date: Mon, 20 Nov 2026 10:30:00 +0100" in eml
    assert b"Bonjour" in eml and b"Voici le catalogue" in eml
    # pas de ligne d'enveloppe mbox ("From " initial)
    assert not eml.startswith(b"From ")


# ------------------------------------------------------------------ erreurs


def test_source_inexistante(tmp_path, main_mbox2eml, capsys):
    with pytest.raises(SystemExit) as exc:
        main_mbox2eml(tmp_path / "absent.mbox")
    assert exc.value.code == 2
    assert "n'existe pas" in capsys.readouterr().err


def test_mbox_sans_message(tmp_path, main_mbox2eml):
    source = tmp_path / "vide.mbox"
    source.write_text("")
    # sys.exit(message) : le texte est dans le code de l'exception, pas sur stderr
    with pytest.raises(SystemExit) as exc:
        main_mbox2eml(source)
    assert "aucun message trouvé" in str(exc.value.code)


def test_destination_est_un_fichier(tmp_path, main_mbox2eml, capsys):
    source = tmp_path / "boite.mbox"
    creer_mbox(source, [{"From": "a@b.fr", "Subject": "S",
                         "Date": "Mon, 20 Nov 2026 10:30:00 +0100", "_corps": "x\n"}])
    occupe = tmp_path / "occupe"
    occupe.write_text("x")
    with pytest.raises(SystemExit) as exc:
        main_mbox2eml(source, occupe)
    assert exc.value.code == 2
    assert "n'est pas un dossier" in capsys.readouterr().err


# --------------------------------------------------------- fonctions internes


def test_nettoyer_supprime_caracteres_interdits():
    assert mbox2eml.nettoyer('a/b\\c:d*e?f"g<h>i|j\x00k') == "abcdefghijk"


def test_nettoyer_compacte_espaces_et_points_finaux():
    assert mbox2eml.nettoyer("  a   b  ") == "a b"
    assert mbox2eml.nettoyer("  a   b  ..", longueur_max=30) == "a b"


def test_nettoyer_tronque_a_la_longueur_max():
    assert len(mbox2eml.nettoyer("x" * 100, longueur_max=30)) == 30


def test_decoder_entete_rfc2047():
    assert mbox2eml.decoder_entete("=?utf-8?q?R=C3=A9union?= du lundi") == "Réunion du lundi"
    assert mbox2eml.decoder_entete("") == ""
