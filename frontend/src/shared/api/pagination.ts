/** The standard list envelope every list endpoint returns (Spec 10.1) —
 * the frontend never invents a different shape for this. */
export interface Page<T> {
  items: T[];
  page: number;
  limit: number;
  total: number;
  pages: number;
  has_next: boolean;
}
