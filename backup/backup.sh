#!/bin/sh
# Sauvegarde compressée de la base (schéma public uniquement) ; garde les 2 plus récentes.
# Lancé par crond dans le conteneur « backup », ou à la main :
#   docker compose run --rm --entrypoint sh backup /usr/local/bin/backup.sh
set -eu

DEST=/backups
KEEP=2
URL_FILE=/run/secrets/database_url

if [ ! -s "$URL_FILE" ]; then
  echo "$(date '+%F %T') ERREUR : secret database_url absent ou vide" >&2
  exit 1
fi

mkdir -p "$DEST"
STAMP=$(date '+%Y%m%d-%H%M%S')
TMP="$DEST/.frigo-$STAMP.dump.partial"
FINAL="$DEST/frigo-$STAMP.dump"

# -Fc : format compressé de pg_dump ; le fichier n'est renommé qu'une fois complet.
pg_dump "$(cat "$URL_FILE")" --schema=public --format=custom --compress=9 \
  --no-owner --no-privileges --file="$TMP"
mv "$TMP" "$FINAL"
echo "$(date '+%F %T') sauvegarde OK : $FINAL ($(du -h "$FINAL" | cut -f1))"

# Rotation : seules les $KEEP plus récentes sont conservées.
ls -1t "$DEST"/frigo-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old"
  echo "$(date '+%F %T') ancienne sauvegarde supprimée : $old"
done
