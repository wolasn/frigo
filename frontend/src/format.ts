import type { Item, RemovalReason } from "./api";

const UNIT_LABELS: Record<string, [string, string]> = {
  g: ["g", "g"],
  kg: ["kg", "kg"],
  ml: ["ml", "ml"],
  cl: ["cl", "cl"],
  dl: ["dl", "dl"],
  l: ["L", "L"],
  piece: ["pièce", "pièces"],
  portion: ["part", "parts"],
};

export function unitLabel(unit: string, quantity = 2): string {
  const labels = UNIT_LABELS[unit];
  if (!labels) return unit;
  return quantity > 1 ? labels[1] : labels[0];
}

export function formatQuantity(quantity: number, unit: string): string {
  const value = Number.isInteger(quantity) ? String(quantity) : quantity.toLocaleString("fr-FR", { maximumFractionDigits: 3 });
  return `${value} ${unitLabel(unit, quantity)}`;
}

export function formatDate(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

export function isoToday(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function expiryText(item: Item): string {
  const d = item.days_left;
  switch (item.status) {
    case "expired":
      return d === -1 ? "Périmé depuis hier" : `Périmé depuis ${-d} j`;
    case "best_before_passed":
      return "DDM dépassée : à vérifier";
    case "soon":
      return d === 0 ? "Expire aujourd'hui" : d === 1 ? "Expire demain" : `Expire dans ${d} j`;
    default:
      return `Jusqu'au ${formatDate(item.expires_on)}`;
  }
}

export const STATUS_STYLES: Record<Item["status"], string> = {
  expired: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  soon: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  best_before_passed: "bg-yellow-50 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300",
  ok: "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300",
};

export const REASON_LABELS: Record<RemovalReason, string> = {
  consumed: "Consommé",
  discarded: "Jeté",
  given: "Donné",
  cooked: "Cuisiné",
  other: "Autre",
};
