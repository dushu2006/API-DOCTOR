import time
import requests
import sys

BASE = "http://localhost:8000"

def wait_for_health(timeout=60):
    for i in range(timeout):
        try:
            r = requests.get(f"{BASE}/health", timeout=1)
            if r.status_code == 200:
                print("health: OK")
                return True
        except Exception as e:
            pass
        print(f"waiting for health... ({i+1}/{timeout})")
        time.sleep(1)
    print("health check timed out")
    return False

def trigger_incident():
    r = requests.post(f"{BASE}/api/incidents/trigger/null_pointer")
    print("trigger response:", r.status_code)
    try:
        print(r.json())
    except Exception:
        print(r.text)
    return r.json().get("incident_id") if r.status_code == 200 else None

def poll_status(incident_id, timeout=60):
    for i in range(timeout):
        try:
            r = requests.get(f"{BASE}/api/incidents/{incident_id}/status", timeout=3)
            print(f"status ({i+1}/{timeout}):", r.status_code, r.text)
            try:
                js = r.json()
            except Exception:
                js = {}
            if js.get("status") == "FIX_VERIFIED":
                print("Fix verified")
                return True
        except Exception as e:
            print("status check error", e)
        time.sleep(2)
    return False

def show_artifacts(incident_id):
    try:
        d = requests.get(f"{BASE}/api/incidents/{incident_id}/diff", timeout=5)
        print("--- DIFF ---")
        print(d.text)
    except Exception as e:
        print("diff error", e)
    try:
        s = requests.get(f"{BASE}/api/incidents/{incident_id}/sandbox", timeout=5)
        print("--- SANDBOX ---")
        print(s.text)
    except Exception as e:
        print("sandbox error", e)

def main():
    if not wait_for_health():
        sys.exit(2)
    incident_id = trigger_incident()
    if not incident_id:
        sys.exit(3)
    poll_status(incident_id)
    show_artifacts(incident_id)

if __name__ == "__main__":
    main()
