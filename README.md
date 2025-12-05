.

## Manual setup (for developers)
From a PowerShell prompt in the project root:

```powershell
python -m venv .venv

& .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip

pip install -r requirements.txt

python -m uvicorn backend_server:app --host 0.0.0.0 --port 8000 --reload
```


---

Developed by [Mahyudeen Shahid](https://mahyudeen.me/) with ❤