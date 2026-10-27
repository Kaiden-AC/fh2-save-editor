# Maintainer: KaidenAC
pkgname=fh2save
pkgver=1.1.1
pkgrel=1
pkgdesc="Curses TUI and CLI editor for Forza Horizon 2 and 3 (Xbox One) save files"
arch=('any')
url="https://github.com/Kaiden-AC/fh2-save-editor"
license=('MIT')
depends=('python')
options=('!strip')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
  install -d "$pkgdir/usr/lib/fh2save"
  cp -r "$srcdir/fh2save-$pkgver/fh2save" "$pkgdir/usr/lib/fh2save/"

  install -Dm755 "$srcdir/fh2save-$pkgver/packaging/fh2save" \
    "$pkgdir/usr/bin/fh2save"

  install -Dm644 "$srcdir/fh2save-$pkgver/packaging/fh2save.desktop" \
    "$pkgdir/usr/share/applications/fh2save.desktop"

  install -Dm644 "$srcdir/fh2save-$pkgver/README.md" \
    "$pkgdir/usr/share/doc/$pkgname/README.md"

  install -Dm644 "$srcdir/fh2save-$pkgver/AI_USAGE.md" \
    "$pkgdir/usr/share/doc/$pkgname/AI_USAGE.md"

  install -Dm644 "$srcdir/fh2save-$pkgver/THIRD_PARTY_NOTICES.md" \
    "$pkgdir/usr/share/doc/$pkgname/THIRD_PARTY_NOTICES.md"

  install -Dm644 "$srcdir/fh2save-$pkgver/docs/ForzaHorizon2_XboxOne_Save_Format.md" \
    "$pkgdir/usr/share/doc/$pkgname/ForzaHorizon2_XboxOne_Save_Format.md"

  install -Dm644 "$srcdir/fh2save-$pkgver/docs/ForzaHorizon3_XboxOne_Save_Format.md" \
    "$pkgdir/usr/share/doc/$pkgname/ForzaHorizon3_XboxOne_Save_Format.md"

  install -Dm644 "$srcdir/fh2save-$pkgver/LICENSE" \
    "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
