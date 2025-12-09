.

## Manual setup (for developers)
From a PowerShell prompt in the project root:


```powershell
git pull

python -m venv .venv
& .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

python -m uvicorn backend_server:app --host 0.0.0.0 --port 8000 --reload

```

---

## ngrok browser warning (how to bypass)

If you use a free ngrok tunnel, new visitors will see a browser warning/interstitial page. This is normal for free tunnels.

- **For API/frontend requests:** Add the header `ngrok-skip-browser-warning: true` to every request. Most frontend frameworks (fetch, axios) allow custom headers.
	- Example (fetch):
		```js
		fetch('https://<your-ngrok-url>/history?ticker=AAPL', {
			headers: {
				'ngrok-skip-browser-warning': 'true',
				'Authorization': 'Bearer <API_KEY>'
			}
		})
		```
	- Example (curl):
		```powershell
		curl -H "ngrok-skip-browser-warning: true" https://electrotropic-uselessly-lashawna.ngrok-free.dev/history?ticker=AAPL
		```

- **For browsers:** The first time you visit the ngrok URL, click "Visit Site" on the warning page. After that, you will be redirected to your backend and the warning will not appear again for a while.

- **For production/no warning:** Upgrade to a paid ngrok account or use cloudflared (Cloudflare Tunnel) to remove the warning for all visitors.

---


---

Developed by [Mahyudeen Shahid](https://mahyudeen.me/) with ❤