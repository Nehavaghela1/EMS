/**
 * Fixed categorical palette for charts.
 * Order is validated for color-blind separation in light and dark mode.
 * Never cycled, never recolored when filters change series count.
 * A 9th series folds into "Other" (color 8 or distinct muted tone).
 */
export const CATEGORICAL_PALETTE = [
  "#3b5bdb", // 1
  "#e8590c", // 2
  "#1098ad", // 3
  "#ae3ec9", // 4
  "#2f9e44", // 5
  "#1864ab", // 6 (in dark mode carries a visible text label)
  "#c2255c", // 7
  "#5c940d", // 8
] as const;

export const OTHER_SERIES_COLOR = "#868e96";

export function getSeriesColor(index: number): string {
  if (index >= 0 && index < CATEGORICAL_PALETTE.length) {
    return CATEGORICAL_PALETTE[index];
  }
  return OTHER_SERIES_COLOR;
}
