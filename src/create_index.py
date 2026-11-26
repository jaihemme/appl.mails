
#!/usr/bin/env python3

import argparse
from pathlib import Path


def create_index(input_dir: Path):
    files = sorted(
        input_dir.rglob("*.md"),
        key=lambda p: p.stat().st_birthtime,
        reverse=True
    )

    entries = []

    for path in files:
        if path.name == "INDEX.md":
            continue

        lines = path.read_text(encoding="utf-8").splitlines()

        if len(lines) < 2:
            continue

        title = lines[0].strip()
        period = lines[1].strip()

        # Extraire la période après "**Période:**"
        if period.startswith("**Période:**"):
            period = period[len("**Période:**"):].strip()

        # Retirer les marqueurs Markdown du titre
        title = title.lstrip("#").strip()

        relative_path = path.relative_to(input_dir).as_posix()

        entries.append((period, title, relative_path))

    # Génération de l'index Markdown
    output = [
        "| N° | Période | Document |",
        "|---:|---|---|",
    ]

    for number, (period, title, filename) in enumerate(entries, 1):
        output.append(
            f"| {number}. | {period} | [{title}](<{filename}>) |"
        )

    index_path = input_dir / "INDEX.md"
    index_path.write_text("\n".join(output) + "\n", encoding="utf-8")

    print(f"{len(entries)} documents indexés dans {index_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Génère un index Markdown des fichiers .md."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Dossier contenant les fichiers Markdown"
    )

    args = parser.parse_args()

    if not args.input.is_dir():
        parser.error(f"Dossier inexistant : {args.input}")

    create_index(args.input)


if __name__ == "__main__":
    main()
