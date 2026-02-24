"""
Chart Direction Detector Module

This module provides a class-based interface over the graph_direction.py logic,
converting the procedural pipeline into a reusable detector object.

Pipeline (mirrors graph_direction.py v14):
  1. Load image and crop vertical margins
  2. Canny edge detection
  3. Remove horizontal artifacts (dotted grid lines, baselines) via Hough
  4. Bridge gaps with morphological operations
  5. Pick the best connected component using density-based scoring
  6. Trace the chart line as a y(x) function
  7. Extend the trace to the rightmost visible edge
  8. Build a zoomed ROI at the graph end
  9. Re-run steps 2-6 on the zoomed ROI
 10. Find the last slope direction change → return UP / DOWN

Outputs (when outdir is provided):
  full_edges_raw.png, full_edges_clean.png, full_edges_bridged.png,
  full_component.png, full_component_dilated.png, full_traced.png,
  original_with_roi.png, zoom.png, edges.png, edges_traced.png, traced.png
"""

import sys
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class _ROI:
    x0: int
    y0: int
    x1: int
    y1: int


# ---------------------------------------------------------------------------
# Main detector class
# ---------------------------------------------------------------------------

class ChartDirectionDetector:
    """
    Detects the trend direction (UP or DOWN) at the rightmost end of a
    financial line-chart screenshot.

    Design (v14 logic):
    - Removes horizontal dotted/grid lines via Hough before component selection.
    - Bridges gaps with morphological dilation to reconnect broken chart lines.
    - Selects the graph component using a density-aware scoring function:
        density = area / (bbox_w * bbox_h)
        Huge bounding-box components are only rejected when density > 0.18
        (i.e. filled UI panels), NOT when they are sparse chart lines.
    - Traces the line as y(x) using column-wise median.
    - Extends the trace rightward through a band-search on clean edges.
    - Zooms (3x) the right-end ROI for more accurate slope calculation.
    - Classifies direction via gradient smoothing on the zoomed trace.

    Parameters
    ----------
    canny_low : int
        Lower threshold for Canny edge detector. Default 30.
    canny_high : int
        Upper threshold for Canny edge detector. Default 120.
    hough_threshold : int
        Minimum Hough accumulator votes to detect a line. Default 40.
    hough_max_gap : int
        Maximum pixel gap for Hough line segments. Default 14.
    horizontal_slope_max : float
        Slope magnitude below which a line is treated as horizontal (and removed).
        Default 0.08.
    min_component_area : int
        Minimum pixel area for a connected component to be considered. Default 160.
    density_threshold : float
        Density above which a huge-bbox component is rejected as a UI panel.
        Default 0.18.
    band_half_height : int
        Half-height of the vertical search band used when extending the trace end.
        Default 22.
    max_end_gap : int
        Maximum consecutive blank columns before stopping the end extension. Default 18.
    slope_threshold : float
        Gradient magnitude below which motion is considered flat (not UP/DOWN).
        Default 0.03.
    last_w_frac_graph : float
        Fraction of total graph x-span used as ROI width. Default 0.28.
    full_y_margin_frac : float
        Fraction of image height to crop from top and bottom. Default 0.02.
    zoom_factor : float
        Magnification applied to the right-end ROI before direction analysis.
        Default 3.0.
    smooth_win_trace : int
        Moving-average window applied to the raw trace before gradient. Default 9.
    smooth_win_grad : int
        Moving-average window applied to the gradient. Default 7.
    """

    def __init__(
        self,
        canny_low: int = 30,
        canny_high: int = 120,
        hough_threshold: int = 40,
        hough_max_gap: int = 14,
        horizontal_slope_max: float = 0.08,
        min_component_area: int = 160,
        density_threshold: float = 0.18,
        band_half_height: int = 22,
        max_end_gap: int = 18,
        slope_threshold: float = 0.15,
        last_w_frac_graph: float = 0.28,
        full_y_margin_frac: float = 0.02,
        zoom_factor: float = 3.0,
        smooth_win_trace: int = 15,
        smooth_win_grad: int = 11,
    ):
        self.canny_low = canny_low
        self.canny_high = canny_high
        self.hough_threshold = hough_threshold
        self.hough_max_gap = hough_max_gap
        self.horizontal_slope_max = horizontal_slope_max
        self.min_component_area = min_component_area
        self.density_threshold = density_threshold
        self.band_half_height = band_half_height
        self.max_end_gap = max_end_gap
        self.slope_threshold = slope_threshold
        self.last_w_frac_graph = last_w_frac_graph
        self.full_y_margin_frac = full_y_margin_frac
        self.zoom_factor = zoom_factor
        self.smooth_win_trace = smooth_win_trace
        self.smooth_win_grad = smooth_win_grad

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def __call__(self, image_path: str) -> str:
        """
        Analyze a chart screenshot and return the trend direction.

        Parameters
        ----------
        image_path : str
            Path to the input screenshot.

        Returns
        -------
        str
            "UP", "DOWN", "NONE", or "ERROR: <message>"
        """
        try:
            result = self.analyze_with_details(image_path)
            if result["success"]:
                return result["direction"]
            return "ERROR: " + result["error"]
        except Exception as exc:
            return f"ERROR: {exc}"

    def analyze_with_details(self, image_path: str) -> dict:
        """
        Full analysis returning the direction result.

        Parameters
        ----------
        image_path : str
            Path to the input screenshot.

        Returns
        -------
        dict with keys:
            success        - bool
            direction      - "UP" | "DOWN" | "NONE"  (only when success is True)
            end_dir        - +1 (UP) | -1 (DOWN) | 0 (NONE)
            trend_start_x  - x index where the final trend segment begins (zoom coords)
            error          - str  (only when success is False)
        """
        # -- 1. Load & margin-crop ----------------------------------------
        img = self._load_image(image_path)
        H, W = img.shape[:2]

        y_margin = int(H * max(0.0, min(0.12, self.full_y_margin_frac)))
        crop_y0 = y_margin
        crop_y1 = H - y_margin
        full_crop = img[crop_y0:crop_y1, :]

        # -- 2. Full-image edge pipeline ----------------------------------
        full_edges_raw     = self._canny_edges(full_crop)
        full_edges_clean   = self._remove_horizontal_artifacts(full_edges_raw)
        full_edges_bridged = self._bridge_gaps(full_edges_clean)

        # -- 3. Component selection ---------------------------------------
        comp_full = self._pick_graph_component(full_edges_bridged)
        k_ellipse = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        comp_d    = cv2.dilate(comp_full, k_ellipse, iterations=1)

        x0g, x1g, y0g, y1g = self._component_bounds(comp_d)
        if x1g < 0:
            return {"success": False, "error": "Couldn't find the graph line on the full screenshot."}

        # -- 4. Trace & extend --------------------------------------------
        try:
            y_full = self._trace_path(comp_d)
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        x1g_ext = self._extend_end(full_edges_clean, y_full, x1g)
        x1g_ext = min(full_edges_clean.shape[1] - 1, max(x1g, x1g_ext))

        # -- 5. ROI at graph end ------------------------------------------
        roi = self._build_roi(img, comp_d, crop_y0, x0g, x1g_ext, y0g, y1g)

        # -- 6. Zoom ROI --------------------------------------------------
        roi_bgr = img[roi.y0:roi.y1, roi.x0:roi.x1].copy()
        zoom    = cv2.resize(roi_bgr, None,
                             fx=self.zoom_factor, fy=self.zoom_factor,
                             interpolation=cv2.INTER_CUBIC)

        # -- 7. Zoom edge pipeline ----------------------------------------
        edges_zoom_raw    = self._canny_edges(zoom)
        edges_zoom_clean  = self._remove_horizontal_artifacts(edges_zoom_raw)
        edges_zoom_bridged = self._bridge_gaps(edges_zoom_clean)
        comp_zoom          = self._pick_graph_component(edges_zoom_bridged)

        try:
            y_zoom = self._trace_path(comp_zoom)
        except RuntimeError as exc:
            return {"success": False, "error": f"Zoom trace failed: {exc}"}

        # -- 8. Direction detection ---------------------------------------
        trend_start, end_dir = self._find_last_direction_change(y_zoom)
        if end_dir > 0:
            direction = "UP"
        elif end_dir < 0:
            direction = "DOWN"
        else:
            direction = "NONE"

        return {
            "success":       True,
            "direction":     direction,
            "end_dir":       end_dir,
            "trend_start_x": int(trend_start),
        }

    # ------------------------------------------------------------------
    # Private helpers - image loading & I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _load_image(path: str) -> np.ndarray:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {path}")
        return img

    @staticmethod
    def _clamp_roi(roi: _ROI, w: int, h: int) -> _ROI:
        x0 = max(0, min(w - 1, roi.x0))
        y0 = max(0, min(h - 1, roi.y0))
        x1 = max(1, min(w, roi.x1))
        y1 = max(1, min(h, roi.y1))
        if x1 <= x0 or y1 <= y0:
            raise ValueError("ROI became invalid after clamping.")
        return _ROI(x0, y0, x1, y1)

    # ------------------------------------------------------------------
    # Private helpers - image processing pipeline
    # ------------------------------------------------------------------

    def _canny_edges(self, bgr: np.ndarray) -> np.ndarray:
        """Convert BGR frame to Canny edge map."""
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        return cv2.Canny(gray, self.canny_low, self.canny_high)

    def _remove_horizontal_artifacts(self, edges: np.ndarray) -> np.ndarray:
        """
        Erase nearly-horizontal Hough lines from the edge map.

        These correspond to dotted grid lines, price-axis baselines, etc.
        A line is considered horizontal when |dy/dx| < horizontal_slope_max.
        """
        h, w = edges.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180,
            threshold=self.hough_threshold,
            minLineLength=max(20, w // 10),
            maxLineGap=self.hough_max_gap,
        )
        if lines is None:
            return edges
        for (x1, y1, x2, y2) in lines[:, 0]:
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0:
                continue
            if abs(dy / dx) < self.horizontal_slope_max:
                cv2.line(mask, (x1, y1), (x2, y2), 255, 3)
        out = edges.copy()
        out[mask > 0] = 0
        return out

    @staticmethod
    def _bridge_gaps(edges_clean: np.ndarray) -> np.ndarray:
        """
        Connect broken chart-line segments caused by dotted lines or anti-aliasing.

        Steps:
          1. Vertical dilation (3x9) bridges gaps along column direction.
          2. Morphological closing (3x5) fills remaining small holes.
        """
        bw = (edges_clean > 0).astype(np.uint8) * 255
        k_vert  = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 9))
        bw      = cv2.dilate(bw, k_vert, iterations=1)
        k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5))
        bw      = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, k_close, iterations=1)
        return (bw > 0).astype(np.uint8) * 255

    def _pick_graph_component(self, edges_for_cc: np.ndarray) -> np.ndarray:
        """
        Select the connected component most likely to be the main chart line.

        Scoring:
          score = (x_span * y_span) + (right_edge * 1500)
                  -----------------------------------------
                  (1 + 0.03 * thickness) * (1 + 1.5 * density)

        Rejection rules (all three must hold for rejection):
          - x_span > 95 % of image width
          - y_span > 80 % of image height
          - density > density_threshold   <- v14 fix: chart lines are sparse

        This prevents previously valid huge-bbox chart lines from being
        discarded as UI panels.
        """
        bw = (edges_for_cc > 0).astype(np.uint8) * 255
        num, labels, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
        if num <= 1:
            return np.zeros_like(bw)

        h, w = bw.shape[:2]
        best_i     = -1
        best_score = -1.0

        for i in range(1, num):
            x, y, ww, hh, area = stats[i]
            if area < self.min_component_area:
                continue

            x_span = ww
            y_span = hh
            right_edge = x + ww

            # Reject thin horizontal baselines
            if y_span <= 3 and x_span >= w * 0.20:
                continue

            # Reject dense huge blocks (UI overlays) - NOT sparse chart lines
            bbox_area = max(1, x_span * y_span)
            density   = float(area) / float(bbox_area)
            if (x_span > w * 0.95) and (y_span > h * 0.80) and (density > self.density_threshold):
                continue

            # Score: prefer large, rightward, thin (line-like), low-density components
            score      = float(x_span * y_span) + float(right_edge) * 1500.0
            thickness  = area / max(1.0, x_span)
            score     /= (1.0 + 0.03 * thickness)
            score     /= (1.0 + 1.5  * density)

            if score > best_score:
                best_score = score
                best_i     = i

        out = np.zeros_like(bw)
        if best_i != -1:
            out[labels == best_i] = 255
        return out

    @staticmethod
    def _component_bounds(mask: np.ndarray):
        """Return (x_min, x_max, y_min, y_max) of non-zero pixels, or (-1,...) if empty."""
        ys, xs = np.where(mask > 0)
        if xs.size == 0:
            return -1, -1, -1, -1
        return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())

    @staticmethod
    def _trace_path(mask: np.ndarray) -> np.ndarray:
        """
        Convert a binary component mask into a 1-D array y[x].

        For each column x, the representative y is the median of all lit pixels.
        Columns with no pixels produce NaN values that are then linearly
        interpolated from their filled neighbours.

        Raises RuntimeError when fewer than 10 % of columns have data.
        """
        h, w = mask.shape[:2]
        y = np.full(w, np.nan, dtype=np.float32)
        for x in range(w):
            pts = np.where(mask[:, x] > 0)[0]
            if pts.size:
                y[x] = float(np.median(pts))
        valid = ~np.isnan(y)
        if valid.sum() < max(30, int(w * 0.10)):
            raise RuntimeError("Too few column samples to trace the graph line.")
        x_idx = np.arange(w)
        return np.interp(x_idx, x_idx[valid], y[valid]).astype(np.float32)

    def _extend_end(self, edges: np.ndarray, y_pred: np.ndarray, x_end: int) -> int:
        """
        Extend the traced end-point rightward through a vertical band search.

        Starting at x_end, scan each column checking a +/-band_half_height pixel
        window around the predicted y.  Stop when max_end_gap blank columns
        are encountered consecutively.

        Returns the updated rightmost x with confirmed edge support.
        """
        h, w = edges.shape[:2]
        x       = max(0, min(w - 1, x_end))
        last_hit = x
        gap      = 0
        for x2 in range(x, w):
            yy = int(round(float(y_pred[min(x2, w - 1)])))
            y0 = max(0, yy - self.band_half_height)
            y1 = min(h, yy + self.band_half_height + 1)
            if np.any(edges[y0:y1, x2] > 0):
                last_hit = x2
                gap      = 0
            else:
                gap += 1
                if gap > self.max_end_gap:
                    break
        return int(last_hit)

    # ------------------------------------------------------------------
    # Private helpers - signal processing & direction
    # ------------------------------------------------------------------

    @staticmethod
    def _smooth_1d(y: np.ndarray, win: int) -> np.ndarray:
        """Box-car (moving-average) smoothing with edge padding."""
        win = max(3, int(win) | 1)          # ensure odd and >= 3
        k   = np.ones(win, dtype=np.float32) / win
        pad = np.pad(y, (win // 2, win // 2), mode="edge")
        return np.convolve(pad, k, mode="valid").astype(np.float32)

    def _find_last_direction_change(self, y: np.ndarray):
        """
        Determine the dominant direction at the trace end and find where it starts.

        Algorithm:
          1. Smooth y with smooth_win_trace window.
          2. Compute gradient dy/dx.
          3. Smooth gradient with smooth_win_grad window.
          4. Classify each point:
               |grad| < slope_threshold -> FLAT (0)
               grad < 0                 -> UP   (+1)  [image y decreases = chart goes up]
               grad > 0                 -> DOWN (-1)
          5. Scan from right to find end_dir (last non-flat direction).
          6. Scan right-to-left to find where end_dir first appears
             after a different direction -> trend_start.

        Returns
        -------
        (trend_start : int, end_dir : int)
            trend_start - x index (in y coordinate space) where final trend begins
            end_dir     - +1 for UP, -1 for DOWN
        """
        y_s  = self._smooth_1d(y, self.smooth_win_trace)
        dy   = np.gradient(y_s).astype(np.float32)
        dy_s = self._smooth_1d(dy, self.smooth_win_grad)

        def _classify(d: float) -> int:
            if abs(d) < self.slope_threshold:
                return 0
            return 1 if d < 0 else -1          # image y down = chart UP

        dirs = np.array([_classify(d) for d in dy_s], dtype=np.int8)

        # -- find end direction -------------------------------------------
        end_dir = 0
        for i in range(len(dirs) - 1, -1, -1):
            if dirs[i] != 0:
                end_dir = int(dirs[i])
                break
        # Fallback: compare smoothed tail vs near-tail when all points are flat
        if end_dir == 0:
            tail_mean   = float(np.mean(y_s[-max(1, len(y_s) // 10):]))
            before_mean = float(np.mean(y_s[max(0, len(y_s) // 2): max(1, len(y_s) * 9 // 10)]))
            end_dir = 1 if tail_mean < before_mean else -1

        # -- find where that direction begins -----------------------------
        trend_start = 0
        for i in range(len(dirs) - 1, -1, -1):
            if dirs[i] == 0:
                continue
            if dirs[i] != end_dir:
                trend_start = i + 1
                break
        trend_start = max(0, min(len(y) - 2, trend_start))

        return trend_start, end_dir

    def _build_roi(
        self,
        img: np.ndarray,
        comp_full: np.ndarray,
        crop_y0: int,
        x0g: int, x1g: int,
        y0g: int, y1g: int,
    ) -> _ROI:
        """
        Build a tight ROI rectangle at the chart right end.

        Horizontal sizing:
          width = last_w_frac_graph * graph_x_span
          clamped to [18 %, 45 %] of image width
          right edge = x1g + small padding

        Vertical sizing:
          centered on component y-range + 3 % padding
          enforces minimum height = 45 % of image height
        """
        H, W     = img.shape[:2]
        graph_span = max(1, x1g - x0g)
        roi_w      = int(self.last_w_frac_graph * graph_span)
        roi_w      = max(int(0.18 * W), min(int(0.45 * W), roi_w))

        pad_r = max(14, int(W * 0.012))
        x1    = min(W, x1g + pad_r + 1)
        x0    = max(0, x1 - roi_w)

        pad_y   = max(24, int(H * 0.03))
        y0_full = max(0, (y0g + crop_y0) - pad_y)
        y1_full = min(H, (y1g + crop_y0) + pad_y)

        min_h = int(0.45 * H)
        if (y1_full - y0_full) < min_h:
            center  = (y0_full + y1_full) // 2
            y0_full = max(0, center - min_h // 2)
            y1_full = min(H, y0_full + min_h)

        return self._clamp_roi(_ROI(x0, y0_full, x1, y1_full), W, H)


# Backwards-compatible alias so existing imports keep working
ChartLineDetector = ChartDirectionDetector


# ---------------------------------------------------------------------------
# Stand-alone usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Detect trend direction in a chart screenshot.")
    ap.add_argument("--image",  required=True,  help="Path to chart image")
    ap.add_argument("--last-w-frac-graph", type=float, default=0.28,
                    help="Fraction of graph width used as ROI (default 0.28)")
    ap.add_argument("--slope-threshold", type=float, default=0.15,
                    help="Gradient threshold to classify UP/DOWN/NONE (default 0.15)")
    args = ap.parse_args()

    detector = ChartDirectionDetector(
        last_w_frac_graph=args.last_w_frac_graph,
        slope_threshold=args.slope_threshold,
    )

    result = detector.analyze_with_details(args.image)

    if result["success"]:
        print(result["direction"])
    else:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)
