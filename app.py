#!/usr/bin/env python3
"""
Простой веб-сервер для FPV интерфейса
Только прокси видео и отдача статичных файлов
"""

from flask import Flask, render_template, Response
import requests

app = Flask(__name__)

# URL видеопотока
ENCODER_URL = "http://192.168.1.106/isabella"

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/live')
def live_stream():
    """Прокси для видеопотока"""
    def generate():
        try:
            r = requests.get(ENCODER_URL, stream=True, timeout=5)
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk
        except Exception as e:
            print(f"[ERROR] Ошибка видеопотока: {e}")
            yield b""

    return Response(generate(),
                   mimetype='video/mp2t',
                   headers={'Cache-Control': 'no-cache'})

if __name__ == '__main__':
    print("Запуск веб-сервера FPV Interface...")
    print(f"Видеопоток: {ENCODER_URL}")
    print("Веб-интерфейс: http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)