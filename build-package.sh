#!/usr/bin/env bash
# Build an Arch Linux pacman package (fh2save-<ver>-<rel>-any.pkg.tar.zst).
set -euo pipefail

cd "$(dirname "$0")"

PKGNAME=fh2save
PKGVER=$(sed -n "s/^pkgver=//p" PKGBUILD)
PKGREL=$(sed -n "s/^pkgrel=//p" PKGBUILD)
TARBALL="$PKGNAME-$PKGVER.tar.gz"

echo ">> building source tarball $TARBALL"
rm -f "$TARBALL"
# Create fh2save-<ver>/ as the top-level directory inside the tarball.
rm -rf "build-$PKGNAME-$PKGVER"
mkdir -p "build-$PKGNAME-$PKGVER/$PKGNAME-$PKGVER"
stage="build-$PKGNAME-$PKGVER/$PKGNAME-$PKGVER"
cp -r fh2save "$stage/"
find "$stage/fh2save" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp -r packaging "$stage/"
cp -r docs "$stage/"
cp README.md AI_USAGE.md THIRD_PARTY_NOTICES.md LICENSE "$stage/"
tar -czf "$TARBALL" -C "build-$PKGNAME-$PKGVER" "$PKGNAME-$PKGVER"
rm -rf "build-$PKGNAME-$PKGVER"

echo ">> running makepkg"
rm -f "$PKGNAME-$PKGVER-$PKGREL-any.pkg.tar.zst"
makepkg -f --nocheck

echo
echo ">> done:"
ls -l "$PKGNAME-$PKGVER-$PKGREL-any.pkg.tar.zst"
