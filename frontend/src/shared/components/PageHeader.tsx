import type { ReactNode } from "react";

interface Props {
  title: string;
  breadcrumb?: string;
  action?: ReactNode;
}

export function PageHeader({ title, breadcrumb, action }: Props) {
  return (
    <div className="page-header row-between">
      <div>
        {breadcrumb && <div className="breadcrumb">{breadcrumb}</div>}
        <h1>{title}</h1>
      </div>
      {action}
    </div>
  );
}
