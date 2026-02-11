"""
Chart Analyzer - Standalone Server

A lightweight web server specifically for chart trend analysis and visualization.
Run this separately from the main trading application.

Usage:
    python chart_analyzer_server.py

Then open: http://localhost:5000
"""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import tempfile
import shutil
import uvicorn

from chart_visualizer import ChartVisualizer
from chart_line_detector import ChartLineDetector

# Create FastAPI app
app = FastAPI(
    title="Chart Trend Analyzer",
    description="Upload trading charts and get instant trend analysis with visualization",
    version="1.0.0"
)

# Add CORS middleware for browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize visualizer
visualizer = ChartVisualizer()
detector = ChartLineDetector()


@app.get("/", response_class=HTMLResponse)
async def serve_home():
    """Serve the chart analyzer web interface."""
    html_path = os.path.join(os.path.dirname(__file__), "chart_analyzer.html")
    
    if not os.path.exists(html_path):
        return HTMLResponse(
            content="<h1>Error: chart_analyzer.html not found</h1>",
            status_code=404
        )
    
    with open(html_path, 'r', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())


@app.post("/api/analyze")
async def analyze_chart(
    file: UploadFile = File(...),
    return_visualization: bool = True
):
    """
    Upload a chart image and get trend analysis with visualization.
    
    Args:
        file: The chart image file (PNG, JPG, JPEG)
        return_visualization: If True, returns base64 encoded visualization
        
    Returns:
        JSON with trend, slope, visualization (base64), and other details
    """
    # Validate file type
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    tmp_path = None
    
    try:
        # Create temp file
        suffix = os.path.splitext(file.filename)[1] or '.png'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_path = tmp_file.name
            # Copy uploaded content
            shutil.copyfileobj(file.file, tmp_file)
        
        # Analyze the chart
        if return_visualization:
            result = visualizer.create_base64_visualization(tmp_path)
        else:
            # Just get trend without full visualization
            trend = detector(tmp_path)
            analysis = detector.analyze_with_details(tmp_path)
            
            result = {
                'success': analysis['success'],
                'trend': trend,
                'slope': analysis.get('slope', 0),
                'points_count': len(analysis.get('points', [])),
                'segment_size': len(analysis.get('segment', []))
            }
        
        if not result['success']:
            raise HTTPException(status_code=422, detail=result.get('error', 'Analysis failed'))
        
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
    finally:
        # Clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass
        await file.close()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "chart_analyzer",
        "version": "1.0.0"
    }


@app.get("/api/info")
async def get_info():
    """Get information about the analyzer."""
    return {
        "name": "Chart Trend Analyzer",
        "version": "1.0.0",
        "algorithm": "Endpoint trend detection with linear regression",
        "lookback_percent": 15,
        "slope_threshold": 0.15,
        "supported_formats": ["PNG", "JPG", "JPEG"],
        "trends": {
            "up": "Upward trend (slope > 0.15)",
            "down": "Downward trend (slope < -0.15)",
            "none": "Flat/Sideways (slope between -0.15 and 0.15)"
        }
    }


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 Starting Chart Trend Analyzer Server")
    print("=" * 70)
    print("\n📊 Chart Analyzer is ready!")
    print(f"\n🌐 Web Interface: http://localhost:5000")
    print(f"🔌 API Endpoint:  http://localhost:5000/api/analyze")
    print(f"💚 Health Check:  http://localhost:5000/health")
    print(f"\n📝 Features:")
    print("   • Drag & drop image upload")
    print("   • Real-time trend detection")
    print("   • Detailed visualizations")
    print("   • UP/DOWN/FLAT trend classification")
    print("\n🎯 Upload a trading chart image to get started!")
    print("=" * 70)
    print()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        log_level="info"
    )
