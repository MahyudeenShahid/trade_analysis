# Chart Trend Detection Algorithm

## Simple Endpoint Trend Detection

### What We're Detecting

**The trend direction AT THE CURRENT MOMENT** (the very last point on the chart)

Think of it like this:
- 🔴 Where is the chart heading RIGHT NOW?
- 🔴 At this exact moment, is the price going up or down?

### Algorithm (Ultra Simple)

1. **Take the Last Segment**
   - Use the last 15% of the chart points
   - This represents the most recent price movement

2. **Fit a Line Through It**
   - Use linear regression on this last segment
   - This gives us the trend line slope

3. **Check the Slope**
   - **Positive slope** → Price is rising → **UP** ↗
   - **Negative slope** → Price is falling → **DOWN** ↘
   - **Near-zero slope** → Price is flat → **FLAT** →

### Visual Example

```
Earlier points          Last segment (analyzed)
    ▼                        ▼
────────────────────────────↗  ← Going UP (positive slope)

────────────────────────────↘  ← Going DOWN (negative slope)
```

### Why This Works

1. ✅ **Simple** - Just look at the endpoint direction
2. ✅ **Fast** - Only analyze last 15% of points
3. ✅ **Accurate** - Matches what the red line shows in your images
4. ✅ **Intuitive** - "Where is it going NOW?"

### Key Parameters

- **Lookback**: 15% of chart (can be adjusted)
- **Smoothing**: Light (sigma=1.0) to reduce noise
- **Slope threshold**: 0.15 (to ignore tiny movements)

### Examples from Your Images

**Image 1 (Going UP):**
```
Chart ends with: ────────↗
Last segment slope: Positive
Detection: UP ✓
```

**Image 2 (Going DOWN):**
```
Chart ends with: ────────↘  
Last segment slope: Negative
Detection: DOWN ✓
```

### Coordinate System

After normalization:
- **X-axis**: 0-100 (time, left to right)
- **Y-axis**: 0-100 (price, bottom to top)
- **Larger Y = Higher Price**

In image coordinates (top-left origin), we flip Y during normalization:
```python
normalized[:, 1] = (y_max - pts[:, 1]) / dy * (height - 1)
```

### Testing

Visualize what the detector sees:
```bash
python test_chart_detector.py your_chart.png
```

This shows:
- The full chart
- The last segment being analyzed (in red)
- The trend line with slope
- Current direction (UP/DOWN)
