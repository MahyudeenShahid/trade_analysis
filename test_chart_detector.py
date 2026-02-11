"""
Test script to debug and visualize chart line detection
"""
import cv2
import numpy as np
import matplotlib.pyplot as plt
from chart_line_detector import ChartLineDetector

def test_with_visualization(image_path):
    """Test detector and show detailed visualization"""
    detector = ChartLineDetector()
    
    # Get detailed analysis
    result = detector.analyze_with_details(image_path)
    
    if not result['success']:
        print(f"Error: {result.get('error', 'Unknown error')}")
        return
    
    # Print results
    print(f"\n{'='*60}")
    print(f"Trend Detection Results")
    print(f"{'='*60}")
    print(f"Detected Trend: {result['trend'].upper()}")
    print(f"Slope: {result['slope']:.4f}")
    print(f"Turning Point Index: {result['flip_index']}")
    print(f"Total Points: {len(result['points'])}")
    print(f"Points after turning: {len(result['segment'])}")
    
    # Visualize
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    
    # Original image
    img = cv2.imread(image_path)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    axes[0, 0].imshow(img_rgb)
    axes[0, 0].set_title('Original Chart Image')
    axes[0, 0].axis('off')
    
    # Extracted and normalized points
    points = result['points']
    axes[0, 1].plot(points[:, 0], points[:, 1], 'b-', linewidth=2, label='Full Line')
    axes[0, 1].scatter(points[:, 0], points[:, 1], c='blue', s=20, alpha=0.5)
    axes[0, 1].set_title('Normalized Points (larger y = higher price)')
    axes[0, 1].set_xlabel('X (time →)')
    axes[0, 1].set_ylabel('Y (price ↑)')
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].legend()
    
    # Turning point and final segment
    flip_idx = result['flip_index']
    segment = result['segment']
    
    axes[1, 0].plot(points[:, 0], points[:, 1], 'gray', linewidth=1, alpha=0.5, label='Earlier Points')
    axes[1, 0].plot(segment[:, 0], segment[:, 1], 'r-', linewidth=3, label='Last Segment (Analyzed)')
    axes[1, 0].scatter([points[flip_idx, 0]], [points[flip_idx, 1]], 
                       c='green', s=200, marker='o', zorder=5, label='Start of Last Segment')
    axes[1, 0].scatter([segment[-1, 0]], [segment[-1, 1]], 
                       c='red', s=200, marker='*', zorder=5, label='Current Position (End)')
    axes[1, 0].set_title(f'Current Trend Detection\n(Analyzing last {len(segment)} points)')
    axes[1, 0].set_xlabel('X (time →)')
    axes[1, 0].set_ylabel('Y (price ↑)')
    axes[1, 0].grid(True, alpha=0.3)
    axes[1, 0].legend()
    
    # Trend line with slope
    if len(segment) >= 2:
        slope, intercept = np.polyfit(segment[:, 0], segment[:, 1], 1)
        trend_line_x = segment[:, 0]
        trend_line_y = slope * trend_line_x + intercept
        
        axes[1, 1].plot(segment[:, 0], segment[:, 1], 'ro-', linewidth=2, markersize=4, label='Actual Points')
        axes[1, 1].plot(trend_line_x, trend_line_y, 'g--', linewidth=3, label=f'Trend Line (slope={slope:.3f})')
        
        # Show direction with arrow
        start_y = trend_line_y[0]
        end_y = trend_line_y[-1]
        direction_text = "↗ UPWARD" if slope > 0.15 else "↘ DOWNWARD" if slope < -0.15 else "→ FLAT"
        color = "green" if slope > 0.15 else "red" if slope < -0.15 else "gray"
        
        axes[1, 1].set_title(f'Trend at Current Moment\n{direction_text}', fontsize=12, weight='bold', color=color)
        axes[1, 1].set_xlabel('X (time →)')
        axes[1, 1].set_ylabel('Y (price ↑)')
        axes[1, 1].grid(True, alpha=0.3)
        axes[1, 1].legend()
        
        # Add text annotations
        axes[1, 1].text(0.05, 0.95, 
                       f'Slope: {slope:.3f}\n' +
                       f'Start Y: {segment[0, 1]:.2f}\n' +
                       f'End Y: {segment[-1, 1]:.2f}\n' +
                       f'Change: {segment[-1, 1] - segment[0, 1]:.2f}',
                       transform=axes[1, 1].transAxes, fontsize=10,
                       verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    plt.savefig('chart_analysis_debug.png', dpi=150, bbox_inches='tight')
    print(f"\nVisualization saved to: chart_analysis_debug.png")
    plt.show()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        # Use default test image
        print("Usage: python test_chart_detector.py <image_path>")
        print("\nTrying default locations...")
        
        import os
        possible_paths = [
            "./chart.png",
            "./test_chart.png", 
            "./charts/chart.png",
            # Add your image path here
        ]
        
        image_path = None
        for path in possible_paths:
            if os.path.exists(path):
                image_path = path
                break
        
        if not image_path:
            print("No image found. Please provide image path as argument.")
            sys.exit(1)
    
    print(f"Testing with image: {image_path}")
    test_with_visualization(image_path)
