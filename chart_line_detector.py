"""
Chart Line Extraction Module

This module provides a class to extract and process line charts from images,
converting them into coordinate data and determining trend direction.
"""

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d


class ChartLineDetector:
    """
    A detector for extracting line charts from images and determining trend direction.

    Improvements for Robinhood-style graphs:
    - Stronger color / saturation based masking with robust fallback for anti-aliased lines
    - Morphological cleanup and component selection by x-span (prefer widest line across chart)
    - Trend computed by linear regression on the final fraction of the curve (configurable)
    - Defensive normalization (avoid div-by-zero) and smoothing
    """

    def __init__(
        self,
        window_size=5,
        slope_threshold=0.05,        # lowered: more sensitive to small trends
        end_fraction=0.20,          # evaluate trend on the last 20% of the curve
        target_spacing=0.2,
        color_threshold=20,         # lowered: catch more colored pixels
        saturation_threshold=15,    # lowered: catch faint lines
        gray_tolerance=15,
        use_multi_window=True,      # use multiple tail windows for robust detection
        momentum_weight=0.3         # weight for momentum (recent slope change)
    ):
        self.window_size = window_size
        self.slope_threshold = slope_threshold
        self.end_fraction = end_fraction
        self.target_spacing = target_spacing
        self.color_threshold = color_threshold
        self.saturation_threshold = saturation_threshold
        self.gray_tolerance = gray_tolerance
        self.use_multi_window = use_multi_window
        self.momentum_weight = momentum_weight

    def analyze_with_details(self, image_path):
        """
        Process a chart image and return detailed analysis data.
        
        Returns:
            dict: Contains trend direction, slope, turning point index, and coordinates
                  {
                      'trend': "up"/"down"/"none",
                      'slope': float,
                      'flip_index': int,
                      'points': numpy array of normalized points,
                      'segment': numpy array of final segment points,
                      'success': bool
                  }
        """
        try:
            points = self._extract_chart_line(image_path)
            if points is None or len(points) == 0:
                return {'success': False, 'error': 'No chart line detected'}

            cleaned = self._clean_and_smooth_points(points)
            if len(cleaned) == 0:
                return {'success': False, 'error': 'Line cleaning failed'}

            densified = self._densify_steep_sections(cleaned)
            if len(densified) == 0:
                return {'success': False, 'error': 'Line densification failed'}

            normalized = self._normalize_points(densified)
            if normalized is None or len(normalized) < 2:
                return {'success': False, 'error': 'Insufficient points'}

            # Get detailed analysis
            x_vals = normalized[:, 0]
            y_vals = normalized[:, 1]
            
            # Use last 15% for trend analysis
            lookback_pct = 0.15
            lookback_points = max(5, int(len(normalized) * lookback_pct))
            flip_idx = len(normalized) - lookback_points
            
            segment = normalized[flip_idx:]
            
            # Calculate slope of final segment
            slope = 0.0
            if len(segment) >= 2:
                from scipy.ndimage import gaussian_filter1d
                segment_y_smooth = gaussian_filter1d(segment[:, 1], sigma=1.0)
                slope, _ = np.polyfit(segment[:, 0], segment_y_smooth, 1)
            
            trend = self._compute_trend(normalized)
            
            return {
                'success': True,
                'trend': trend,
                'slope': float(slope),
                'flip_index': int(flip_idx),
                'points': normalized,
                'segment': segment,
                'raw_points': points
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def __call__(self, image_path):
        """
        Process a chart image and determine the trend direction.

        Returns:
            str: "up", "down", or "none"
        """
        try:
            points = self._extract_chart_line(image_path)
            if points is None or len(points) == 0:
                return "none"

            cleaned = self._clean_and_smooth_points(points)
            if len(cleaned) == 0:
                return "none"

            densified = self._densify_steep_sections(cleaned)
            if len(densified) == 0:
                return "none"

            normalized = self._normalize_points(densified)
            if normalized is None or len(normalized) < 2:
                return "none"

            trend = self._compute_trend(normalized)
            return trend

        except Exception as e:
            print(f"Error processing {image_path}: {e}")
            return "none"

    def _clean_background_keep_colored_lines(self, img):
        """
        Improved masking: preserve colored/bright lines while suppressing most background.
        Returns a mask (uint8) with 1 where line candidate pixels exist.
        """
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        b = img[:, :, 0].astype(np.int16)
        g = img[:, :, 1].astype(np.int16)
        r = img[:, :, 2].astype(np.int16)
        saturation = hsv[:, :, 1].astype(np.int16)
        value = hsv[:, :, 2].astype(np.int16)

        channel_max = np.maximum(np.maximum(r, g), b)
        channel_min = np.minimum(np.minimum(r, g), b)
        color_spread = channel_max - channel_min

        diff_rg = np.abs(r - g)
        diff_gb = np.abs(g - b)
        diff_rb = np.abs(r - b)

        is_grayscale = (diff_rg < self.gray_tolerance) & (diff_gb < self.gray_tolerance) & (diff_rb < self.gray_tolerance)
        is_colored = (~is_grayscale) & ((color_spread > self.color_threshold) | (saturation > self.saturation_threshold))

        # Also treat very bright/dark high-contrast pixels as potential line (handles white/black lines)
        high_contrast = (value > 220) | (value < 30)
        candidate = is_colored | high_contrast

        mask = (candidate).astype(np.uint8) * 255

        # Morphological cleanup: close gaps and remove small specks
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        # Thin the mask slightly to focus on line center
        mask = cv2.erode(mask, kernel, iterations=1)

        return mask

    def _extract_via_skeleton(self, edges):
        """
        Robust coordinate extraction without relying on ximgproc.thinning.
        For each x column keep median y of edge pixels; returns (x,y) sorted by x.
        """
        ys, xs = np.where(edges > 0)
        if len(xs) == 0:
            return np.empty((0, 2))

        data = np.column_stack((xs, ys))
        unique_x = np.unique(data[:, 0])
        points = []
        for x in unique_x:
            y_vals = data[data[:, 0] == x, 1]
            median_y = int(np.median(y_vals))
            points.append([int(x), median_y])
        points = np.array(points, dtype=float)
        # Ensure sorted by x
        points = points[points[:, 0].argsort()]
        return points

    def _extract_chart_line(self, image_path):
        """
        Extract line chart coordinates using color masking + Canny on the colored mask.
        Selects the connected component with the largest x-span (most likely main line).
        """
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not read image from {image_path}")

        mask = self._clean_background_keep_colored_lines(img)

        # If mask is almost empty, fall back to edge detection on grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if mask.sum() < 50:
            # Use Otsu threshold for automatic edge detection
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            edges = cv2.Canny(gray, 30, 100)
            # Also try adaptive threshold and combine
            adapt = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY, 11, 2)
            edges = cv2.bitwise_or(edges, adapt)
        else:
            # Edges on masked color regions to pick up anti-aliased/soft lines
            masked = cv2.bitwise_and(img, img, mask=mask)
            gray_masked = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
            # Use multiple edge detection approaches and combine
            v = np.median(gray_masked[gray_masked > 0]) if np.any(gray_masked > 0) else 127
            lower = max(5, int(0.5 * v))
            upper = min(180, int(1.5 * v) + 30)
            edges1 = cv2.Canny(gray_masked, lower, upper)
            # Also try tighter thresholds
            edges2 = cv2.Canny(gray_masked, max(10, lower - 10), min(200, upper + 20))
            edges = cv2.bitwise_or(edges1, edges2)
            # If still sparse, try on full gray with mask overlay
            if edges.sum() < 500:
                edges_gray = cv2.Canny(gray, 40, 120)
                edges_gray = cv2.bitwise_and(edges_gray, edges_gray, mask=mask)
                edges = cv2.bitwise_or(edges, edges_gray)

        # Slightly dilate to connect broken strokes
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)

        # Find connected components and pick the one with largest x-span (robust for Robinhood charts)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(edges, connectivity=8)
        best_mask = None
        best_span = 0
        for lbl in range(1, num_labels):
            x, y, w, h, area = stats[lbl]
            span = w  # width across x-axis
            if span > best_span and area > 10:
                best_span = span
                best_mask = (labels == lbl).astype(np.uint8) * 255

        if best_mask is not None:
            edges = cv2.bitwise_and(edges, edges, mask=best_mask)
        # else leave edges as-is (may still contain the line)

        points = self._extract_via_skeleton(edges)
        return points

    def _clean_and_smooth_points(self, points):
        """
        Remove outliers and smooth the extracted line.
        """
        if len(points) == 0:
            return points

        # For each x-coordinate, take median y-value (removes outliers)
        unique_x = np.unique(points[:, 0])
        cleaned = []
        for x in unique_x:
            y_values = points[points[:, 0] == x, 1]
            median_y = np.median(y_values)
            cleaned.append([x, median_y])

        cleaned = np.array(cleaned, dtype=float)

        # Apply Gaussian smoothing to y-values (lighter smoothing to preserve detail)
        if len(cleaned) > self.window_size:
            cleaned[:, 1] = gaussian_filter1d(cleaned[:, 1], sigma=max(0.8, self.window_size / 4.0))

        # Remove outliers using IQR on y-differences
        if len(cleaned) > 10:
            dy = np.diff(cleaned[:, 1])
            q1, q3 = np.percentile(dy, [25, 75])
            iqr = q3 - q1
            lower_bound = q1 - 2.0 * iqr
            upper_bound = q3 + 2.0 * iqr
            # Mark outlier transitions
            outlier_mask = (dy < lower_bound) | (dy > upper_bound)
            # Interpolate outlier points
            for i in range(len(outlier_mask)):
                if outlier_mask[i] and i > 0 and i < len(cleaned) - 2:
                    # Replace with average of neighbors
                    cleaned[i + 1, 1] = (cleaned[i, 1] + cleaned[min(i + 2, len(cleaned) - 1), 1]) / 2

        return cleaned

    def _densify_steep_sections(self, points):
        """
        Add interpolated points in steep sections for better representation.
        """
        if len(points) < 2:
            return points

        result = [points[0]]

        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]

            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]

            slope = abs(dy / dx) if dx != 0 else float('inf')

            if slope > self.slope_threshold and dx > self.target_spacing:
                num_points = max(1, int(dx / max(self.target_spacing, 0.1)))
                for j in range(1, num_points):
                    t = j / num_points
                    x_interp = p1[0] + t * dx
                    y_interp = p1[1] + t * dy
                    result.append([x_interp, y_interp])

            result.append(p2)

        return np.array(result, dtype=float)

    def _normalize_points(self, points, width=100, height=100):
        """
        Normalize coordinates to a standard scale with defensive guards.
        In image coordinates: y=0 is top, larger y is bottom
        After normalization: larger y means higher price/value (top of chart)
        """
        pts = np.array(points, dtype=float)
        if pts.size == 0:
            return None
        x_min, y_min = pts.min(axis=0)
        x_max, y_max = pts.max(axis=0)
        dx = x_max - x_min
        dy = y_max - y_min
        if dx == 0:
            dx = 1.0
        if dy == 0:
            dy = 1.0

        normalized = pts.copy()
        # Normalize x from 0 to (width-1)
        normalized[:, 0] = (pts[:, 0] - x_min) / dx * (width - 1)
        # Normalize and flip y: in image coords small y=top, we want small y=bottom for chart analysis
        # So we invert: top of image (small pts y) becomes large normalized y (high price)
        normalized[:, 1] = (y_max - pts[:, 1]) / dy * (height - 1)
        return normalized

    def _compute_trend(self, normalized_points):
        """
        SIMPLE trend detection: Check if the chart is going UP or DOWN at the END (current moment).
        
        Algorithm:
        1. Take the last portion of the chart (e.g., last 15-20% of points)
        2. Fit a linear regression line through these points
        3. Check the slope:
           - Positive slope → UP (price increasing)
           - Negative slope → DOWN (price decreasing)
        
        This tells us the direction RIGHT NOW at the endpoint.
        
        Coordinate system: larger y = higher price
        Positive slope = upward trend, Negative slope = downward trend
        
        Returns "up", "down", or "none".
        """
        pts = np.array(normalized_points, dtype=float)
        if len(pts) < 5:
            return "none"

        x_vals = pts[:, 0]
        y_vals = pts[:, 1]
        
        # Use the last portion of the chart for trend detection
        # This percentage determines how "recent" we look
        # 15% = very recent (last few seconds/minutes)
        # 30% = slightly longer view
        lookback_pct = 0.15
        lookback_points = max(5, int(len(pts) * lookback_pct))
        
        # Get the final segment
        final_segment_x = x_vals[-lookback_points:]
        final_segment_y = y_vals[-lookback_points:]
        
        # Apply light smoothing to reduce noise
        from scipy.ndimage import gaussian_filter1d
        final_segment_y_smooth = gaussian_filter1d(final_segment_y, sigma=1.0)
        
        # Fit linear regression to get the slope
        try:
            slope, intercept = np.polyfit(final_segment_x, final_segment_y_smooth, 1)
        except Exception as e:
            print(f"Linear regression failed: {e}")
            return "none"
        
        # Determine trend from slope
        # Use a small threshold to avoid noise (0.1 is about 0.1% change per normalized unit)
        slope_threshold = 0.15
        
        if slope > slope_threshold:
            return "up"
        elif slope < -slope_threshold:
            return "down"
        else:
            return "none"  # Nearly flat/sideways

    def _last_y_direction_change(self, points):
        """
        Keep for backward compatibility but prefer _compute_trend for Robinhood charts.
        """
        if len(points) < 3:
            return None

        y = [p[1] for p in points]
        direction = 0  # 1 = up, -1 = down
        last_change_index = None

        for i in range(1, len(y)):
            dy = y[i] - y[i - 1]
            new_dir = 1 if dy > 0 else (-1 if dy < 0 else direction)
            if direction and new_dir and new_dir != direction:
                last_change_index = i - 1
            direction = new_dir

        if last_change_index is not None:
            return points[last_change_index]
        return None


if __name__ == "__main__":
    import os

    image_folder = "./charts"

    if not os.path.exists(image_folder):
        print(f"Error: Folder '{image_folder}' not found. Please create it and add chart images.")
        exit(1)

    images = [f for f in os.listdir(image_folder)
              if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]

    if not images:
        print(f"No images found in '{image_folder}'. Please add .png, .jpg, .jpeg, or .bmp files.")
        exit(1)

    detector = ChartLineDetector()

    for img_file in images:
        image_path = os.path.join(image_folder, img_file)
        print(f"\nProcessing: {img_file}")

        result = detector(image_path)

        if result == "up":
            print(f"  📈 Trend: UP after last direction change")
        elif result == "down":
            print(f"  📉 Trend: DOWN after last direction change")
        else:
            print(f"  ⚠️ No direction change detected in the chart")

    print("\n" + "=" * 60)
    print("To install required packages, run:")
    print("pip install opencv-python opencv-contrib-python numpy scipy")