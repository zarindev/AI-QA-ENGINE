import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

export function duration(start?: string | null, end?: string | null): string {
  if (!start) return "—";
  const ms = (end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime();
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export const DOMAIN_LABELS: Record<string, string> = {
  healthcare: "Healthcare",
  rental: "Rental",
  ecommerce: "E-commerce",
  education: "Education",
  hr: "HR",
  crm: "CRM",
  restaurant: "Restaurant",
  real_estate: "Real estate",
  banking: "Banking",
  booking: "Booking",
  portfolio: "Portfolio",
  blog: "Blog",
  other: "Other",
};
