import type { ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./auth-context";
import { ToastProvider } from "./toast-context";
import { TimerProvider } from "./timer-context";
import { ErrorBoundary } from "../shared/components/ErrorBoundary";
import { GlobalKeyboardHandler } from "../shared/components/GlobalKeyboardHandler";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <GlobalKeyboardHandler />
          <ToastProvider>
            <TimerProvider>
              <AuthProvider>{children}</AuthProvider>
            </TimerProvider>
          </ToastProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
