# 📊 Chart Trend Analyzer - Standalone Server

## 🚀 Quick Start

### 1. Start the Server

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Start the chart analyzer
python chart_analyzer_server.py
```

### 2. Open Your Browser

Go to: **http://localhost:5000**

### 3. Upload & Analyze!

- Drag & drop any trading chart image
- Click "Analyze Chart"
- See instant results with visualization!

## ✨ What You Get

### Web Interface (Port 5000)
- 🎨 Beautiful drag & drop upload
- 📊 Real-time trend detection
- 📈 Detailed visualizations showing:
  - Original chart
  - Extracted line points
  - Analysis segment (last 15%)
  - Trend line with slope
  - Step-by-step explanation

### API Endpoints

**Analyze Chart:**
```
POST http://localhost:5000/api/analyze
```

**Health Check:**
```
GET http://localhost:5000/health
```

**Info:**
```
GET http://localhost:5000/api/info
```

## 📝 Example API Usage

```python
import requests

url = "http://localhost:5000/api/analyze"
files = {"file": open("chart.png", "rb")}
response = requests.post(url, files=files)
result = response.json()

print(f"Trend: {result['trend']}")
print(f"Slope: {result['slope']}")
```

## 🎯 Features

✅ **Standalone** - Runs on its own (port 5000)  
✅ **Separate from main app** - Won't interfere with your trading app  
✅ **Drag & drop** - Easy image upload  
✅ **Real-time** - Instant analysis  
✅ **Visualizations** - See how detection works  
✅ **API access** - Use programmatically  

## 🔧 How It Works

1. Extracts chart line from image
2. Normalizes to 0-100 scale
3. Analyzes last 15% of points
4. Fits linear regression
5. Determines trend:
   - **UP** ↗ if slope > 0.15
   - **DOWN** ↘ if slope < -0.15
   - **FLAT** → otherwise

## 📁 Files

- `chart_analyzer_server.py` - Standalone server
- `chart_analyzer.html` - Web interface
- `chart_visualizer.py` - Visualization engine
- `chart_line_detector.py` - Detection algorithm

## 🎨 Command Line

Create visualizations directly:

```powershell
python chart_visualizer.py chart.png output.png
```

## ⚡ Notes

- Runs on **port 5000** (separate from main app on port 8000)
- Completely independent
- Can run alongside your trading app
- No database needed
- Lightweight and fast

## 🎉 That's It!

Your standalone chart analyzer is ready to use!

**Start it now:** `python chart_analyzer_server.py`  
**Then visit:** http://localhost:5000
