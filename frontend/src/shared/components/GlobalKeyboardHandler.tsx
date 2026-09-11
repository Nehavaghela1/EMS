import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/**
 * Global Keyboard Navigation Controller:
 * 1. Escape Key:
 *    - If a modal or dialog is open (.modal-backdrop or [role="dialog"]), close it (triggers close button / cancel / click backdrop).
 *    - If an input/select/textarea is focused with no modal, blur focus.
 *    - If on a child/detail page with no modal open, go back in history.
 * 2. Enter Key:
 *    - Inside form inputs (except multi-line textareas and buttons), pressing Enter
 *      automatically advances focus to the next empty input or next editable field,
 *      or submits the form if on the last field.
 */
export function GlobalKeyboardHandler() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // ─────────────────────────────────────────────────────────────
      // 1. ESCAPE KEY BEHAVIOR
      // ─────────────────────────────────────────────────────────────
      if (e.key === "Escape") {
        // Find if any modal backdrop or dialog is currently present in DOM
        const backdrops = Array.from(
          document.querySelectorAll<HTMLElement>(".modal-backdrop, [role='dialog']")
        );
        const visibleBackdrops = backdrops.filter(
          (b) => b.offsetParent !== null || window.getComputedStyle(b).display !== "none"
        );

        if (visibleBackdrops.length > 0) {
          // Top-most modal is the last one in DOM
          const topModal = visibleBackdrops[visibleBackdrops.length - 1];

          // 1. Try finding a close button (.modal-close-btn or button with ✕ / Close)
          const closeBtn = topModal.querySelector<HTMLElement>(
            ".modal-close-btn, button[title='Close'], button[aria-label='Close']"
          );
          if (closeBtn && !closeBtn.hasAttribute("disabled")) {
            e.preventDefault();
            e.stopPropagation();
            closeBtn.click();
            return;
          }

          // 2. Try finding a Cancel button
          const buttons = Array.from(topModal.querySelectorAll<HTMLButtonElement>("button"));
          const cancelBtn = buttons.find((btn) => {
            const text = btn.textContent?.trim().toLowerCase();
            return (text === "cancel" || text === "dismiss" || text === "close") && !btn.disabled;
          });
          if (cancelBtn) {
            e.preventDefault();
            e.stopPropagation();
            cancelBtn.click();
            return;
          }

          // 3. Fallback: click the backdrop itself
          e.preventDefault();
          e.stopPropagation();
          topModal.click();
          return;
        }

        // If an input is focused, blur it
        const active = document.activeElement as HTMLElement | null;
        if (
          active &&
          (active.tagName === "INPUT" ||
            active.tagName === "TEXTAREA" ||
            active.tagName === "SELECT")
        ) {
          active.blur();
          return;
        }

        // If no modal is open and we're not on dashboard/login, navigate back
        if (
          location.pathname !== "/dashboard" &&
          location.pathname !== "/login" &&
          window.history.length > 1
        ) {
          e.preventDefault();
          navigate(-1);
          return;
        }
      }

      // ─────────────────────────────────────────────────────────────
      // 2. ENTER KEY BEHAVIOR IN FORMS
      // ─────────────────────────────────────────────────────────────
      if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        const active = document.activeElement as HTMLElement | null;
        if (!active) return;

        // Never interfere with multiline textareas or buttons
        if (active.tagName === "TEXTAREA") return;
        if (active.tagName === "BUTTON") return;

        // If inside an input or select
        if (active.tagName === "INPUT" || active.tagName === "SELECT") {
          const inputEl = active as HTMLInputElement;

          // Don't interfere with checkboxes/radios
          if (inputEl.type === "checkbox" || inputEl.type === "radio") return;

          const form = active.closest("form");
          if (!form) return;

          // Query all visible, interactive form fields
          const formElements = Array.from(
            form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
              "input:not([type='hidden']):not([type='submit']):not([disabled]), select:not([disabled]), textarea:not([disabled])"
            )
          ).filter(
            (el) => el.offsetParent !== null && window.getComputedStyle(el).display !== "none"
          );

          const currentIndex = formElements.indexOf(active as any);
          if (currentIndex >= 0 && currentIndex < formElements.length - 1) {
            // First priority: find next empty field
            let targetElement: HTMLElement | null = null;
            for (let i = currentIndex + 1; i < formElements.length; i++) {
              const el = formElements[i];
              if (!el.value || el.value.trim() === "") {
                targetElement = el;
                break;
              }
            }

            // If no empty field after current, choose immediate next field
            if (!targetElement) {
              targetElement = formElements[currentIndex + 1];
            }

            if (targetElement) {
              e.preventDefault();
              targetElement.focus();
              if (targetElement instanceof HTMLInputElement && typeof targetElement.select === "function") {
                targetElement.select();
              }
              return;
            }
          }

          // If on the last field, trigger submit button
          const submitBtn = form.querySelector<HTMLButtonElement>(
            "button[type='submit']:not([disabled]), input[type='submit']:not([disabled])"
          );
          if (submitBtn && currentIndex === formElements.length - 1) {
            e.preventDefault();
            submitBtn.click();
          }
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown, true); // capture phase
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [navigate, location]);

  return null;
}
