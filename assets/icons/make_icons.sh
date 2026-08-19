# Convert SVG to export ico
inkscape -w 16 -h 16 -o 16.png rev80.svg
inkscape -w 32 -h 32 -o 32.png rev80.svg
inkscape -w 48 -h 48 -o 48.png rev80.svg

convert 16.png 32.png 48.png rev80.ico

