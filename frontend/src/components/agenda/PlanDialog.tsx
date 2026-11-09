import { useEffect, useState } from "react";
import { api, type Inventory, type MealSlot } from "../../api";
import { isoToday } from "../../format";
import { ErrorMessage, Field, inputClass, Modal, primaryButton } from "../ui";

export const SLOT_LABELS: Record<MealSlot, string> = {
  breakfast: "Petit-déjeuner",
  lunch: "Déjeuner",
  snack: "Encas",
  dinner: "Dîner",
};
export const SLOTS: MealSlot[] = ["breakfast", "lunch", "snack", "dinner"];

/** Planifier une recette ou un reste dans un agenda (personnel ou partagé). */
export default function PlanDialog({
  title,
  recipeId,
  leftoverItemId,
  defaultServings,
  maxServings,
  onPlanned,
  onClose,
}: {
  title: string;
  recipeId?: string;
  leftoverItemId?: string;
  defaultServings: number;
  maxServings?: number;
  onPlanned: () => void;
  onClose: () => void;
}) {
  const [date, setDate] = useState(isoToday());
  const [slot, setSlot] = useState<MealSlot>(new Date().getHours() < 14 ? "lunch" : "dinner");
  const [servings, setServings] = useState(defaultServings);
  const [agendas, setAgendas] = useState<Inventory[]>([]);
  const [agendaId, setAgendaId] = useState("");
  const [shortages, setShortages] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .inventories()
      .then((list) => setAgendas(list.filter((i) => i.kind === "shared" && i.role !== "member")))
      .catch(() => setAgendas([]));
  }, []);

  async function plan() {
    setError(null);
    try {
      const meal = await api.planMeal({
        recipe_id: recipeId,
        leftover_item_id: leftoverItemId,
        meal_date: date,
        slot,
        servings,
        shared_inventory_id: agendaId || undefined,
      });
      onPlanned();
      if (meal.shortages.length) setShortages(meal.shortages.map((s) => s.name));
      else onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Planification impossible.");
    }
  }

  if (shortages) {
    return (
      <Modal title="Repas planifié" onClose={onClose}>
        <p className="mb-2">« {title} » est dans l'agenda, mais il manquera :</p>
        <ul className="mb-4 list-disc pl-5 text-sm text-amber-800 dark:text-amber-300">
          {shortages.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
        <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">Ces manques iront dans la liste de courses.</p>
        <button className={primaryButton} onClick={onClose}>
          Compris
        </button>
      </Modal>
    );
  }

  return (
    <Modal title={`Planifier « ${title} »`} onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date">
            <input type="date" min={isoToday()} className={inputClass} value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Field label="Moment">
            <select className={inputClass} value={slot} onChange={(e) => setSlot(e.target.value as MealSlot)}>
              {SLOTS.map((s) => (
                <option key={s} value={s}>
                  {SLOT_LABELS[s]}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label={leftoverItemId ? "Parts à manger" : "Personnes"}>
          <input
            type="number"
            min={1}
            max={maxServings ?? 999}
            className={inputClass}
            value={servings}
            onChange={(e) => setServings(Math.min(maxServings ?? 999, Math.max(1, Number(e.target.value) || 1)))}
          />
        </Field>
        {agendas.length > 0 && (
          <Field label="Agenda">
            <select className={inputClass} value={agendaId} onChange={(e) => setAgendaId(e.target.value)}>
              <option value="">Personnel</option>
              {agendas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} (partagé)
                </option>
              ))}
            </select>
          </Field>
        )}
        <ErrorMessage message={error} />
        <button className={primaryButton} onClick={plan} disabled={!date}>
          Ajouter à l'agenda
        </button>
      </div>
    </Modal>
  );
}
