import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./shared/styles/global.css";
import { AppProviders } from "./app/providers";
import { AppRouter } from "./app/router";

// Restore custom brand accent color immediately upon boot
try {
  const savedBrandColor = localStorage.getItem("ems_brand_accent_color");
  if (savedBrandColor) {
    document.documentElement.style.setProperty("--color-primary", savedBrandColor);
  }
} catch {
  // Ignore localStorage access failures in restricted environments
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders>
      <AppRouter />
    </AppProviders>
  </StrictMode>,
);
