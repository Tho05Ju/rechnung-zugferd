import threading, time, urllib.request
import webview
from app import app

PORT = 5001

def serve():
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)

threading.Thread(target=serve, daemon=True).start()
for _ in range(50):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1); break
    except Exception:
        time.sleep(0.2)
webview.settings["ALLOW_DOWNLOADS"] = True  # PDF-/DATEV-Downloads mit Speichern-Dialog
webview.create_window("Rechnung", f"http://127.0.0.1:{PORT}/", width=1200, height=850)
webview.start()
