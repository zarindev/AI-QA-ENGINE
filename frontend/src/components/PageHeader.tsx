import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";

export function PageHeader({
  title,
  description,
  crumbs = [],
  actions,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  crumbs?: { label: string; to: string }[];
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-7">
      {crumbs.length > 0 && (
        <nav className="mb-2 flex items-center gap-1 text-xs text-faint" aria-label="Breadcrumb">
          {crumbs.map((c) => (
            <span key={c.to} className="flex items-center gap-1">
              <Link to={c.to} className="hover:text-fg">{c.label}</Link>
              <ChevronRight className="size-3" />
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <div className="mt-1 text-sm text-muted">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
