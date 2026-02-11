"""
Chart Line Detection Visualizer

Creates detailed visualizations showing how the line detector processes images.
"""

import cv2
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for web
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import io
import base64
from PIL import Image
from chart_line_detector import ChartLineDetector


class ChartVisualizer:
    """Visualize the chart line detection process step by step."""
    
    def __init__(self, detector=None):
        """
        Initialize the visualizer.
        
        Args:
            detector: ChartLineDetector instance, or None to create default
        """
        self.detector = detector if detector else ChartLineDetector()
    
    def create_visualization(self, image_path, output_path=None):
        """
        Create a comprehensive visualization of the detection process.
        
        Args:
            image_path: Path to the chart image
            output_path: Optional path to save the visualization
            
        Returns:
            Dict with visualization_path, trend, slope, and other details
        """
        # Get detailed analysis
        result = self.detector.analyze_with_details(image_path)
        
        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'Unknown error'),
                'trend': 'none'
            }
        
        # Create the visualization
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
        
        # 1. Original Image
        ax1 = fig.add_subplot(gs[0, :])
        img = cv2.imread(image_path)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ax1.imshow(img_rgb)
        ax1.set_title('Original Chart Image', fontsize=14, weight='bold')
        ax1.axis('off')
        
        # 2. Extracted Line Points
        ax2 = fig.add_subplot(gs[1, 0])
        points = result['points']
        ax2.plot(points[:, 0], points[:, 1], 'b-', linewidth=2, alpha=0.7)
        ax2.scatter(points[:, 0], points[:, 1], c='blue', s=10, alpha=0.3)
        ax2.set_title('Normalized Chart Line', fontsize=12)
        ax2.set_xlabel('X (Time →)')
        ax2.set_ylabel('Y (Price ↑)')
        ax2.grid(True, alpha=0.3)
        ax2.set_xlim(-5, 105)
        ax2.set_ylim(-5, 105)
        
        # 3. Analysis Segment Highlighted
        ax3 = fig.add_subplot(gs[1, 1])
        flip_idx = result['flip_index']
        segment = result['segment']
        
        ax3.plot(points[:, 0], points[:, 1], 'gray', linewidth=1, alpha=0.3, label='Full Chart')
        ax3.plot(segment[:, 0], segment[:, 1], 'r-', linewidth=3, label=f'Analyzed Segment ({len(segment)} pts)')
        ax3.scatter([points[flip_idx, 0]], [points[flip_idx, 1]], 
                   c='green', s=150, marker='o', zorder=5, edgecolors='black', linewidths=2,
                   label='Segment Start')
        ax3.scatter([segment[-1, 0]], [segment[-1, 1]], 
                   c='red', s=200, marker='*', zorder=5, edgecolors='black', linewidths=2,
                   label='Current Position')
        ax3.set_title('Trend Detection Region', fontsize=12)
        ax3.set_xlabel('X (Time →)')
        ax3.set_ylabel('Y (Price ↑)')
        ax3.grid(True, alpha=0.3)
        ax3.legend(loc='best', fontsize=8)
        ax3.set_xlim(-5, 105)
        ax3.set_ylim(-5, 105)
        
        # 4. Trend Line with Slope
        ax4 = fig.add_subplot(gs[1, 2])
        slope = result['slope']
        
        if len(segment) >= 2:
            from scipy.ndimage import gaussian_filter1d
            segment_y_smooth = gaussian_filter1d(segment[:, 1], sigma=1.0)
            
            # Fit line
            slope_calc, intercept = np.polyfit(segment[:, 0], segment_y_smooth, 1)
            trend_line_x = segment[:, 0]
            trend_line_y = slope_calc * trend_line_x + intercept
            
            ax4.plot(segment[:, 0], segment[:, 1], 'ro-', linewidth=2, markersize=5, 
                    label='Actual Points', alpha=0.7)
            ax4.plot(segment[:, 0], segment_y_smooth, 'b--', linewidth=1.5, 
                    label='Smoothed', alpha=0.5)
            ax4.plot(trend_line_x, trend_line_y, 'g-', linewidth=3, 
                    label=f'Trend Line', alpha=0.8)
            
            # Add arrow showing direction
            arrow_start = len(trend_line_x) // 3
            arrow_end = arrow_start + len(trend_line_x) // 3
            if arrow_end < len(trend_line_x):
                ax4.annotate('', 
                           xy=(trend_line_x[arrow_end], trend_line_y[arrow_end]),
                           xytext=(trend_line_x[arrow_start], trend_line_y[arrow_start]),
                           arrowprops=dict(arrowstyle='->', color='green', lw=3))
        
        trend = result['trend']
        color = 'green' if trend == 'up' else 'red' if trend == 'down' else 'gray'
        direction_symbol = '↗' if trend == 'up' else '↘' if trend == 'down' else '→'
        
        ax4.set_title(f'Trend: {trend.upper()} {direction_symbol}\nSlope: {slope:.4f}', 
                     fontsize=12, weight='bold', color=color)
        ax4.set_xlabel('X (Time →)')
        ax4.set_ylabel('Y (Price ↑)')
        ax4.grid(True, alpha=0.3)
        ax4.legend(loc='best', fontsize=8)
        
        # 5. Detection Steps Info
        ax5 = fig.add_subplot(gs[2, :])
        ax5.axis('off')
        
        # Create info text
        info_text = f"""
DETECTION PROCESS:

1. EXTRACTION: Extracted {len(points)} coordinate points from the chart line
   
2. NORMALIZATION: Scaled coordinates to 0-100 range (larger Y = higher price)
   
3. ANALYSIS SEGMENT: Using last {len(segment)} points ({len(segment)/len(points)*100:.1f}% of chart)
   • Start Position: X={segment[0,0]:.1f}, Y={segment[0,1]:.1f}
   • End Position:   X={segment[-1,0]:.1f}, Y={segment[-1,1]:.1f}
   • Y Change:       {segment[-1,1] - segment[0,1]:.2f} ({'+' if segment[-1,1] > segment[0,1] else ''}{(segment[-1,1] - segment[0,1])/segment[0,1]*100:.1f}%)

4. TREND CALCULATION: Linear regression on smoothed segment
   • Slope: {slope:.4f} {'(positive → upward)' if slope > 0 else '(negative → downward)' if slope < 0 else '(near zero → flat)'}
   • Threshold: ±0.15 (slopes within this range are considered flat)

5. RESULT: {direction_symbol} {trend.upper()} {'✓' if trend in ['up', 'down'] else '⚠'}
"""
        
        ax5.text(0.05, 0.95, info_text, transform=ax5.transAxes,
                fontsize=10, verticalalignment='top', family='monospace',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        # Main title
        fig.suptitle('Chart Line Detection Analysis', fontsize=16, weight='bold')
        
        # Save or return
        if output_path:
            plt.savefig(output_path, dpi=120, bbox_inches='tight', facecolor='white')
            plt.close()
            return {
                'success': True,
                'visualization_path': output_path,
                'trend': trend,
                'slope': slope,
                'points_count': len(points),
                'segment_size': len(segment)
            }
        else:
            # Return as bytes for web display
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='white')
            buf.seek(0)
            plt.close()
            
            return {
                'success': True,
                'image_bytes': buf.getvalue(),
                'trend': trend,
                'slope': slope,
                'points_count': len(points),
                'segment_size': len(segment)
            }
    
    def create_base64_visualization(self, image_path):
        """
        Create visualization and return as base64 string for web display.
        
        Args:
            image_path: Path to the chart image
            
        Returns:
            Dict with base64_image, trend, and other details
        """
        result = self.create_visualization(image_path)
        
        if not result['success']:
            return result
        
        # Convert bytes to base64
        img_base64 = base64.b64encode(result['image_bytes']).decode('utf-8')
        
        return {
            'success': True,
            'visualization_base64': img_base64,
            'trend': result['trend'],
            'slope': result['slope'],
            'points_count': result['points_count'],
            'segment_size': result['segment_size']
        }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python chart_visualizer.py <image_path> [output_path]")
        print("\nExample:")
        print("  python chart_visualizer.py chart.png")
        print("  python chart_visualizer.py chart.png visualization.png")
        sys.exit(1)
    
    image_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else 'chart_visualization.png'
    
    print(f"Creating visualization for: {image_path}")
    
    visualizer = ChartVisualizer()
    result = visualizer.create_visualization(image_path, output_path)
    
    if result['success']:
        print(f"\n✓ Visualization saved to: {output_path}")
        print(f"  Trend: {result['trend'].upper()}")
        print(f"  Slope: {result['slope']:.4f}")
        print(f"  Points: {result['points_count']}")
        print(f"  Segment Size: {result['segment_size']}")
    else:
        print(f"\n✗ Error: {result.get('error', 'Unknown error')}")
