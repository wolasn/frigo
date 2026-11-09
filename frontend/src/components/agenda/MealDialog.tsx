import { useState } from "react";
import { api, type Meal, type MealChange, type MealSlot } from "../../api";
import { isoToday } from "../../format";
import { ErrorMessage, Field, inputClass, Modal, primaryButton, secondaryButton } from "../ui";
import { SLOT_LABELS, SLOTS } from "./PlanDialog";

export function formatDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

/** Confirmation d'un déplacement qui aurait des conséquences. */
export function MoveWarningDialog({
  warnings,
  onConfirm,
  onCancel,
}: {
  warnings: string[];
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal title="Attention, ce déplacement a des conséquences" onClose={onCancel}>
      <ul className="mb-4 list-disc space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-300">
        {warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">Les manques iront dans la liste de courses.</p>
      <div className="flex gap-2">
        <button className={primaryButton} onClick={onConfirm}>
          Déplacer quand même
        </button>
        <button className={secondaryButton} onClick={onCancel}>
          Annuler
        </button>
      </div>
    </Modal>
  );
}

/** Déplace un repas : simulation d'abord, confirmation seulement s'il y a des avertissements. */
export async function moveWithCheck(
  meal: Meal,
  change: MealChange,
  askConfirmation: (warnings: string[]) => Promise<boolean>,
): Promise<boolean> {
  const { warnings } = await api.previewMove(meal.id, change);
  if (warnings.length && !(await askConfirmation(warnings))) return false;
  await api.updateMeal(meal.id, change);
  return true;
}

export default function MealDialog({
  meal,
  onOpenRecipe,
  onChanged,
  onClose,
  askConfirmation,
}: {
  meal: Meal;
  onOpenRecipe: (recipeId: string, servings: number) => void;
  onChanged: () => void;
  onClose: () => void;
  askConfirmation: (warnings: string[]) => Promise<boolean>;
}) {
  const [date, setDate] = useState(meal.meal_date);
  const [slot, setSlot] = useState<MealSlot>(meal.slot);
  const [servings, setServings] = useState(meal.servings);
  const [askLeftovers, setAskLeftovers] = useState(false);
  const [portions, setPortions] = useState("");
  const [error, setError] = useState<string | null>(null);
  const planned = meal.status === "planned";
  const changed = date !== meal.meal_date || slot !== meal.slot || servings !== meal.servings;

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      onChanged();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action impossible.");
    }
  }

  async function save() {
    setError(null);
    try {
      const moved = await moveWithCheck(meal, { meal_date: date, slot, servings }, askConfirmation);
      if (moved) {
        onChanged();
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Modification impossible.");
    }
  }

  return (
    <Modal title={meal.title} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          {SLOT_LABELS[meal.slot]} du {formatDay(meal.meal_date)} · agenda {meal.agenda_name}
          {meal.planned_by && meal.agenda_id && ` · planifié par ${meal.planned_by}`}
          {meal.status === "done" && " · cuisiné"}
        </p>

        {meal.shortages.length > 0 && (
          <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <p className="mb-1 font-medium">Il manquera :</p>
            <ul className="list-disc pl-5">
              {meal.shortages.map((s) => (
                <li key={s.name}>{s.name}</li>
              ))}
            </ul>
          </div>
        )}

        {planned && meal.can_edit && (
          <div className="grid gap-3 sm:grid-cols-3">
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
            <Field label={meal.kind === "leftover" ? "Parts" : "Personnes"}>
              <input
                type="number"
                min={1}
                max={999}
                className={inputClass}
                value={servings}
                onChange={(e) => setServings(Math.min(999, Math.max(1, Number(e.target.value) || 1)))}
              />
            </Field>
          </div>
        )}

        {askLeftovers ? (
          <div className="space-y-2 rounded-lg border border-stone-200 p-3 dark:border-stone-800">
            <p className="text-sm font-medium">Il en reste ? Combien de parts ?</p>
            <input className={inputClass} inputMode="numeric" placeholder="0 = rien" value={portions} onChange={(e) => setPortions(e.target.value)} autoFocus />
            <button
              className={primaryButton}
              onClick={() => run(() => api.mealDone(meal.id, Number(portions) > 0 ? Math.min(999, Math.floor(Number(portions))) : undefined))}
            >
              Valider
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {planned && (
              <button
                className={primaryButton}
                onClick={() => (meal.kind === "recipe" ? setAskLeftovers(true) : run(() => api.mealDone(meal.id)))}
              >
                {meal.kind === "recipe" ? "Cuisiné" : "Mangé"}
              </button>
            )}
            {planned && meal.can_edit && changed && (
              <button className={secondaryButton} onClick={save}>
                Enregistrer les changements
              </button>
            )}
            {meal.recipe_id && (
              <button className={secondaryButton} onClick={() => onOpenRecipe(meal.recipe_id!, meal.servings)}>
                Voir la recette
              </button>
            )}
            {planned && meal.can_edit && (
              <button className="rounded-lg px-3 py-2 text-sm text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-stone-800" onClick={() => run(() => api.cancelMeal(meal.id))}>
                Annuler ce repas
              </button>
            )}
          </div>
        )}
        <ErrorMessage message={error} />
      </div>
    </Modal>
  );
}
