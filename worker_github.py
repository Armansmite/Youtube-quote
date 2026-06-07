import os, requests, json

DASHBOARD_URL = os.environ["DASHBOARD_URL"].rstrip("/") + "/"

def send_log(msg):
    print(msg)
    try:
        requests.post(DASHBOARD_URL + "api/log", json={"message": msg}, timeout=5)
    except:
        pass

send_log("🚀 Worker started successfully!")
