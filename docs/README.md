# appl.mails — Traitement et analyse de conversations e-mail

Pipeline en ligne de commande (Python, bibliothèque standard uniquement) :

```text
boite.mbox ──mbox2eml──▶ mbox.d/*.eml ──eml2json_update──▶ conversations.json
                                                               │
                                        generate_reports ──────┘
                                                               ▼
                                                    reports.d/*.md (+ résumé LLM)
```

---

## 📁 Structure du projet

```text
/Users/yogi/Docker/appl.mails/
├── src/
│   ├── mbox2eml.py            # 1. découpe un fichier mbox en .eml individuels
│   ├── eml2json_update.py     # 2. parse les .eml et consolide un JSON de conversations
│   ├── generate_reports.py    # 3. génère les rapports Markdown (résumé LLM)
│   └── …                      # autres scripts utilitaires
├── tests/
│   ├── test_mbox2eml.py       # suite pytest (3 fichiers, 55 tests)
│   ├── test_eml2json_update.py
│   ├── test_generate_reports.py
│   └── utilitaires.py         # fabriques partagées (.eml et conversations de test)
├── docs/
│   └── README.md              # cette documentation
├── pytest.ini                 # configuration pytest (testpaths, pythonpath=src)
├── PPE/                       # exemple de dossier contenant les e-mails sources (.eml)
└── venv/                      # environnement virtuel (pytest installé)
```

---

## ⚙️ 1. `mbox2eml.py` — découpe d'un fichier mbox

### Utilisation

```bash
python3 src/mbox2eml.py SOURCE [DESTINATION]
```

| Argument | Description |
| :--- | :--- |
| `SOURCE` *(requis)* | Fichier au format mbox (doit exister). |
| `DESTINATION` *(optionnel)* | Dossier des `.eml` ; par défaut **`mbox.d`** à côté du fichier source. |

### Nom des fichiers `.eml` générés

Format : `<AAAAMMJJ_HHMMSS>_<expéditeur>_<objet>.eml` — objet **limité à 50 caractères**.

- **Date** : extraite de l'en-tête `Date`, fuseau horaire du message (ex. `20261120_103000`).
- **Expéditeur** : adresse e-mail seule extraite de `From` (ex. `alice@exemple.fr`).
- **Objet** : décodé (RFC 2047, accents corrects), caractères interdits supprimés
  (`/ \ : * ? " < > |` + caractères de contrôle), espaces compactés, limité à 50 caractères.
- **Replis** si un en-tête manque : `sansdate`, `inconnu`, `sansobjet`.
- **Collision** de nom → suffixe `-1`, `-2`, …

Exemples :

```text
20261120_103000_alice@exemple.fr_Catalogue promotion élargi.eml
20261121_080000_carol.martin@exemple.com_SansTitre test.eml        ← caractères / : " * supprimés
sansdate_spam@evil.example_sansobjet.eml                           ← sans Date ni Subject
```

Le contenu du message est préservé à l'identique ; la ligne d'enveloppe mbox (`From `)
est exclue, comme il se doit pour un `.eml`.

### Erreurs

- Source inexistante → erreur et code retour 2.
- Fichier sans aucun message → « aucun message trouvé… » (fichier pas vraiment au format mbox ?).
- Destination existante mais non-dossier → erreur.

---

## ⚙️ 2. `eml2json_update.py` — parsing et consolidation en JSON

### Utilisation

```bash
python3 src/eml2json_update.py --input <FICHIER_OU_DOSSIER_EML> --json_file <FICHIER_JSON> [OPTIONS]
```

| Argument | Type | Description |
| :--- | :---: | :--- |
| `--input` | *Requis* | Fichier `.eml` ou répertoire exploré récursivement (ex. `mbox.d`, `PPE`). |
| `--json_file` | *Requis* | JSON à mettre à jour ou à créer (ex. `data/ppe.json`). |
| `--output` | *Optionnel* | Chemin de sortie alternatif (défaut : identique à `--json_file`). |
| `--attachment-dir` | *Optionnel* | Dossier où écrire les pièces jointes (défaut : **`pieces_jointes.d`** à côté du JSON de sortie). |
| `--dry-run` | *Optionnel* | Simulation : JSON non sauvegardé **et** pièces jointes non écrites (les chemins projetés figurent dans le résultat). |
| `--log-level` | *Optionnel* | `debug`, `info` (défaut), `warning`, `error`. |
| `--log-file` | *Optionnel* | Fichier de logs (défaut : `update_conversations.log`). |

### Comportement

1. **Décodage du corps** : le charset déclaré dans `Content-Type` de chaque part est respecté
   (`iso-8859-1`, `utf-8`, quoted-printable, base64…), avec replis `utf-8` puis `iso-8859-1`
   si le charset est absent, invalide ou mensonger.
2. **Nettoyage du corps** (`contenu_nettoye`) : suppression des signatures
   (`--`, `Sent from my…`, `Envoyé de mon…`), des citations (`>`) et des indicateurs
   « Le … a écrit » / « On … wrote ».
3. **Transferts** : si le sujet contient `FWD:` / `TR:` / `Forwarded` et que le corps
   contient un séparateur (« -----Original Message----- », « De : », …), un bloc
   `forwarded_message` (`auteur`, `date`, `sujet`) est extrait.
4. **Pièces jointes** : décodées et écrites dans `--attachment-dir` sous le nom
   **`<message-id>_<nom original>`** (ou `<hash SHA-1 12 car.>_<nom>` sans Message-ID) —
   nommage déterministe : ré-exécuter le script n'écrase pas la structure.
   Homonymes dans un même mail → suffixe `-n`. Le JSON contient `"nom"`, `"type"`,
   `"taille"` (octets réels) et `"chemin"` (chemin absolu) — jamais le payload.
5. **Regroupement en conversations** :
   - déduplication par `message_id` (un message déjà présent est ignoré) ;
   - rattachement via `In-Reply-To` ;
   - à défaut, via le sujet normalisé (préfixes `Re:`, `Fwd:`, `TR:`, `[…]` supprimés) ;
   - sinon création d'une nouvelle conversation ; messages triés chronologiquement,
     `date_debut` / `date_fin` ajustés.
6. **Mise à jour incrémentale** : le JSON existant est chargé et enrichi sans écraser l'historique ;
   les métadonnées globales sont recalculées.

---

## ⚙️ 3. `generate_reports.py` — rapports Markdown et résumé LLM

### Utilisation

```bash
python3 src/generate_reports.py --input <FICHIER_JSON> [OPTIONS]
```

| Argument | Type | Description |
| :--- | :---: | :--- |
| `--input` | *Requis* | JSON de conversations (ex. `data/ppe.json`). |
| `--rapports-dir` | *Optionnel* | Dossier des rapports (défaut : **`reports.d`** à côté du JSON d'entrée). |
| `--attachment-dir` | *Optionnel* | Dossier contenant les fichiers des pièces jointes (défaut : `attachments.d` à côté du JSON d'entrée). |
| `--llm-cache-dir` | *Optionnel* | Dossier du cache des réponses LLM (défaut : **`openai_cache.d`** à côté du JSON d'entrée). |
| `--force` | *Optionnel* | Régénère les rapports même inchangés. |

### Rapport généré (`reports.d/<sujet_normalisé>.md`)

1. **Messages** : tableau chronologique (date, lien vers le `.eml` source, expéditeur → destinataires).
2. **Résumé** : narratif, généré via l'API OpenAI (`OPENAI_MODEL = "gpt-4o-mini"`,
   clé lue dans la variable d'environnement `OPENAI_API_KEY`).
3. **Pièces jointes** : liens — chemin `"chemin"` du JSON s'il existe, sinon recherche
   du fichier dans `--attachment-dir`, sinon mention « Fichier non trouvé ».
4. Un commentaire caché `<!-- hash: … -->` (hash des `message_id` + `timestamp`) permet la
   **mise à jour incrémentale** : seules les conversations modifiées sont régénérées
   (sauf `--force`). Les dossiers annexes ne sont créés qu'au premier usage réel.

### Cache des résumés LLM (`openai_cache.d/<sha256>.json`)

- Clé = SHA-256 de la requête complète (modèle + prompts + contenu de conversation).
- Le cache est vérifié **avant tout** : un résumé en cache est restitué **même sans clé API** —
  relancer les rapports ne consomme des jetons que pour les conversations nouvelles ou modifiées.
- Chaque entrée contient `{"model", "date", "resume"}` ; une entrée corrompue déclenche un
  nouvel appel. Pour forcer la régénération des résumés : supprimer `openai_cache.d`
  ou changer `OPENAI_MODEL`.
- Robustesse : clé absente ou erreur API → avertissement et texte de repli
  « Résumé narratif indisponible (…) » ; la génération de rapport n'échoue jamais à cause du LLM.

---

## 📄 Structure du JSON de conversations

```json
{
  "meta": {
    "date_derniere_mise_a_jour": "2026-11-23T10:15:04.123456",
    "nombre_conversations": 1,
    "nombre_messages": 2
  },
  "conversations": [
    {
      "sujet": "Catalogue promotion",
      "sujet_normalise": "Catalogue promotion",
      "date_debut": "2026-11-09T10:00:00",
      "date_fin": "2026-11-09T14:30:00",
      "nombre_messages": 2,
      "messages": [
        {
          "fichier_source": "/…/mbox.d/20261109_100000_jean@exemple.fr_Catalogue promotion.eml",
          "timestamp": "2026-11-09T10:00:00",
          "message_id": "test1@exemple.fr",
          "in_reply_to": "",
          "expediteur_nom": "Jean Exemple",
          "expediteur_email": "jean@exemple.fr",
          "destinataires": {
            "to": [{"nom": "Marie Dupont", "email": "marie@exemple.fr"}],
            "cc": [],
            "bcc": []
          },
          "sujet": "Catalogue promotion",
          "contenu_nettoye": "Chère Madame, voici le catalogue demandé.",
          "pieces_jointes": [
            {
              "nom": "catalogue.pdf",
              "type": "application/pdf",
              "taille": 5120,
              "chemin": "/…/pieces_jointes.d/test1@exemple.fr_catalogue.pdf"
            }
          ],
          "forwarded_message": null
        }
      ]
    }
  ]
}
```

| Champ | Description |
| :--- | :--- |
| `meta.date_derniere_mise_a_jour` | Horodatage ISO de la dernière exécution modifiante. |
| `meta.nombre_conversations` / `nombre_messages` | Compteurs globaux. |
| `conversations[].sujet_normalise` | Objet nettoyé des préfixes de réponse/transfert (base du regroupement). |
| `conversations[].date_debut` / `date_fin` | Bornes chronologiques du fil. |
| `messages[].timestamp` | Date d'envoi en ISO 8601 (heure locale). |
| `messages[].message_id` / `in_reply_to` | Identifiants RFC 822, sans chevrons. |
| `messages[].destinataires` | Listes `to`, `cc`, `bcc` d'objets `{"nom", "email"}`. |
| `messages[].contenu_nettoye` | Corps textuel après nettoyage (accents décodés selon le charset). |
| `messages[].pieces_jointes[]` | `nom` (nom original), `type` (MIME), `taille` (octets), `chemin` (absolu, si `--attachment-dir`). |
| `messages[].forwarded_message` | `{auteur, date, sujet}` si transfert détecté, sinon `null`. |

---

## 🧪 Tests

```bash
venv/bin/python -m pytest tests/ -v      # 55 tests
```

| Fichier | Contenu |
| :--- | :--- |
| `test_mbox2eml.py` | Destination par défaut, décodage RFC 2047, troncature à 50, caractères interdits, collisions, contenu préservé, erreurs. |
| `test_eml2json_update.py` | Charsets et replis (bug des accents en multipart), pièces jointes (nommage message-id, homonymes, sans Message-ID, dry-run), transferts, nettoyage, fusion des conversations, I/O JSON. |
| `test_generate_reports.py` | Hash incrémental, liens des pièces jointes, résumé LLM (API simulée : succès, cache, cache sans clé, entrée corrompue, erreur 401), `main` bout en bout, dossiers par défaut. |

- `pytest.ini` déclare `testpaths = tests` et `pythonpath = src` : les modules de `src/`
  sont importables sans installation (dans PyCharm, marquer `src/` comme *Sources Root*
  pour éviter les avertissements d'import).
- `tests/utilitaires.py` fournit les fabriques de `.eml` (iso-8859-1, multipart, sans charset…)
  et de conversations utilisées par les trois suites.
- Les résumés LLM sont testés avec une API simulée : aucun appel réseau ni jeton consommé.

---

## 🐳 Docker — pipeline complet sur un nouveau mbox

Le conteneur enchaîne les 3 scripts sur tout nouveau fichier `.mbox` déposé dans le
dossier d'entrée mappé, et met à jour les rapports (conversations, pièces jointes,
cache LLM et rapports persistent dans le volume).

### Fichiers

- `Dockerfile` — image `python:3.13-slim` (bibliothèque standard uniquement,
  ~144 Mo), `PYTHONUTF8=1`, fuseau `Europe/Zurich`.
- `docker/entrypoint.sh` — enchaîne mbox2eml → eml2json_update → generate_reports.

### Construction et exécution

```bash
docker build -t appl.mails .

# déposer les .mbox dans <dossier>/input/ puis :
docker run --rm \
    -e OPENAI_API_KEY=sk-… \
    -v /chemin/vers/dossier:/data \
    appl.mails
```

(À défaut de `-e OPENAI_API_KEY=…`, utiliser `--env-file <fichier>` ; sans clé,
le pipeline fonctionne et les résumés restent « indisponible » jusqu'à un run avec clé.)

### Organisation du volume `/data`

```text
/data
├── input/*.mbox            ← déposer ici les nouveaux mbox
│   └── processed/          ← les mbox traités sont déplacés ici
├── mbox.d/                 ← .eml extraits
├── conversations.json      ← JSON consolidé des conversations
├── pieces_jointes.d/       ← fichiers des pièces jointes
├── reports.d/              ← rapports Markdown (un par conversation)
├── openai_cache.d/         ← cache des résumés LLM
└── logs/                   ← journaux
```

### Comportement

- Chaque `*.mbox` de `input/` est converti puis **déplacé dans `input/processed/`** :
  ré-exécuter le conteneur ne re-traite pas les anciens mails.
- La mise à jour est **incrémentale** : déduplication par `message_id`, les rapports
  ne sont régénérés que pour les conversations modifiées (sauf `--force`).
- Un mbox vide ou illisible est ignoré sans bloquer le reste du pipeline.
- Un run sans nouveau mbox ne fait rien (idempotent).

---

## 🚀 Chaîne complète d'exécution (sans Docker)

```bash
# 1. découpe d'une boîte mbox en .eml
python3 src/mbox2eml.py boite.mbox                    # → mbox.d/ à côté du fichier source

# 2. consolidation des .eml en JSON de conversations (+ pièces jointes)
python3 src/eml2json_update.py --input mbox.d --json_file data/ppe.json

# 3. rapports Markdown avec résumé LLM (OPENAI_API_KEY requis pour les nouveaux résumés)
python3 src/generate_reports.py --input data/ppe.json \
       --attachment-dir data/pieces_jointes.d          # aligné avec l'étape 2
```
