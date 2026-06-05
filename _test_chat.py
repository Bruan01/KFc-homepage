import os, sys, time, json, urllib.request, http.cookiejar, threading

os.environ['PORT'] = '5615'
sys.path.insert(0, '.')

# Start server in background
t = threading.Thread(target=lambda: __import__('app.server').server.run_server(), daemon=True)
t.start()
time.sleep(3)

# Login
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
req = urllib.request.Request('http://127.0.0.1:5615/api/admin/login',
    data=json.dumps({'username':'admin','password':'admin123'}).encode(),
    headers={'Content-Type':'application/json'})
op.open(req)

# Test chat message send
body = {
    "messages": [
        {"role": "user", "content": "hello test"}
    ],
    "model": "agnes-2.0-flash",
    "stream": True,
    "session_id": None  # new session
}
req2 = urllib.request.Request('http://127.0.0.1:5615/api/agnes/chat',
    data=json.dumps(body).encode(),
    headers={'Content-Type':'application/json'})
try:
    resp = op.open(req2)
    data = json.loads(resp.read())
    print(f'Status: {resp.status}')
    print(f'Response id: {data.get("id")}')
    print(f'Messages: {len(data.get("messages", []))}')
    print('OK')
except urllib.request.HTTPError as e:
    print(f'HTTP Error: {e.code}')
    print(e.read().decode()[:500])
except Exception as e:
    print(f'Error: {e}')
"