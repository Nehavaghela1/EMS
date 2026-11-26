import React, { useRef, useEffect } from "react";

export interface DateInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  type?: "date" | "datetime-local" | "time" | "month";
  error?: boolean;
}

/**
 * Shared DateInput component:
 * - Native date picker opens on double click (or showPicker() when supported)
 * - Click outside or Escape closes/blurs the picker
 * - Cursor is pointer indicating interactivity
 */
export const DateInput: React.FC<DateInputProps> = ({
  type = "date",
  className = "",
  style,
  onKeyDown,
  error,
  ...props
}) => {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDoubleClick = () => {
    if (inputRef.current) {
      if ("showPicker" in HTMLInputElement.prototype && typeof (inputRef.current as any).showPicker === "function") {
        try {
          (inputRef.current as any).showPicker();
        } catch {
          inputRef.current.focus();
        }
      } else {
        inputRef.current.focus();
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      inputRef.current?.blur();
    }
    onKeyDown?.(e);
  };

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (inputRef.current && !inputRef.current.contains(e.target as Node)) {
        if (document.activeElement === inputRef.current) {
          inputRef.current.blur();
        }
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
    };
  }, []);

  return (
    <input
      ref={inputRef}
      type={type}
      className={`input ${error ? "input-error" : ""} ${className}`.trim()}
      style={{
        cursor: "pointer",
        ...style,
      }}
      onDoubleClick={handleDoubleClick}
      onKeyDown={handleKeyDown}
      {...props}
    />
  );
};
