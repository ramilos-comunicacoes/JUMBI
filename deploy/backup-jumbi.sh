#!/bin/sh
set -eu
umask 077
backup_root=/srv/jumbi/backups/daily
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$backup_root/$stamp"
install -d -m 700 "$target"
cd /tmp
runuser -u postgres -- pg_dump -Fc --no-owner --no-privileges jumbi_v2 > "$target/database.dump"
tar -czf "$target/private-files.tar.gz" -C /srv/jumbi/shared private_media
tar -czf "$target/brand-files.tar.gz" -C /srv/jumbi/shared media
cp /srv/jumbi/shared/.env "$target/production.env"
readlink -f /srv/jumbi/current > "$target/release.txt"
cd "$target"
sha256sum database.dump private-files.tar.gz brand-files.tar.gz > SHA256SUMS
# Retention applies only to timestamped daily backups under this exact root.
find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name '20??????T??????Z' -mtime +14 -exec rm -rf -- {} +
