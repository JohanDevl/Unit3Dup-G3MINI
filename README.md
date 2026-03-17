# Unit3Dup — Fork G3MINI

Fork de [Unit3Dup](https://github.com/31December99/Unit3Dup) adapté pour **G3MINI Tracker**.

Ce fork ajoute la normalisation automatique des noms de release selon les conventions du tracker, la détection du flag `personal_release` par tag d'équipe, et le nettoyage automatique des fichiers `.nfo` orphelins.

---

## Fonctionnalités ajoutées

- **Normalisation des noms de release** : les noms sont automatiquement reformatés selon les conventions G3MINI (`Titre.Année.Langue.Résolution.HDR.Source.Audio.Codec-TEAM`)
- **Détection `personal_release`** : si le tag de la release (ex: `-KFL`) correspond à un tag configuré dans `TAGS_TEAM`, le champ `personal_release` est automatiquement coché à l'upload
- **Nettoyage des `.nfo` orphelins** : le watcher supprime automatiquement les fichiers `.nfo` isolés après traitement

---

## Installation

### Prérequis

```bash
sudo apt install ffmpeg python3 python3-pip git
```

### Installation depuis ce fork

```bash
git clone https://github.com/lantiumBot/Unit3Dup-G3MINI
cd Unit3Dup-G3MINI
pip install -e .
```

> L'option `-e` (editable) permet de recevoir les mises à jour du fork simplement avec un `git pull`.

### Wrapper (optionnel)

Pour utiliser `unit3dup` depuis n'importe où sans activer le venv manuellement :

```bash
sudo ln -s /opt/unit3dup/unit3dup-wrapper.sh /usr/local/bin/unit3dup
```

> Adapte le chemin si tu as cloné le repo ailleurs que dans `/opt/unit3dup`.

### Mise à jour

```bash
cd Unit3Dup-G3MINI
git pull
```

---

## Configuration

### Étape 1 — Générer la configuration

Au premier lancement, unit3dup crée automatiquement le dossier `~/Unit3Dup_config/` et y génère un fichier `Unit3Dbot.json` pré-rempli :

```bash
unit3dup --help
```

### Étape 2 — Remplir la configuration

Ouvrez le fichier généré et renseignez vos informations :

```bash
nano ~/Unit3Dup_config/Unit3Dbot.json
```

Les champs essentiels à remplir :

- `Gemini_URL` : l'URL de G3MINI
- `Gemini_APIKEY` : ta clé API (disponible dans ton profil)
- `Gemini_PID` : ton passkey
- `TMDB_APIKEY` : clé gratuite sur [themoviedb.org](https://www.themoviedb.org/settings/api)
- `IMGBB_KEY` : clé gratuite sur [imgbb.com](https://imgbb.com) (recommandé pour les screenshots)
- `WATCHER_PATH` : chemin vers ton dossier de watch
- `WATCHER_DESTINATION_PATH` : chemin vers le dossier de destination des torrents

### Étape 3 — Ajouter tes tags d'équipe

La section `uploader_tag` n'est pas générée automatiquement, il faut l'ajouter manuellement dans le JSON :

```json
"uploader_tag": {
    "TAGS_TEAM": ["MONTAG"]
}
```

Si ta release se termine par `-MONTAG`, le champ `personal_release` sera automatiquement activé à l'upload.

---

## Utilisation

```bash
# Uploader un fichier
unit3dup -u /chemin/vers/fichier.mkv

# Uploader un dossier entier
unit3dup -f /chemin/vers/dossier

# Scanner un dossier
unit3dup -scan /chemin/vers/dossier
```

---

## Projet original

Ce fork est basé sur [Unit3Dup](https://github.com/31December99/Unit3Dup) — licence MIT.