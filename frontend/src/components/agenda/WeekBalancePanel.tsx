import { useEffect, useState } from "react";
import { api, type BalanceTile, type WeekBalance } from "../../api";

const STATUS_STYLE: Record<BalanceTile["status"], string> = {
  good: "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950",
  warn: "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950",
  info: "border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900",
};
const STATUS_ICON: Record<BalanceTile["status"], string> = { good: "✓", warn: "⚠", info: "ℹ" };

const OPEN_KEY = "frigo.balance.open";

function readOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) !== "0";
  } catch {
    return true;
  }
}

/** Bilan nutritionnel de la semaine affichée, selon le filtre d'agenda. Un clic sur une tuile met en
 * évidence les repas concernés dans la grille. */
export function useWeekBalance(weekStart: string, agenda: string, refreshKey: unknown): WeekBalance | null {
  const [balance, setBalance] = useState<WeekBalance | null>(null);
  useEffect(() => {
    let current = true;
    api
      .weekBalance(weekStart, agenda)
      .then((b) => current && setBalance(b))
      .catch(() => current && setBalance(null));
    return () => {
      current = false;
    };
  }, [weekStart, agenda, refreshKey]);
  return balance;
}

export default function WeekBalancePanel({
  balance,
  selected,
  onSelect,
}: {
  balance: WeekBalance | null;
  selected: BalanceTile | null;
  onSelect: (key: string | null) => void;
}) {
  const [open, setOpen] = useState(readOpen);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (!next) onSelect(null);
    try {
      localStorage.setItem(OPEN_KEY, next ? "1" : "0");
    } catch {
      /* préférence non mémorisée */
    }
  }

  if (!balance) return null;
  const warnings = balance.tiles.filter((t) => t.status === "warn").length;

  return (
    <section className="mb-5 rounded-xl border border-stone-200 bg-white p-3 dark:border-stone-800 dark:bg-stone-900">
      <button className="flex w-full items-center justify-between gap-2 text-left" onClick={toggle} aria-expanded={open}>
        <span>
          <span className="font-semibold">Équilibre de la semaine</span>
          <span className="ml-2 text-sm text-stone-500">
            {balance.meal_count === 0
              ? "aucun repas prévu"
              : warnings
                ? `${warnings} point(s) à améliorer`
                : "bien équilibrée"}
          </span>
        </span>
        <span className="text-stone-400">{open ? "▲" : "▼"}</span>
      </button>

      {open && balance.meal_count > 0 && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {balance.tiles.map((tile) => {
              const active = selected?.key === tile.key;
              return (
                <button
                  key={tile.key}
                  onClick={() => onSelect(active ? null : tile.key)}
                  className={
                    "rounded-lg border p-2.5 text-left text-sm transition " +
                    STATUS_STYLE[tile.status] +
                    (active ? " ring-2 ring-brand-500" : " hover:shadow-sm")
                  }
                >
                  <span className="flex items-start justify-between gap-1 text-xs text-stone-600 dark:text-stone-300">
                    {tile.label}
                    <span aria-hidden>{STATUS_ICON[tile.status]}</span>
                  </span>
                  <span className="mt-0.5 block text-base font-semibold">{tile.value}</span>
                  <span className="block text-xs text-stone-500">Repère : {tile.target}</span>
                </button>
              );
            })}
          </div>
          {selected && (
            <p className="mt-3 rounded-lg bg-stone-50 p-2.5 text-sm dark:bg-stone-950">
              <span className="font-medium">{selected.label} : </span>
              {selected.hint}
              {selected.meal_ids.length > 0 && (
                <span className="text-stone-500"> Les repas concernés sont encadrés ; ouvre-en un pour voir des alternatives.</span>
              )}
            </p>
          )}
          <p className="mt-2 text-xs text-stone-500">
            Par personne, d'après les repas de l'agenda et les repères du PNNS (Santé publique France). Conseils généraux et
            indicatifs, sans valeur médicale.
            {balance.unanalyzed_meal_ids.length > 0 &&
              ` ${balance.unanalyzed_meal_ids.length} repas non analysé(s) : ingrédients non reconnus.`}
          </p>
        </>
      )}
    </section>
  );
}
