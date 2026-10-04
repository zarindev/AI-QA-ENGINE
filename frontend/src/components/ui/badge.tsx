import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap [&_svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "bg-slate-500/15 text-muted",
        primary: "bg-primary-soft text-blue-400 light:text-blue-700",
        pass: "bg-green-500/15 text-green-400",
        fail: "bg-red-500/15 text-red-400",
        warn: "bg-amber-500/15 text-amber-400",
        info: "bg-sky-500/15 text-sky-400",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export const severityTone = (s: string) =>
  (({ critical: "fail", major: "warn", minor: "info", trivial: "neutral" }) as const)[s as "critical"] ?? "neutral";

export const statusTone = (s: string) =>
  (
    ({
      completed: "pass",
      done: "pass",
      running: "primary",
      pending: "neutral",
      failed: "fail",
      interrupted: "warn",
      cancelled: "neutral",
      skipped: "neutral",
    }) as const
  )[s as "completed"] ?? "neutral";
