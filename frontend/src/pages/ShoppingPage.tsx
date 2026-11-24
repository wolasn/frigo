import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, type ShoppingLine, type ShoppingList } from "../api";
import { ErrorMessage, inputClass, primaryButton, secondaryButton, Loading } from "../components/ui";
import { formatDate, formatQuantity, isoToday } from "../format";

function recommendation(line: ShoppingLine): { text: string; style: string } | null {
  if (!line.recommended_purchase_on) return null;
  const when = line.recommended_purchase_on <= isoToday() ? "aujourd'hui" : `le ${formatDate(line.recommended_purchase_on)}`;
  if (line.expiry_risk && line.freeze_from) {
    const from = line.freeze_from <= isoToday() ? "dès aujourd'hui" : `au plus tôt le ${formatDate(line.freeze_from)}`;
    return { text: `À acheter ${when}, ou ${from} et congeler`, style: "text-amber-700 dark:text-amber-400" };
  }
  return line.expiry_risk
    ? { text: `À acheter ${when} (pas avant : périmerait avant le repas)`, style: "text-amber-700 dark:text-amber-400" }
    : { text: `À acheter ${when}`, style: "text-stone-600 dark:text-stone-400" };
}

export default function ShoppingPage() {
  const [lists, setLists] = useState<ShoppingList[] | null>(null);
  const [listId, setListId] = useState("personal");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [newLabel, setNewLabel] = useState("");
  const [purchasing, setPurchasing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    setLoading(true);
    api
      .shopping()
      .then(setLists)
      .catch(() => setError("Impossible de charger la liste de courses."))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const list = lists?.find((l) => l.id === listId) ?? lists?.[0] ?? null;
  const groups = useMemo(() => {
    const map = new Map<string, ShoppingLine[]>();
    (list?.lines ?? []).forEach((line) => map.set(line.aisle, [...(map.get(line.aisle) ?? []), line]));
    return [...map.entries()];
  }, [list]);
  const selected = (list?.lines ?? []).filter((l) => checked.has(l.id));

  function toggle(id: string) {
    setChecked((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function addLine(event: FormEvent) {
    event.preventDefault();
    if (!newLabel.trim() || !list) return;
    try {
      await api.addShoppingLine(newLabel.trim(), list.id === "personal" ? undefined : list.id);
      setNewLabel("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ajout impossible.");
    }
  }

  async function purchase() {
    setError(null);
    setPurchasing(true);
    try {
      const result = await api.purchase(selected.map((l) => l.id));
      setChecked(new Set());
      setMessage(`${result.removed_from_list} article(s) acheté(s), retiré(s) de la liste.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation impossible.");
    } finally {
      setPurchasing(false);
    }
  }

  async function removeLine(line: ShoppingLine) {
    try {
      await api.deleteShoppingLine(line.id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suppression impossible.");
    }
  }

  return (
    <div className="pb-24">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-2xl font-semibold">
          Courses
          {loading && lists !== null && <Loading inline label="Mise à jour…" />}
        </h1>
        {lists && lists.length > 1 && (
          <div className="flex flex-wrap gap-1.5">
            {lists.map((l) => (
              <button
                key={l.id}
                onClick={() => {
                  setListId(l.id);
                  setChecked(new Set());
                }}
                className={
                  "rounded-full px-3 py-1 text-sm " +
                  (list?.id === l.id ? "bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900" : "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300")
                }
              >
                {l.name} · {l.lines.length}
              </button>
            ))}
          </div>
        )}
      </div>

      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">
        La liste réunit tous les ingrédients des repas prévus dans l'agenda à partir d'aujourd'hui (sauf l'eau). Coche ce que tu as
        acheté ou ce que tu as déjà, puis valide : ces articles quittent la liste pour ces repas.
      </p>

      <ErrorMessage message={error} />
      {message && <p className="mb-4 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700 dark:bg-stone-800 dark:text-brand-500">{message}</p>}

      <form onSubmit={addLine} className="mb-6 flex max-w-xl gap-2">
        <input className={inputClass} placeholder="Ajouter un article (ex. papier toilette)" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} maxLength={120} />
        <button type="submit" className={secondaryButton} disabled={!newLabel.trim()}>
          Ajouter
        </button>
      </form>

      {list === null ? (
        <Loading label="Calcul de la liste de courses…" />
      ) : list.lines.length === 0 ? (
        <div className="rounded-xl border border-dashed border-stone-300 p-8 text-center text-stone-600 dark:border-stone-700 dark:text-stone-400">
          Rien à acheter pour les repas prévus. Programme des repas dans l'agenda : leurs ingrédients apparaîtront ici.
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map(([aisle, lines]) => (
            <section key={aisle}>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">{aisle}</h2>
              <ul className="divide-y divide-stone-200 overflow-hidden rounded-xl border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
                {lines.map((line) => {
                  const advice = recommendation(line);
                  return (
                    <li key={line.id} className="flex items-start gap-3 px-4 py-3">
                      <input
                        type="checkbox"
                        checked={checked.has(line.id)}
                        onChange={() => toggle(line.id)}
                        className="mt-1 size-5 shrink-0 accent-brand-600"
                        aria-label={`Acheté : ${line.label}`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className={"font-medium " + (checked.has(line.id) ? "line-through opacity-60" : "")}>
                          {line.label}
                          {line.quantity !== null && line.unit && (
                            <span className="font-normal text-stone-600 dark:text-stone-400"> · {formatQuantity(line.quantity, line.unit)}</span>
                          )}
                          {line.food_id && line.quantity === null && <span className="font-normal text-stone-500"> · quantité à préciser</span>}
                          {line.is_perishable && (
                            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                              périssable
                            </span>
                          )}
                        </p>
                        {line.meals.length > 0 && (
                          <p className="text-xs text-stone-500">Pour : {line.meals.map((m) => `${m.title} (${formatDate(m.meal_date)})`).join(", ")}</p>
                        )}
                        {advice && <p className={"text-xs font-medium " + advice.style}>{advice.text}</p>}
                      </div>
                      {line.origin === "manual" && (
                        <button onClick={() => removeLine(line)} className="text-xs text-stone-500 hover:text-red-600">
                          Retirer
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}

      {selected.length > 0 && (
        <div className="fixed inset-x-0 bottom-0 border-t border-stone-200 bg-white/95 p-3 backdrop-blur dark:border-stone-800 dark:bg-stone-900/95">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-1">
            <span className="text-sm">{selected.length} article(s) coché(s)</span>
            <button className={primaryButton} onClick={purchase} disabled={purchasing}>
              {purchasing ? "…" : "C'est acheté"}
            </button>
          </div>
        </div>
      )}

    </div>
  );
}
