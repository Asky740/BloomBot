import network
import time

def connect_to_wifi(ssid, password):
    """Pripoji se k Wi-Fi siti"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print("Connecting to WiFi:", ssid)
        wlan.connect(ssid, password)
        
        # Cekani na pripojeni
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(0.5)
            timeout -= 1
            print(".", end="")
        
        if wlan.isconnected():
            print("\nSuccessfully connected. IP address:", wlan.ifconfig()[0])
        else:
            print("\nWiFi connection error!")
            
    return wlan

def get_html():
    """Nacte HTML soubor"""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<html><body><h1>HTML loading error: {e}</h1></body></html>"
