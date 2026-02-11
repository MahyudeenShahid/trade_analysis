# Chart Trend Analyzer - Web GUI

## What's This?

A beautiful web interface to upload trading chart images and get instant trend analysis with detailed visualizations showing exactly how the detection algorithm works.

## Features

✨ **Drag & Drop Upload** - Easy image upload interface  
📊 **Real-time Analysis** - Instant trend detection (UP/DOWN/FLAT)  
📈 **Visual Breakdown** - See step-by-step how the detector analyzes your chart  
🎯 **Detailed Metrics** - Slope, data points, segment analysis  
🖼️ **Comprehensive Visualization** - 5-panel analysis view showing:
- Original chart image
- Extracted and normalized line
- Analysis segment highlighting
- Trend line with slope
- Step-by-step detection process explanation

## Quick Start

### 1. Start the Server

Make sure your FastAPI server is running:

```bash
# Activate virtual environment
.venv\Scripts\Activate.ps1

# Start the server
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Open the Web Interface

Open your browser and go to:

```
http://localhost:8000/chart_analyzer.html
```

Or just open the `chart_analyzer.html` file directly in your browser!

### 3. Upload and Analyze

1. **Drag & drop** a chart image into the upload zone, or click to browse
2. Click the **"Analyze Chart"** button
3. View the results instantly with full visualization

## API Endpoint

You can also use the API directly:

```bash
POST http://localhost:8000/api/chart/analyze

# Example using curl:
curl -X POST "http://localhost:8000/api/chart/analyze" \
  -F "file=@mychartimage.png" \
  -F "return_visualization=true"
```

**Response:**
```json
{
  "success": true,
  "trend": "up",
  "slope": 0.2453,
  "points_count": 145,
  "segment_size": 22,
  "visualization_base64": "iVBORw0KGgoAAAANS..."
}
```

## Command Line Tool

You can also create visualizations from the command line:

```bash
# Create visualization and save to file
python chart_visualizer.py chart.png output.png

# Just specify input (saves as chart_visualization.png)
python chart_visualizer.py chart.png
```

## How It Works

The visualizer shows:

1. **Original Image** - Your uploaded chart
2. **Normalized Line** - Extracted coordinate points (0-100 scale)
3. **Analysis Region** - Highlights the last 15% segment being analyzed
4. **Trend Line** - Linear regression fit with direction arrow
5. **Detection Steps** - Detailed explanation of the algorithm

The trend is determined by:
- Taking the **last 15%** of chart points (most recent data)
- Applying **light smoothing** to reduce noise
- Fitting a **linear regression line**
- Checking if slope is:
  - **> 0.15** → UP ↗
  - **< -0.15** → DOWN ↘
  - Otherwise → FLAT →

## Supported Images

✅ PNG, JPG, JPEG formats  
✅ Trading charts (Robinhood, TradingView, etc.)  
✅ Line charts with visible trends  
✅ Any image size (automatically scaled)  
✅ Light or dark backgrounds  

## Troubleshooting

**"Analysis failed" error:**
- Make sure the image contains a visible line chart
- Try adjusting the chart line color/thickness
- Check that the chart line is prominent in the image

**Slow performance:**
- Large images may take a few seconds
- The visualization rendering is computation-intensive
- Consider using smaller image sizes for faster results

**Wrong trend detection:**
- The algorithm analyzes the last 15% of the chart
- Make sure this region clearly shows the trend
- Extremely noisy charts may need preprocessing

## Examples

Upload any of these chart types:
- 📈 Stock price charts
- 💰 Cryptocurrency charts
- 📊 Forex charts
- 📉 Index charts
- 🎯 Any line-based trading charts

## Files

- `chart_visualizer.py` - Visualization generator
- `chart_analyzer.html` - Web interface
- `api/routes/chart_analysis.py` - API endpoint
- `chart_line_detector.py` - Core detection algorithm

Enjoy analyzing your charts! 🚀
