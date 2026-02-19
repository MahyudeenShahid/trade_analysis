"""
Web Interface for Chart Line Extraction

A simple Flask web application that allows users to upload chart images
and receive trend analysis with visualizations.
"""

from flask import Flask, render_template_string, request
import os
import io
import base64
from PIL import Image

from chart_line_detector import ChartLineDetector

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# HTML Templates
UPLOAD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Chart Line Analyzer</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            margin-bottom: 30px;
            text-align:center;
        }
        .upload-form {
            margin-top: 20px;
        }
        input[type="file"] {
            padding: 10px;
            margin-bottom: 20px;
            border: 2px dashed #ddd;
            border-radius: 4px;
            width: 100%;
        }
        button {
            background-color: #007bff;
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            display:block;
            margin:auto;
        }
        button:hover {
            background-color: #0056b3;
        }
        .info {
            margin-top: 20px;
            padding: 15px;
            background-color: #e7f3ff;
            border-left: 4px solid #007bff;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Chart Line Analyzer</h1>
        <p style="text-align:center;">Upload a chart screenshot to analyze trend direction.</p>
        
        <form method="POST" enctype="multipart/form-data" class="upload-form">
            <input type="file" name="file" accept="image/*" required>
            <button type="submit">Analyze Chart</button>
        </form>
        
        <div class="info">
            <strong>Supported formats:</strong> PNG, JPG, JPEG, BMP<br>
            <strong>Note:</strong> Works best with line charts on clean backgrounds.
        </div>
    </div>
</body>
</html>
"""

RESULT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Analysis Results</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 1000px;
            margin: 50px auto;
            padding: 20px;
            background-color: #f5f5f5;
            text-align:center;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
        }
        h1 {
            color: #333;
            margin-bottom: 25px;
        }
        .result-box {
            padding: 20px;
            margin: 20px auto;
            border-radius: 6px;
            font-size: 20px;
            font-weight: bold;
            width: 70%;
        }
        .up {
            background-color: #d4edda;
            border-left: 5px solid #28a745;
            color: #155724;
        }
        .down {
            background-color: #f8d7da;
            border-left: 5px solid #dc3545;
            color: #721c24;
        }
        .none {
            background-color: #fff3cd;
            border-left: 5px solid #ffc107;
            color: #856404;
        }
        img {
            max-width: 85%;
            border-radius: 8px;
            margin: 20px auto;
            display:block;
        }
        .meta {
            color: #666;
            font-size: 15px;
            margin-bottom: 15px;
        }
        a {
            display: inline-block;
            margin-top: 25px;
            padding: 12px 24px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-size: 16px;
        }
        a:hover {
            background-color: #0056b3;
        }
    </style>
</head>
<body>
    <div class="container">

        <h1>📈 Trend Analysis Result</h1>

        <div class="meta">
            <strong>File:</strong> {{ filename }}
        </div>

        <div class="result-box {{ result_class }}">
            {{ result_text }}
        </div>

        <img src="data:image/png;base64,{{ img_data }}" alt="Uploaded Chart">

        <a href="/">← Analyze Another Chart</a>
    </div>
</body>
</html>
"""

ERROR_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Error</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .error {
            color: #dc3545;
            padding: 20px;
            background-color: #f8d7da;
            border-left: 4px solid #dc3545;
            border-radius: 4px;
            margin: 20px 0;
        }
        a {
            display: inline-block;
            margin-top: 20px;
            padding: 10px 20px;
            background-color: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }
        a:hover {
            background-color: #0056b3;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚠️ Error</h1>
        <div class="error">
            {{ error_message }}
        </div>
        <a href="/">← Try Again</a>
    </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def upload_file():
    """Handle file upload and chart analysis."""
    if request.method == "POST":
        if 'file' not in request.files:
            return render_template_string(ERROR_TEMPLATE, error_message="No file uploaded.")

        file = request.files["file"]
        
        if not file or file.filename == '':
            return render_template_string(ERROR_TEMPLATE, error_message="No file selected.")

        if not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            return render_template_string(ERROR_TEMPLATE, error_message="Invalid file format.")

        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(filepath)
        
        try:
            detector = ChartLineDetector()
            trend_direction = detector(filepath)

            if trend_direction == "UP":
                result_text = "Trend: UP after last direction change"
                result_class = "up"
            elif trend_direction == "DOWN":
                result_text = "Trend: DOWN after last direction change"
                result_class = "down"
            else:
                result_text = "No direction change detected in the chart"
                result_class = "none"

            with Image.open(filepath) as img:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                img_data = base64.b64encode(buf.getvalue()).decode("utf-8")

            os.remove(filepath)

            return render_template_string(
                RESULT_TEMPLATE,
                filename=file.filename,
                result_text=result_text,
                result_class=result_class,
                img_data=img_data
            )

        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            return render_template_string(ERROR_TEMPLATE, error_message=f"Processing error: {str(e)}")

    return render_template_string(UPLOAD_TEMPLATE)

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Chart Line Analyzer - Web Interface")
    print("="*60)
    print("\nServer starting...")
    print("Open your browser and go to: http://localhost:5000")
    print("\nPress Ctrl+C to stop the server")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
