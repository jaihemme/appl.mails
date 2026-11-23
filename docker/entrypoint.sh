#!/bin/sh
# Pipeline complet : mbox -> .eml -> JSON conversations -> rapports Markdown.
# Tout se passe dans le volume /data :
#   /data/input/*.mbox        fichiers mbox à traiter (déplacés vers input/processed/)
#   /data/mbox.d/             fichiers .eml extraits
#   /data/conversations.json  JSON consolidé des conversations
#   /data/pieces_jointes.d/   fichiers des pièces jointes
#   /data/reports.d/          rapports Markdown (résumé LLM si OPENAI_API_KEY définie)
#   /data/openai_cache.d/     cache des réponses LLM (par hash de requête)
#   /data/logs/               journaux

set -e

INPUT_DIR=/data/input
mkdir -p "$INPUT_DIR" /data/mbox.d /data/logs

# 1. conversion des mbox en .eml ; chaque mbox traitée est déplacée vers input/processed/
for boite in "$INPUT_DIR"/*.mbox; do
    [ -e "$boite" ] || continue
    echo "=== mbox2eml : $boite"
    if python3 /app/src/mbox2eml.py "$boite" /data/mbox.d; then
        mkdir -p "$INPUT_DIR/processed"
        mv "$boite" "$INPUT_DIR/processed/"
    else
        echo "ERREUR : conversion impossible de $boite (ignorée)" >&2
    fi
done

# 2. consolidation des .eml en JSON de conversations (+ pièces jointes sur disque)
echo "=== eml2json_update"
python3 /app/src/eml2json_update.py \
    --input /data/mbox.d \
    --json_file /data/conversations.json \
    --attachment-dir /data/pieces_jointes.d \
    --log-file /data/logs/eml2json.log

# 3. rapports Markdown ; résumé LLM uniquement pour les conversations nouvelles ou modifiées
echo "=== generate_reports"
python3 /app/src/generate_reports.py \
    --input /data/conversations.json \
    --rapports-dir /data/reports.d \
    --attachment-dir /data/pieces_jointes.d \
    --llm-cache-dir /data/openai_cache.d
