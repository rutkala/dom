#!/usr/bin/env python3
"""Lokalny serwer podgladu 3D z mechanizmem Live-Reload.

Automatycznie serwuje podglad 3D i informuje przegladarke o zmianach w plikach modelu.
"""
from __future__ import annotations
import http.server
import io
import json
import os
import socketserver
import subprocess
import sys
import webbrowser
from pathlib import Path

# Bezpieczne kodowanie wyjscia na Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
PORT = 8765
WATCHED_FILES = [
    ROOT / 'index.html',
    ROOT / 'podglad_3d.html',
    ROOT / 'scena_modelu.json',
    ROOT / 'dane_zrodlowe.json',
    ROOT / 'parametry_modelu.json'
]

def get_latest_mtime() -> float:
    mtimes = []
    for f in WATCHED_FILES:
        if f.is_file():
            try:
                mtimes.append(f.stat().st_mtime)
            except OSError:
                pass
    return max(mtimes) if mtimes else 0.0

class LiveHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path in ('/api/version', '/api/version/'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.end_headers()
            data = json.dumps({'version': get_latest_mtime()})
            self.wfile.write(data.encode('utf-8'))
            return
        elif self.path in ('/', ''):
            self.path = '/index.html'
        return super().do_GET()

    def log_message(self, format, *args):
        if len(args) > 0 and 'api/version' in str(args[0]):
            return
        super().log_message(format, *args)

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

def open_in_browser(url: str):
    try:
        if subprocess.run(['termux-open-url', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
    except Exception:
        pass
    try:
        if subprocess.run(['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
    except Exception:
        pass
    try:
        webbrowser.open(url)
    except Exception:
        pass

def main():
    port = PORT
    httpd = None
    for p in range(PORT, PORT + 20):
        try:
            httpd = ReusableTCPServer(('0.0.0.0', p), LiveHandler)
            port = p
            break
        except OSError:
            try:
                httpd = ReusableTCPServer(('127.0.0.1', p), LiveHandler)
                port = p
                break
            except OSError:
                continue
    if not httpd:
        print("Nie znaleziono wolnego portu.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}/index.html"
    print(f"Serwer Live Podgladu uruchomiony pod adresem: {url}")
    print(f"Dostęp lokalny: http://localhost:{port}/index.html")
    print("Otwieranie przegladarki...")
    open_in_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZatrzymano serwer.")

if __name__ == '__main__':
    main()
