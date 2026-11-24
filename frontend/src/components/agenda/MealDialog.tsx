import { useState } from "react";
import { api, type Meal, type MealAlternative, type MealSlot } from "../../api";
import { ErrorMessage, Field, inputClass, Modal, secondaryButton } from "../ui";
import { SLOT_LABELS, SLOTS } from "./PlanDialog";

export function formatDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

/** Un repas de l'agenda : le déplacer (toutes dates), changer le nombre de personnes, le remplacer ou le retirer. */
export default function MealDialog({
  meal,
  onOpenRecipe,
  onChanged,
  onClose,
  focus,
}: {
  meal: Meal;
  focus?: { key: string; label: string } | null;
  onOpenRecipe: (recipeRef: string, servings: number) => void;
  onChanged: () => void;
  onClose: () => void;
}) {
  const [date, setDate] = useState(meal.meal_date);
  const [slot, setSlot] = useState<MealSlot>(meal.slot);
  const [servings, setServings] = useState(meal.servings);
  const [alternatives, setAlternatives] = useState<MealAlternative[] | null>(null);
  const [loadingAlternatives, setLoadingAlternatives] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  async function showAlternatives() {
    setError(null);
    setLoadingAlternatives(true);
    try {
      setAlternatives(await api.mealAlternatives(meal.id, focus?.key));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impossible de chercher des alternatives.");
    } finally {
      setLoadingAlternatives(false);
    }
  }

  return (
    <Modal title={meal.title} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          {SLOT_LABELS[meal.slot]} du {formatDay(meal.meal_date)} · agenda {meal.agenda_name}
          {meal.planned_by && meal.agenda_id && ` · programmé par ${meal.planned_by}`}
        </p>

        {meal.can_edit && (
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Date">
              <input type="date" className={inputClass} value={date} onChange={(e) => setDate(e.target.value)} />
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
            <Field label="Personnes">
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

        <div className="flex flex-wrap gap-2">
          {meal.can_edit && changed && (
            <button className={secondaryButton} onClick={() => run(() => api.updateMeal(meal.id, { meal_date: date, slot, servings }))}>
              Enregistrer les changements
            </button>
          )}
          <button className={secondaryButton} onClick={() => onOpenRecipe(meal.recipe_id, meal.servings)}>
            Voir la recette
          </button>
          {meal.can_edit && (
            <button
              className="rounded-lg px-3 py-2 text-sm text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-stone-800"
              onClick={() => run(() => api.removeMeal(meal.id))}
            >
              Retirer ce repas
            </button>
          )}
        </div>

        {meal.can_edit && (
          <AlternativesSection
            focusLabel={focus?.label}
            alternatives={alternatives}
            loading={loadingAlternatives}
            onSearch={showAlternatives}
            onReplace={(ref) => run(() => api.replaceMeal(meal.id, ref))}
            onOpenRecipe={(ref) => onOpenRecipe(ref, meal.servings)}
          />
        )}
        <ErrorMessage message={error} />
      </div>
    </Modal>
  );
}

function AlternativesSection({
  focusLabel,
  alternatives,
  loading,
  onSearch,
  onReplace,
  onOpenRecipe,
}: {
  focusLabel?: string;
  alternatives: MealAlternative[] | null;
  loading: boolean;
  onSearch: () => void;
  onReplace: (recipeRef: string) => void;
  onOpenRecipe: (recipeRef: string) => void;
}) {
  if (alternatives === null) {
    return (
      <button className="text-sm font-medium text-brand-700 hover:underline disabled:opacity-60 dark:text-brand-500" onClick={onSearch} disabled={loading}>
        {loading ? "Recherche…" : `Alternatives mieux équilibrées${focusLabel ? ` (${focusLabel.toLowerCase()})` : ""}`}
      </button>
    );
  }
  return (
    <div className="rounded-lg border border-stone-200 p-3 dark:border-stone-800">
      <p className="mb-2 text-sm font-medium">Alternatives mieux équilibrées{focusLabel ? ` · ${focusLabel}` : ""}</p>
      {alternatives.length === 0 ? (
        <p className="text-sm text-stone-500">
          Aucune de tes recettes (créées, épinglées ou favorites) ne fait mieux pour ce repas. Clique sur le moment dans l'agenda pour en
          chercher une sur les sites.
        </p>
      ) : (
        <ul className="space-y-2">
          {alternatives.map(({ recipe, reasons }) => (
            <li key={recipe.id} className="flex items-start justify-between gap-2 text-sm">
              <button className="text-left" onClick={() => onOpenRecipe(recipe.id)}>
                <span className="font-medium hover:underline">{recipe.title}</span>
                {recipe.source === "ai" && <span className="ml-1 rounded bg-violet-100 px-1 text-[10px] font-semibold text-violet-800 dark:bg-violet-950 dark:text-violet-300">IA</span>}
                <span className="block text-xs text-stone-500">{reasons.join(" · ")}</span>
              </button>
              <button className={secondaryButton + " shrink-0 px-2.5 py-1 text-xs"} onClick={() => onReplace(recipe.id)}>
                Remplacer
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
