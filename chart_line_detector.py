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
        normalized[:, 0] = (pts[:, 0] - x_min) / dx * (width - 1)
        # Invert y so that larger values mean "higher" on chart (consistent with plotting coordinates)
        normalized[:, 1] = (pts[:, 1] - y_min) / dy * (height - 1)
        # Flip y so origin at bottom (optional depending on interpretation)
        normalized[:, 1] = (height - 1) - normalized[:, 1]
        return normalized

    def _find_last_turning_point(self, y_vals, min_swing=2.0, min_run=3):
        """
        Find the index of the last significant turning point (local min/max).
        A turning point is where direction changes after a sustained move.
        
        Args:
            y_vals: normalized y values
            min_swing: minimum y-change to count as a real swing (not noise)
            min_run: minimum number of points moving in same direction
        
        Returns:
            index of the last turning point, or 0 if none found
        """
        if len(y_vals) < 5:
            return 0
        
        # Compute direction at each point: +1 = up, -1 = down, 0 = flat
        dy = np.diff(y_vals)
        directions = np.sign(dy)
        
        # Smooth out tiny wiggles: require sustained direction
        smoothed_dir = np.zeros_like(directions)
        current_dir = 0
        run_length = 0
        for i in range(len(directions)):
            if directions[i] == current_dir or directions[i] == 0:
                run_length += 1
            else:
                if run_length >= min_run:
                    current_dir = directions[i]
                    run_length = 1
                else:
                    run_length += 1
            smoothed_dir[i] = current_dir if current_dir != 0 else directions[i]
        
        # Find turning points: where smoothed direction changes
        turning_points = []
        for i in range(1, len(smoothed_dir)):
            if smoothed_dir[i] != 0 and smoothed_dir[i-1] != 0 and smoothed_dir[i] != smoothed_dir[i-1]:
                # Check if swing is significant
                # Look back to find the local extremum
                j = i - 1
                while j > 0 and smoothed_dir[j] == smoothed_dir[i-1]:
                    j -= 1
                swing = abs(y_vals[i] - y_vals[j])
                if swing >= min_swing:
                    turning_points.append(i)
        
        if not turning_points:
            # No turning point found — use a fraction from the end
            return max(0, len(y_vals) - int(len(y_vals) * self.end_fraction))
        
        return turning_points[-1]  # Return the LAST turning point

    def _compute_trend(self, normalized_points):
        """
        Compute trend AFTER the last turning point (most recent direction change).
        This gives the current trading direction since the last reversal.
        Returns "up", "down", or "none".
        """
        pts = np.array(normalized_points, dtype=float)
        if len(pts) < 5:
            return "none"

        x_vals = pts[:, 0]
        y_vals = pts[:, 1]
        
        # Find the last turning point
        turn_idx = self._find_last_turning_point(y_vals, min_swing=1.5, min_run=2)
        
        # Get segment from turning point to end
        segment = pts[turn_idx:]
        if len(segment) < 2:
            segment = pts[-max(3, int(len(pts) * 0.15)):]
        
        seg_x = segment[:, 0]
        seg_y = segment[:, 1]
        
        # Method 1: Linear regression on segment after turning point
        slope = 0.0
        try:
            if len(segment) >= 2:
                a, b = np.polyfit(seg_x, seg_y, 1)
                slope = a
        except Exception:
            pass
        
        # Method 2: Direct endpoint comparison (most intuitive for traders)
        y_at_turn = y_vals[turn_idx]
        y_at_end = y_vals[-1]
        endpoint_delta = y_at_end - y_at_turn
        
        # Method 3: Recent momentum (last few points)
        recent_n = min(5, len(segment))
        recent_delta = y_vals[-1] - y_vals[-recent_n] if recent_n > 1 else 0
        
        # Combined decision: weight endpoint delta heavily (what traders see)
        # Normalize by segment length for fair comparison
        seg_len = max(1, len(segment))
        normalized_delta = endpoint_delta / (seg_len ** 0.5)  # sqrt to not over-penalize short segments
        
        # Thresholds (tuned for normalized 0-100 scale)
        delta_thresh = 1.0  # minimum y-change to call a trend
        slope_thresh = self.slope_threshold
        
        # Score combining all signals
        score = 0.0
        if abs(endpoint_delta) > delta_thresh:
            score += np.sign(endpoint_delta) * min(abs(endpoint_delta), 10) * 0.5
        if abs(slope) > slope_thresh:
            score += np.sign(slope) * min(abs(slope), 1.0) * 3.0
        if abs(recent_delta) > 0.5:
            score += np.sign(recent_delta) * min(abs(recent_delta), 5) * 0.3
        
        # Decision
        if score > 0.5 or endpoint_delta > delta_thresh:
            return "up"
        elif score < -0.5 or endpoint_delta < -delta_thresh:
            return "down"
        else:
            return "none"

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