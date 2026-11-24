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
