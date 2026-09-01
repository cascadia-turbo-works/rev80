set -xe

icondir="assets/icons"

# Convert SVG to export ico
inkscape -w 16 -h 16 -o "$icondir/16.png" "$icondir/rev80.svg"
inkscape -w 32 -h 32 -o "$icondir/32.png" "$icondir/rev80.svg"
inkscape -w 48 -h 48 -o "$icondir/48.png" "$icondir/rev80.svg"
inkscape -w 64 -h 64 -o "$icondir/64.png" "$icondir/rev80.svg"

convert "$icondir/16.png" "$icondir/32.png" "$icondir/48.png" "$icondir/64.png" rev80.ico

# Export the Linux XDG hicolor icon theme PNG set as package data. PNG, not
# the SVG itself: Qt/KDE's SVG renderer doesn't render this icon correctly
# (breaks in the launcher and taskbar) — see src/rev80/desktop.py.
hicolordir="src/rev80/assets/icons/hicolor"
for size in 16 24 32 48 64 128 256; do
    dest="$hicolordir/${size}x${size}/apps"
    mkdir -p "$dest"
    inkscape -w "$size" -h "$size" -o "$dest/rev80.png" "$icondir/rev80.svg"
done

