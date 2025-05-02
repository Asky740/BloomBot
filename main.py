import network
import socket
from machine import Pin, ADC
import dht
import time
import ujson

# Hardware setup
dht_sensor = dht.DHT22(Pin(15))
soil_moisture = ADC(Pin(26))
relay = Pin(16, Pin.OUT)
history = []

# Wi-Fi connection
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect("SKYWLAN", "P3tr4wl4n.")

def get_sensor_data():
    dht_sensor.measure()
    soil = 100 - (soil_moisture.read_u16() / 65535 * 100)
    return {
        'temp': dht_sensor.temperature(),
        'hum': dht_sensor.humidity(),
        'soil': round(soil, 1)
    }

def generate_chart_url(data):
    chart_data = {
        'type': 'line',
        'data': {
            'labels': ['-3h', '-2h', '-1h', 'Nyní'],
            'datasets': [{
                'label': 'Vlhkost půdy',
                'data': [data-10, data-5, data+2, data],
                'borderColor': '#006A6A'
            }]
        }
    }
    return f'https://quickchart.io/chart?c={ujson.dumps(chart_data)}'

def handle_request(client):
    request = client.recv(1024).decode()
    data = get_sensor_data()
    history.append(data['soil'])
    
    # Automatické zalévání
    if data['soil'] < 30:
        control_pump(2)

    # Routing
    if 'GET / ' in request:
        with open('templates/index.html') as f:
            html = f.read()
            html = html.replace('{temp}', str(data['temp']))
            html = html.replace('{hum}', str(data['hum']))
            html = html.replace('{soil}', str(data['soil']))
            html = html.replace('{chart}', generate_chart_url(data['soil']))
            send_response(client, html, 'text/html')
    
    elif 'GET /style.css' in request:
        with open('style.css') as f:
            send_response(client, f.read(), 'text/css')
    
    elif 'GET /script.js' in request:
        with open('script.js') as f:
            send_response(client, f.read(), 'text/javascript')
    
    elif '/water' in request:
        control_pump(2)
        client.send('HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n')
    
    client.close()

def control_pump(duration):
    relay.on()
    time.sleep(duration)
    relay.off()

def send_response(client, content, content_type):
    client.send(f'HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\n\r\n')
    client.send(content)

# Start server
server = socket.socket()
server.bind(('0.0.0.0', 80))
server.listen(5)

while True:
    client, addr = server.accept()
    try:
        handle_request(client)
    except Exception as e:
        client.close()
