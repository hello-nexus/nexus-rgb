#!/bin/bash
# Bundle the macOS openrgb-headless binary + its Homebrew dylib deps into a
# self-contained folder, rewriting link paths to @loader_path so the bundle
# can be copied anywhere.
#
# Usage: ./bundle-macos.sh [output-dir]
# Default output-dir is ../nexus-service/Bundled/osx-arm64/openrgb/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/openrgb-headless/OpenRGB"
OUT="${1:-$SCRIPT_DIR/../nexus-service/Bundled/osx-arm64/openrgb}"

if [ ! -f "$SRC" ]; then
    echo "ERROR: openrgb-headless binary not found at $SRC" >&2
    echo "Build it first: cd openrgb-headless && qmake OpenRGB.pro CONFIG+=release CONFIG+=sdk_no_version_check && make -j" >&2
    exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"

# Copy binary with the name the service expects
cp "$SRC" "$OUT/OpenRGB-headless"
chmod +x "$OUT/OpenRGB-headless"

# Collect all non-system dylibs the binary references
dylibs=$(otool -L "$OUT/OpenRGB-headless" | awk '/\/usr\/local\/|\/opt\/homebrew\//{print $1}')

# Copy each dylib next to the binary
for lib in $dylibs; do
    if [ -f "$lib" ]; then
        basename=$(basename "$lib")
        cp -n "$lib" "$OUT/$basename" 2>/dev/null || true
        chmod u+w "$OUT/$basename"
    fi
done

# Rewrite dylib references in the binary to use @loader_path
for lib in $dylibs; do
    basename=$(basename "$lib")
    install_name_tool -change "$lib" "@loader_path/$basename" "$OUT/OpenRGB-headless"
done

# Rewrite dylib references inside each copied dylib (for cross-dylib deps).
# mbedtls dylibs cross-reference each other via @rpath/ — rewrite those too.
for lib in "$OUT"/*.dylib; do
    [ -f "$lib" ] || continue
    basename=$(basename "$lib")
    # Set this dylib's own install name
    install_name_tool -id "@loader_path/$basename" "$lib"
    # Rewrite any cross-dylib refs (both absolute and @rpath/)
    for ref in $(otool -L "$lib" | awk '$1 ~ /^(\/usr\/local\/|\/opt\/homebrew\/|@rpath\/)/{print $1}'); do
        refname=$(basename "$ref")
        if [ -f "$OUT/$refname" ] && [ "$refname" != "$basename" ]; then
            install_name_tool -change "$ref" "@loader_path/$refname" "$lib"
        fi
    done
done

# Copy the GPL license text + a README pointing to the public source
cp "$SCRIPT_DIR/openrgb-headless/LICENSE" "$OUT/LICENSE-OpenRGB.txt"
cat > "$OUT/README.txt" <<EOF
OpenRGB headless build
----------------------
Source: https://github.com/nexusqos/openrgb-headless
License: GPL-2.0-or-later (see LICENSE-OpenRGB.txt)
EOF

echo "Bundled: $OUT"
ls -la "$OUT"
