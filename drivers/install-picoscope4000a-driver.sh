#!/usr/bin/env bash

wget -O- https://labs.picotech.com/Release.gpg.key | sudo gpg --dearmor | sudo tee /usr/share/keyrings/picotech-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/picotech-archive-keyring.gpg] https://labs.picotech.com/picoscope7/debian/ picoscope main" | sudo tee /etc/apt/sources.list.d/picoscope7.list
sudo apt-get update && sudo apt-get install libps4000a

