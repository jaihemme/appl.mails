"""Tests de src/generate_reports.py : rapports, résumé LLM et cache."""
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote
import pytest
import generate_reports as gr
from utilitaires import conversation_test

RESUME_SIMULE = "Résumé narratif simulé de la conversation."


class FausseReponse:
    """Réponse OpenAI simulée (urllib context manager)."""

    def __init__(self, contenu=RESUME_SIMULE):
        self._contenu = contenu

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps({"choices": [{"message": {"content": self._contenu}}],
                           "usage": {"total_tokens": 42}}).encode("utf-8")


@pytest.fixture
def api_simulee(monkeypatch):
    """Remplace urlopen par une fausse API OpenAI qui compte les appels."""
    appels = []

    def _faux_urlopen(requete, timeout=None):
        appels.append(requete)
        return FausseReponse()

    monkeypatch.setattr(urllib.request, "urlopen", _faux_urlopen)
    return appels


@pytest.fixture
def api_en_erreur(monkeypatch):
    """Remplace urlopen par une API qui renvoie une erreur HTTP 401."""
    def _faux_urlopen(requete, timeout=None):
        raise urllib.error.HTTPError(gr.OPENAI_URL, 401, "Unauthorized", None,
                                     io.BytesIO(b'{"error": "bad key"}'))
    monkeypatch.setattr(urllib.request, "urlopen", _faux_urlopen)


@pytest.fixture
def cle_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


@pytest.fixture
def sans_cle(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def lancer_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["generate_reports.py", *[str(a) for a in args]])
    gr.main()


# --------------------------------------------------------- fonctions internes


def test_slugify():
    assert gr.slugify("Catalogue Promotion 2026 !") == "catalogue_promotion_2026"
    assert gr.slugify("   ") == ""


def test_compute_conversation_hash():
    conv = conversation_test()
    h1 = gr.compute_conversation_hash(conv)
    assert h1 == gr.compute_conversation_hash(conversation_test())
    # un changement de message_id ou de timestamp change le hash
    modifie = conversation_test(
        messages=[dict(conv["messages"][0], timestamp="2026-11-10T09:00:00")])
    assert gr.compute_conversation_hash(modifie) != h1
    # un changement du corps seul ne le change pas
    corps = conversation_test(
        messages=[dict(conv["messages"][0], contenu_nettoye="autre corps")])
    assert gr.compute_conversation_hash(corps) == h1


def test_get_attachment_filename():
    ancien = {"nom": "ancien.pdf", "creation-date": "Fri, 13 Dec 2024 10:00:00 GMT"}
    assert gr.get_attachment_filename(ancien) == "20241213100000_ancien.pdf"
    assert gr.get_attachment_filename({"nom": "simple.pdf"}) == "simple.pdf"
    assert gr.get_attachment_filename({"nom": "x.pdf", "creation-date": "13/12/2024"}) \
        == "00000000000000_x.pdf"


# ------------------------------------------------------------- needs_update


def test_needs_update_cycle_complet(tmp_path):
    conv = conversation_test()
    assert gr.needs_update(conv, tmp_path) is True      # rapport absent

    gr.generate_report(conv, tmp_path, tmp_path / "PJ")
    assert gr.needs_update(conv, tmp_path) is False     # inchangé -> pas de màj

    modifiee = conversation_test(
        messages=[dict(conv["messages"][0], timestamp="2026-11-10T09:00:00")])
    assert gr.needs_update(modifiee, tmp_path) is True  # modifiée -> màj


# ------------------------------------------------------------ generate_report


def test_generate_report_contenu_et_pieces_jointes(tmp_path):
    dossier_pj = tmp_path / "PJ"
    dossier_pj.mkdir()
    existante = dossier_pj / "test1@exemple.fr_catalogue.pdf"
    existante.write_bytes(b"x")
    ancienne = dossier_pj / "20241213100000_ancien.pdf"
    ancienne.write_bytes(b"y")

    message = dict(conversation_test()["messages"][0], pieces_jointes=[
        {"nom": "catalogue.pdf", "type": "application/pdf", "taille": 1,
         "chemin": str(existante)},                                # chemin JSON valide
        {"nom": "ancien.pdf", "creation-date": "Fri, 13 Dec 2024 10:00:00 GMT"},
        {"nom": "perdu.pdf"},                                      # introuvable
    ])
    conv = conversation_test(messages=[message])

    rapport = gr.generate_report(conv, tmp_path, dossier_pj)
    contenu = Path(rapport).read_text(encoding="utf-8")
    assert "# Test Rapport" in contenu
    assert "## Messages (1)" in contenu
    assert "| 2026-11-09 10:00:00 |" in contenu
    assert "jean@exemple.fr" in contenu and "marie@exemple.fr" in contenu
    assert "## Résumé" in contenu
    # liens des pièces jointes : chemin JSON, nommage historique, introuvable
    # (liens encodés URL : '@' devient %40)
    assert f"- [catalogue.pdf]({quote(str(existante))})" in contenu
    assert f"- [ancien.pdf]({quote(str(ancienne))})" in contenu
    assert "perdu.pdf" in contenu and "Fichier non trouvé" in contenu
    # hash de mise à jour incrémentale
    assert f"<!-- hash: {gr.compute_conversation_hash(conv)} -->" in contenu


# --------------------------------------------------- résumé LLM et cache


def test_resume_llm_succes_puis_cache(tmp_path, api_simulee, cle_api):
    conv = conversation_test()
    cache = tmp_path / "openai_cache.d"

    r1 = gr.generate_llm_summary(conv, str(cache))
    assert r1 == RESUME_SIMULE
    assert len(api_simulee) == 1
    requete = api_simulee[0]
    assert requete.full_url == gr.OPENAI_URL
    assert requete.get_header("Authorization") == "Bearer sk-test"

    entrees = list(cache.glob("*.json"))
    assert len(entrees) == 1
    entree = json.loads(entrees[0].read_text(encoding="utf-8"))
    assert entree["resume"] == RESUME_SIMULE
    assert entree["model"] == gr.OPENAI_MODEL
    assert entree["date"]

    r2 = gr.generate_llm_summary(conv, str(cache))
    assert r2 == RESUME_SIMULE
    assert len(api_simulee) == 1  # hit cache : aucun nouvel appel


def test_resume_llm_cache_meme_sans_cle(tmp_path, api_simulee, cle_api, monkeypatch):
    conv = conversation_test()
    cache = str(tmp_path / "openai_cache.d")
    assert gr.generate_llm_summary(conv, cache) == RESUME_SIMULE

    monkeypatch.delenv("OPENAI_API_KEY")
    assert len(api_simulee) == 1
    assert gr.generate_llm_summary(conv, cache) == RESUME_SIMULE  # restauré du cache
    assert len(api_simulee) == 1  # toujours aucun appel


def test_resume_llm_sans_cle_sans_cache(tmp_path, sans_cle, capsys):
    conv = conversation_test()
    r = gr.generate_llm_summary(conv, str(tmp_path / "cache"))
    assert "clé OPENAI_API_KEY absente" in r
    assert not (tmp_path / "cache").exists()  # aucun dossier créé sans écriture
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().out


def test_resume_llm_entree_cache_corrompue(tmp_path, api_simulee, cle_api):
    conv = conversation_test()
    cache = tmp_path / "openai_cache.d"
    assert gr.generate_llm_summary(conv, str(cache)) == RESUME_SIMULE
    entree = next(cache.glob("*.json"))
    entree.write_text("{json cassé", encoding="utf-8")

    r = gr.generate_llm_summary(conv, str(cache))
    assert r == RESUME_SIMULE
    assert len(api_simulee) == 2  # cache corrompu -> nouvel appel
    assert json.loads(entree.read_text(encoding="utf-8"))["resume"] == RESUME_SIMULE


def test_resume_llm_erreur_http_401(tmp_path, api_en_erreur, cle_api, capsys):
    r = gr.generate_llm_summary(conversation_test(), str(tmp_path / "cache"))
    assert "erreur HTTP 401" in r
    assert "OpenAI API error 401" in capsys.readouterr().out


def test_resume_llm_prompt_contient_la_conversation(tmp_path, api_simulee, cle_api):
    gr.generate_llm_summary(conversation_test(), str(tmp_path / "cache"))
    payload = json.loads(api_simulee[0].data.decode("utf-8"))
    assert payload["model"] == gr.OPENAI_MODEL
    assert payload["messages"][0]["role"] == "system"
    conv_texte = payload["messages"][1]["content"]
    assert "Test Rapport" in conv_texte
    assert "jean@exemple.fr" in conv_texte
    assert "Chère Madame, voici le catalogue demandé." in conv_texte


# --------------------------------------------------------------------- main


def ecrire_json_entree(tmp_path, conversations):
    entree = tmp_path / "data" / "ppe.json"
    entree.parent.mkdir(exist_ok=True)
    entree.write_text(json.dumps({"meta": {}, "conversations": conversations},
                                 ensure_ascii=False), encoding="utf-8")
    return entree


def test_main_bout_en_bout_avec_cache(tmp_path, monkeypatch, api_simulee, cle_api, capsys):
    entree = ecrire_json_entree(tmp_path, [conversation_test()])
    args = ["--input", entree, "--rapports-dir", tmp_path / "rp",
            "--attachment-dir", tmp_path / "PJ", "--llm-cache-dir", tmp_path / "cache"]

    lancer_main(monkeypatch, *args, "--force")
    rapport = tmp_path / "rp" / "test_rapport.md"
    assert rapport.exists()
    assert RESUME_SIMULE in rapport.read_text(encoding="utf-8")
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1

    # 2e exécution sans --force : conversation inchangée -> rien à mettre à jour
    lancer_main(monkeypatch, *args)
    assert "Done. 0 reports were created or updated." in capsys.readouterr().out


def test_main_sans_cle_resume_indisponible(tmp_path, monkeypatch, sans_cle, capsys):
    entree = ecrire_json_entree(tmp_path, [conversation_test()])
    lancer_main(monkeypatch, "--input", entree, "--rapports-dir", tmp_path / "rp")
    rapport = tmp_path / "rp" / "test_rapport.md"
    assert rapport.exists()
    assert "Résumé narratif indisponible (clé OPENAI_API_KEY absente)" \
        in rapport.read_text(encoding="utf-8")


def test_main_dossiers_par_defaut(tmp_path, monkeypatch, sans_cle, capsys):
    entree = ecrire_json_entree(tmp_path, [conversation_test()])
    lancer_main(monkeypatch, "--input", entree)

    # <input>/reports.d avec le rapport
    rapport = entree.parent / "reports.d" / "test_rapport.md"
    assert rapport.exists()
    # les dossiers annexes ne sont créés qu'à l'usage
    assert not (entree.parent / "attachments.d").exists()
    assert not (entree.parent / "openai_cache.d").exists()


def test_main_fichier_entree_inexistant(tmp_path, monkeypatch, capsys):
    lancer_main(monkeypatch, "--input", tmp_path / "absent.json")
    assert "Error: Input file" in capsys.readouterr().out
