import type { ReactNode } from "react";

interface Props {
  title: string;
  breadcrumb?: string;
  action?: ReactNode;
  className?: string;
}

export function PageHeader({ title, breadcrumb, action, className }: Props) {
  return (
    <div className={`page-header row-between page-header-responsive ${className || ""}`.trim()}>
      <div>
        {breadcrumb && <div className="breadcrumb">{breadcrumb}</div>}
        <h1>{title}</h1>
      </div>
      {action}
    </div>
  );
}
