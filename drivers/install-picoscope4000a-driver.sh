#!/usr/bin/env bash

wget -O- https://labs.picotech.com/Release.gpg.key | sudo gpg --dearmor | sudo tee /usr/share/keyrings/picotech-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/picotech-archive-keyring.gpg] https://labs.picotech.com/picoscope7/debian/ picoscope main" | sudo tee /etc/apt/sources.list.d/picoscope7.list
sudo apt-get update && sudo apt-get install -y libps4000a

# picotech installs the .so to /opt/picoscope/lib — link it into ldconfig's search path
PICO_LIB=/opt/picoscope/lib
if [ -d "$PICO_LIB" ]; then
    echo "$PICO_LIB" | sudo tee /etc/ld.so.conf.d/picoscope.conf > /dev/null
    sudo ldconfig
    echo "PicoScope library registered at $PICO_LIB"
else
    echo "WARNING: $PICO_LIB not found — you may need to link libps4000a.so manually"
fi

