#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
APP_NAME="sni-forwarder"
ARCH="${ARCH:-amd64}"

if [[ ! -f "dist/$APP_NAME" ]]; then
  echo "Linux binary not found. Building it first..."
  bash scripts/build_linux.sh
fi

PKG_DIR="dist/deb/${APP_NAME}_${VERSION}_${ARCH}"
DEBIAN_DIR="$PKG_DIR/DEBIAN"
BIN_DIR="$PKG_DIR/usr/local/bin"
ETC_DIR="$PKG_DIR/etc/sni-forwarder"
SYSTEMD_DIR="$PKG_DIR/etc/systemd/system"

rm -rf "$PKG_DIR"
mkdir -p "$DEBIAN_DIR" "$BIN_DIR" "$ETC_DIR" "$SYSTEMD_DIR"

install -m 755 "dist/$APP_NAME" "$BIN_DIR/$APP_NAME"
install -m 644 "config.json" "$ETC_DIR/config.json"
install -m 644 "packaging/debian/sni-forwarder.service" "$SYSTEMD_DIR/sni-forwarder.service"
install -m 755 "packaging/debian/postinst" "$DEBIAN_DIR/postinst"
install -m 755 "packaging/debian/prerm" "$DEBIAN_DIR/prerm"

INSTALLED_SIZE="$(du -ks "$PKG_DIR" | cut -f1)"

cat > "$DEBIAN_DIR/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: Maximum Radikali
Installed-Size: $INSTALLED_SIZE
Depends: systemd
Description: Optimized SNI Forwarder
 Upstream source fork with edits and optimization by Maximum Radikali.
EOF

dpkg-deb --build "$PKG_DIR"
echo "Debian package created: dist/deb/${APP_NAME}_${VERSION}_${ARCH}.deb"
