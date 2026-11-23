import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./shared/styles/global.css";
import { AppProviders } from "./app/providers";
import { AppRouter } from "./app/router";

// Brand accent color is managed dynamically per company session in AppLayout


createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders>
      <AppRouter />
    </AppProviders>
  </StrictMode>,
);
