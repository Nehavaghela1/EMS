import { useState } from "react";

/** The client-side half of Spec 10.1's list envelope: `page`/`limit` are
 * request params; `total`/`pages`/`has_next` come back from the server on
 * every `Page[T]` response and are never computed on the client. */
export interface PaginationState {
  page: number;
  limit: number;
}

export function usePagination(initialLimit = 20) {
  const [state, setState] = useState<PaginationState>({ page: 1, limit: initialLimit });

  return {
    ...state,
    setPage: (page: number) => setState((s) => ({ ...s, page })),
    setLimit: (limit: number) => setState({ page: 1, limit }),
    reset: () => setState({ page: 1, limit: initialLimit }),
  };
}
