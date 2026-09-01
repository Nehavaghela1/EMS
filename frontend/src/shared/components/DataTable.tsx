import type { ReactNode } from "react";
import type { Page } from "../api/pagination";
import { parseApiError } from "../api/errors";
import { EmptyState } from "./EmptyState";

export interface DataTableColumn<T> {
  key: string;
  label: string;
  sortable?: boolean;
  render: (row: T) => ReactNode;
}

interface Props<T> {
  columns: DataTableColumn<T>[];
  page?: Page<T>;
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  currentPage: number;
  onPageChange: (page: number) => void;
  sort: string | null;
  onSortChange: (sort: string) => void;
  emptyMessage?: string;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
}

/**
 * One table, reused by every list page (Spec 14.4): search lives outside
 * this component (a `PageHeader` action or a filter bar), this owns sort,
 * pagination, and the four required states — loading, error, empty,
 * content. Consumes the standard `Page[T]` envelope directly, never a
 * client-invented shape.
 */
export function DataTable<T>({
  columns,
  page,
  isLoading,
  isError,
  error,
  currentPage,
  onPageChange,
  sort,
  onSortChange,
  emptyMessage = "Nothing here yet.",
  rowKey,
  onRowClick,
}: Props<T>) {
  function headerClick(col: DataTableColumn<T>) {
    if (!col.sortable) return;
    const descending = sort === `-${col.key}`;
    onSortChange(descending ? col.key : `-${col.key}`);
  }

  function sortIndicator(col: DataTableColumn<T>): string {
    if (!col.sortable) return "";
    if (sort === col.key) return " ▲";
    if (sort === `-${col.key}`) return " ▼";
    return "";
  }

  return (
    <div className="stack">
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={col.sortable ? "sortable" : undefined}
                  onClick={() => headerClick(col)}
                >
                  {col.label}
                  {sortIndicator(col)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={columns.length}>
                  <div className="row" style={{ padding: "16px 0" }}>
                    <div className="spinner" />
                    <span className="text-muted">Loading…</span>
                  </div>
                </td>
              </tr>
            )}
            {!isLoading && isError && (
              <tr>
                <td colSpan={columns.length}>
                  <div className="alert alert-error" style={{ margin: "8px 0" }}>
                    {parseApiError(error).message}
                  </div>
                </td>
              </tr>
            )}
            {!isLoading && !isError && page && page.items.length === 0 && (
              <tr>
                <td colSpan={columns.length}>
                  <EmptyState message={emptyMessage} />
                </td>
              </tr>
            )}
            {!isLoading &&
              !isError &&
              page?.items.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  style={onRowClick ? { cursor: "pointer" } : undefined}
                >
                  {columns.map((col) => (
                    <td key={col.key}>{col.render(row)}</td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
        {!isLoading && !isError && page && page.total > 0 && (
          <div className="pagination">
            <span>
              {page.total} total · page {page.page} of {page.pages}
            </span>
            <button
              className="btn btn-sm"
              disabled={page.page <= 1}
              onClick={() => onPageChange(currentPage - 1)}
            >
              Previous
            </button>
            <button className="btn btn-sm" disabled={!page.has_next} onClick={() => onPageChange(currentPage + 1)}>
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
