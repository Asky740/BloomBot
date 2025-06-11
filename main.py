# Import potřebných knihoven pro síťovou komunikaci, hardware a čas
import socket
import machine
import time
import json
import gc
from machine import Pin, ADC
import dht
import wlan
import ntptime
import urequests

# ========== KONFIGURACE SYSTÉMU ==========
# Wi-Fi přihlašovací údaje
SSID = "MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM"
PASSWORD = "abcd1234"

# Telegram bot konfigurace pro notifikace
TELEGRAM_BOT_TOKEN = "token"  # Token od @BotFather
TELEGRAM_CHAT_ID = "id"    # ID chatu pro zasílání zpráv

# Nastavení automatického zalévání a čerpadla
SOIL_THRESHOLD = 30000        # RAW hodnota - když je vyšší, spustí se zalévání
PUMP_DURATION_MANUAL = 5      # Doba běhu čerpadla při manuálním zalévání (sekundy)
PUMP_DURATION_AUTO = 3        # Doba běhu čerpadla při automatickém zalévání (sekundy)
AUTO_CHECK_INTERVAL = 30      # Jak často kontrolovat automatické zalévání (sekundy)

# Kalibrace senzoru vlhkosti půdy (pro převod RAW hodnot na procenta)
SOIL_DRY_VALUE = 50000        # RAW hodnota pro úplně suchou půdu (0% vlhkosti)
SOIL_WET_VALUE = 20000        # RAW hodnota pro úplně mokrou půdu (100% vlhkosti)

# Kalibrace senzoru hladiny vody
WATER_EMPTY_VALUE = 0         # RAW hodnota pro prázdnou nádrž
WATER_FULL_VALUE = 40000      # RAW hodnota pro plnou nádrž

# Časové pásmo - Praha (CEST = UTC+2 v létě)
TIMEZONE_OFFSET = 7200        # Offset v sekundách

# Název souboru pro ukládání času posledního zalévání do flash paměti
LAST_WATERING_FILE = "last_watering.txt"

# Nastavení upozornění na nízkou hladinu vody
LOW_WATER_THRESHOLD = 10      # Procenta - pod touto hodnotou se posílá upozornění
ALERT_INTERVAL = 1800         # 30 minut v sekundách - interval mezi upozorněními

# ========== HARDWARE KONFIGURACE ==========
# Inicializace pinů pro senzory a čerpadlo
water_level_pin = ADC(Pin(27))    # Analogový pin pro senzor hladiny vody
soil_moisture_pin = ADC(Pin(26))  # Analogový pin pro senzor vlhkosti půdy
dht_pin = Pin(1)                  # Digitální pin pro teplotní/vlhkostní senzor
relay_pin = Pin(0, Pin.OUT)       # Výstupní pin pro ovládání relé čerpadla

# Inicializace DHT22 senzoru (teplota a vlhkost vzduchu)
dht_sensor = dht.DHT22(dht_pin)

# ========== GLOBÁLNÍ PROMĚNNÉ ==========
pump_running = False          # Stav čerpadla (běží/neběží)
auto_watering = True         # Stav automatického zalévání (zapnuto/vypnuto)
last_watering_time = None    # Čas posledního zalévání
time_synced = False          # Zda je čas synchronizován přes NTP
last_low_water_alert = 0     # Čas posledního upozornění na nízkou hladinu vody

def save_last_watering_time(watering_time):
    """
    Uloží čas posledního zalévání do souboru ve flash paměti
    Args:
        watering_time (str): Čas zalévání ve formátu DD.MM.YYYY HH:MM
    """
    try:
        # Zápis času do souboru ve flash paměti Raspberry Pi Pico
        with open(LAST_WATERING_FILE, "w") as f:
            f.write(watering_time)
        print(f"Last watering time saved to flash: {watering_time}")
    except Exception as e:
        print(f"Failed to save last watering time: {e}")

def load_last_watering_time():
    """
    Načte čas posledního zalévání ze souboru ve flash paměti
    Returns:
        str: Čas posledního zalévání nebo výchozí hodnotu
    """
    try:
        # Čtení času ze souboru ve flash paměti
        with open(LAST_WATERING_FILE, "r") as f:
            saved_time = f.read().strip()
        print(f"Last watering time loaded from flash: {saved_time}")
        return saved_time
    except OSError:
        # Soubor neexistuje - první spuštění systému
        default_time = "Nikdy"
        print("No saved watering time found, using default")
        return default_time
    except Exception as e:
        print(f"Failed to load last watering time: {e}")
        return "Chyba načtení"

def send_telegram_message(message):
    """
    Pošle zprávu přes Telegram bot
    Args:
        message (str): Text zprávy k odeslání
    Returns:
        bool: True pokud se zpráva odeslala úspěšně, False jinak
    """
    # Kontrola, zda je Telegram nakonfigurován
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("Telegram not configured - skipping notification")
        return False
    
    try:
        # Sestavení URL pro Telegram API
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        # Příprava dat pro odeslání (odstranění HTML tagů pro jednoduchost)
        data = {
            "chat_id": str(TELEGRAM_CHAT_ID),  # ID chatu jako string
            "text": message.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "")
        }
        
        print("Sending Telegram notification...")
        print(f"Chat ID: {TELEGRAM_CHAT_ID}")
        
        # Odeslání POST requestu na Telegram API
        response = urequests.post(url, json=data, timeout=10)
        
        # Kontrola odpovědi
        if response.status_code == 200:
            print("✓ Telegram message sent successfully")
            response.close()
            return True
        else:
            print(f"✗ Telegram API error: {response.status_code}")
            try:
                error_text = response.text
                print(f"Error details: {error_text}")
            except:
                pass
            response.close()
            return False
            
    except Exception as e:
        print(f"✗ Telegram notification failed: {e}")
        return False

def notify_startup(ip):
    """
    Pošle notifikaci o spuštění systému s IP adresou
    Args:
        ip (str): IP adresa zařízení
    """
    current_time = get_current_time_str()
    
    # Sestavení zprávy o spuštění
    message = f"""BloomBot spusten!

Cas spusteni: {current_time}
Pristup: http://{ip}"""
    
    success = send_telegram_message(message)
    
    # Pokud Telegram selže, uloží info do souboru jako záloha
    if not success:
        try:
            with open("startup_log.txt", "w") as f:
                f.write(f"IP: {ip}\nTime: {current_time}\n")
            print("Startup info saved to startup_log.txt")
        except:
            pass

def notify_error(error_message):
    """
    Pošle notifikaci o chybě systému
    Args:
        error_message (str): Popis chyby
    """
    current_time = get_current_time_str()
    message = f"""BloomBot - Chyba

Chyba: {error_message}
Cas: {current_time}

Zkontrolujte prosim system."""
    
    send_telegram_message(message)

def notify_low_water(water_level_percent):
    """
    Pošle upozornění na nízkou hladinu vody
    Args:
        water_level_percent (float): Aktuální hladina vody v procentech
    """
    current_time = get_current_time_str()
    message = f"""Upozorneni: Nizka hladina vody!

Aktualni hladina: {water_level_percent:.1f}%
Cas: {current_time}

Doplnte vodu do nadrze."""
    
    send_telegram_message(message)

def check_water_level_alert(water_level_percent):
    """
    Kontroluje hladinu vody a posílá upozornění každých 30 minut pokud je nízká
    Args:
        water_level_percent (float): Aktuální hladina vody v procentech
    """
    global last_low_water_alert
    
    # Kontrola, zda je hladina vody pod prahem
    if water_level_percent < LOW_WATER_THRESHOLD:
        current_time = time.time()
        
        # Kontrola, zda uplynulo alespoň 30 minut od posledního upozornění
        if current_time - last_low_water_alert > ALERT_INTERVAL:
            print(f"Low water alert triggered! Water level: {water_level_percent:.1f}%")
            notify_low_water(water_level_percent)
            last_low_water_alert = current_time

def sync_time():
    """
    Synchronizuje čas se serverem NTP (Network Time Protocol)
    Nastaví globální proměnnou time_synced
    """
    global time_synced
    try:
        print("Synchronizing time with NTP server...")
        ntptime.settime()  # Synchronizace s NTP serverem
        time_synced = True
        print("Time synchronized successfully")
        
        # Výpis času pro kontrolu
        utc_time = time.localtime()
        local_time = time.localtime(time.time() + TIMEZONE_OFFSET)
        print(f"UTC time: {utc_time[2]}.{utc_time[1]}.{utc_time[0]} {utc_time[3]:02d}:{utc_time[4]:02d}")
        print(f"Prague time (CEST): {local_time[2]}.{local_time[1]}.{local_time[0]} {local_time[3]:02d}:{local_time[4]:02d}")
        
    except Exception as e:
        print(f"Failed to sync time: {e}")
        time_synced = False

def get_current_time_str():
    """
    Vrátí aktuální pražský čas ve formátu DD.MM.YYYY HH:MM
    Returns:
        str: Formátovaný čas nebo chybová zpráva
    """
    try:
        if not time_synced:
            return "Time not synced"
        
        # Převod UTC času na pražský čas
        utc_timestamp = time.time()
        prague_timestamp = utc_timestamp + TIMEZONE_OFFSET
        prague_time = time.localtime(prague_timestamp)
        
        return f"{prague_time[2]}.{prague_time[1]}.{prague_time[0]} {prague_time[3]:02d}:{prague_time[4]:02d}"
    except Exception as e:
        print(f"Error getting time: {e}")
        return "Time error"

def calculate_soil_moisture_percent(raw_value):
    """
    Převede RAW hodnotu ze senzoru vlhkosti půdy na procenta
    Args:
        raw_value (int): RAW hodnota ze senzoru (0-65535)
    Returns:
        float: Vlhkost půdy v procentech (0-100)
    """
    if raw_value >= SOIL_DRY_VALUE:
        return 0.0  # Úplně suchá půda
    elif raw_value <= SOIL_WET_VALUE:
        return 100.0  # Úplně mokrá půda
    else:
        # Lineární interpolace mezi suchým a mokrým stavem
        range_total = SOIL_DRY_VALUE - SOIL_WET_VALUE
        range_current = SOIL_DRY_VALUE - raw_value
        return (range_current / range_total) * 100

def calculate_water_level_percent(raw_value):
    """
    Převede RAW hodnotu ze senzoru hladiny vody na procenta
    Args:
        raw_value (int): RAW hodnota ze senzoru (0-65535)
    Returns:
        float: Hladina vody v procentech (0-100)
    """
    if raw_value <= WATER_EMPTY_VALUE:
        return 0.0  # Prázdná nádrž
    elif raw_value >= WATER_FULL_VALUE:
        return 100.0  # Plná nádrž
    else:
        # Lineární interpolace mezi prázdnou a plnou nádrží
        range_total = WATER_FULL_VALUE - WATER_EMPTY_VALUE
        range_current = raw_value - WATER_EMPTY_VALUE
        return (range_current / range_total) * 100

def read_sensors():
    """
    Načte data ze všech senzorů a vrátí je jako slovník
    Returns:
        dict: Slovník s hodnotami ze všech senzorů
    """
    # Čtení teploty a vlhkosti vzduchu z DHT22
    try:
        dht_sensor.measure()
        temperature = dht_sensor.temperature()
        humidity = dht_sensor.humidity()
    except:
        # Pokud čtení selže, nastaví None
        temperature = None
        humidity = None
    
    # Čtení vlhkosti půdy
    soil_moisture_raw = soil_moisture_pin.read_u16()
    soil_moisture_percent = calculate_soil_moisture_percent(soil_moisture_raw)
    
    # Čtení hladiny vody
    water_level_raw = water_level_pin.read_u16()
    water_level_percent = calculate_water_level_percent(water_level_raw)
    
    # Vrácení všech dat jako slovník
    return {
        'temperature': temperature,
        'humidity': humidity,
        'soil_moisture': soil_moisture_percent,
        'soil_moisture_raw': soil_moisture_raw,
        'water_level': water_level_percent,
        'water_level_raw': water_level_raw,
        'pump_running': pump_running,
        'auto_watering': auto_watering,
        'last_watering_time': last_watering_time,
        'time_synced': time_synced
    }

def start_pump(duration):
    """
    Spustí čerpadlo na zadanou dobu
    Args:
        duration (int): Doba běhu čerpadla v sekundách
    """
    global pump_running, last_watering_time
    
    # Nastavení stavu čerpadla
    pump_running = True
    relay_pin.value(1)  # Zapnutí relé (čerpadlo ON)
    
    # Aktualizace času posledního zalévání a uložení do flash paměti
    last_watering_time = get_current_time_str()
    save_last_watering_time(last_watering_time)  # Trvalé uložení do souboru
    
    print(f"Pump started for {duration}s - Last watering time updated: {last_watering_time}")
    
    # Čekání po dobu běhu čerpadla
    time.sleep(duration)
    
    # Vypnutí čerpadla
    relay_pin.value(0)  # Vypnutí relé (čerpadlo OFF)
    pump_running = False
    print("Pump stopped")

def check_auto_watering():
    """
    Kontroluje, zda je potřeba automatické zalévání
    Spustí zalévání pokud je půda příliš suchá
    """
    global auto_watering
    
    # Kontrola, zda je auto režim zapnutý a čerpadlo neběží
    if not auto_watering or pump_running:
        return
    
    # Čtení aktuální vlhkosti půdy
    soil_raw = soil_moisture_pin.read_u16()
    
    # Pokud je půda suchá (vysoká RAW hodnota), spustí zalévání
    if soil_raw > SOIL_THRESHOLD:
        print("Auto watering triggered!")
        start_pump(PUMP_DURATION_AUTO)

def handle_request(request_str):
    """
    Zpracovává HTTP požadavky od klientů (webový prohlížeč)
    Args:
        request_str (str): HTTP požadavek jako string
    Returns:
        bytes: HTTP odpověď
    """
    global auto_watering
    
    try:
        # Obsluha požadavků na obrázky (ikony, SVG soubory)
        if "GET /img/" in request_str:
            # Extrakce názvu souboru z URL
            start = request_str.find("GET /img/") + 9
            end = request_str.find(" ", start)
            filename = request_str[start:end]
            
            try:
                # Načtení souboru z img/ složky
                with open(f"img/{filename}", "rb") as f:
                    image_data = f.read()
                
                # Určení MIME typu podle přípony
                if filename.endswith('.png'):
                    content_type = "image/png"
                elif filename.endswith('.svg'):
                    content_type = "image/svg+xml"
                elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
                    content_type = "image/jpeg"
                else:
                    content_type = "application/octet-stream"
                
                # Sestavení HTTP odpovědi s obrázkem
                response_header = (
                    "HTTP/1.0 200 OK\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(image_data)}\r\n"
                    "Connection: close\r\n\r\n"
                )
                return response_header.encode() + image_data
                
            except:
                # Pokud soubor neexistuje, vrátí 404 chybu
                return (
                    "HTTP/1.0 404 Not Found\r\n"
                    "Content-Type: text/html\r\n"
                    "Connection: close\r\n\r\n"
                    "<html><body><h1>404 - Image not found</h1></body></html>"
                ).encode()
        
        # API endpoint pro získání dat ze senzorů (AJAX volání)
        elif "GET /api/sensors" in request_str:
            sensor_data = read_sensors()  # Načtení aktuálních dat
            response_body = json.dumps(sensor_data)  # Převod na JSON
            return (
                "HTTP/1.0 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Access-Control-Allow-Origin: *\r\n"  # CORS hlavička
                "Connection: close\r\n\r\n"
                + response_body
            ).encode()
        
        # Endpoint pro manuální zalévání
        elif "POST /water" in request_str:
            print("Manual watering from web")
            start_pump(PUMP_DURATION_MANUAL)  # Spuštění čerpadla
            return (
                "HTTP/1.0 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n\r\n"
                "Watering started"
            ).encode()
        
        # Endpoint pro přepnutí automatického zalévání
        elif "POST /toggle_auto" in request_str:
            auto_watering = not auto_watering  # Přepnutí stavu
            print(f"Auto watering: {'ON' if auto_watering else 'OFF'}")
            
            return (
                "HTTP/1.0 200 OK\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n\r\n"
                f"Auto watering: {'on' if auto_watering else 'off'}"
            ).encode()
        
        # Všechny ostatní požadavky - vrátí hlavní HTML stránku
        else:
            response_body = wlan.get_html()  # Načtení HTML z wlan modulu
            return (
                "HTTP/1.0 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Connection: close\r\n\r\n"
                + response_body
            ).encode()
            
    except Exception as e:
        print(f"Request handling error: {e}")
        # Vrácení 500 chyby při problému
        return (
            "HTTP/1.0 500 Internal Server Error\r\n"
            "Content-Type: text/html\r\n"
            "Connection: close\r\n\r\n"
            "<html><body><h1>500 - Server Error</h1></body></html>"
        ).encode()

def main():
    """
    Hlavní funkce programu - spouští webový server a hlavní smyčku
    """
    global last_watering_time
    
    # Optimalizace garbage collection pro lepší správu paměti
    gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
    
    try:
        # Připojení k Wi-Fi síti
        mywlan = wlan.connect_to_wifi(SSID, PASSWORD)
        ip = mywlan.ifconfig()[0]  # Získání IP adresy
        
        # Krátká pauza a synchronizace času
        time.sleep(2)
        sync_time()
        
        # Načtení času posledního zalévání z flash paměti při startu
        last_watering_time = load_last_watering_time()
        print(f"Loaded last watering time: {last_watering_time}")
        
        # Nastavení webového serveru
        addr = socket.getaddrinfo(ip, 80)[0][-1]  # Adresa pro port 80
        s = socket.socket()  # Vytvoření socketu
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Rychlejší uvolnění portu
        s.bind(addr)  # Navázání na adresu
        s.listen(3)  # Naslouchání max. 3 současným připojením
        
        # Výpis informací o spuštění
        print(f"Smart flower pot running on http://{ip}:80/")
        print(f"Free memory: {gc.mem_free()} bytes")
        
        # Odeslání notifikace o spuštění
        notify_startup(ip)
        
        # Inicializace časovačů pro různé úkoly
        last_auto_check = time.time()      # Poslední kontrola auto zalévání
        last_time_sync = time.time()       # Poslední synchronizace času
        last_gc = time.time()              # Poslední garbage collection
        connection_count = 0               # Počítadlo připojení
        
        # Hlavní smyčka serveru
        while True:
            try:
                current_time = time.time()
                
                # Resynchronizace času každých 24 hodin
                if current_time - last_time_sync > 86400:
                    sync_time()
                    last_time_sync = current_time
                
                # Kontrola automatického zalévání každých 30 sekund
                if current_time - last_auto_check > AUTO_CHECK_INTERVAL:
                    check_auto_watering()
                    last_auto_check = current_time
                
                # Kontrola hladiny vody a upozornění (při každém cyklu)
                sensor_data = read_sensors()
                check_water_level_alert(sensor_data['water_level'])
                
                # Garbage collection každé 2 minuty
                if current_time - last_gc > 120:
                    gc.collect()
                    last_gc = current_time
                    # Výpis statistik každých 100 připojení
                    if connection_count % 100 == 0 and connection_count > 0:
                        print(f"Connections: {connection_count}, Free memory: {gc.mem_free()}")
                
                # Nastavení timeoutu pro příchozí připojení
                s.settimeout(0.2)
                
                try:
                    # Přijetí nového připojení
                    cl, addr = s.accept()
                    connection_count += 1
                    
                    # Nastavení timeoutu pro komunikaci s klientem
                    cl.settimeout(2.0)
                    
                    try:
                        # Přijetí HTTP požadavku
                        request = cl.recv(1024)
                        if request:
                            request_str = request.decode("utf-8")
                            # Zpracování požadavku a odeslání odpovědi
                            response = handle_request(request_str)
                            cl.sendall(response)
                    except:
                        pass  # Tichá obsluha chyb komunikace
                    finally:
                        try:
                            cl.close()  # Uzavření spojení
                        except:
                            pass
                    
                except OSError:
                    continue  # Timeout - pokračování ve smyčce
                    
            except Exception as e:
                print(f"Main loop error: {e}")
                notify_error(str(e))  # Odeslání chybové notifikace
                time.sleep(1)
                gc.collect()
                
    except Exception as e:
        print(f"Startup error: {e}")
        time.sleep(5)

# Spuštění hlavní funkce při importu jako main modul
if __name__ == "__main__":
    main()
