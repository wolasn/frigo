import { useState } from "react";
import { api, type Meal, type MealAlternative, type MealChange, type MealSlot } from "../../api";
import { isoToday } from "../../format";
import { ErrorMessage, Field, inputClass, Modal, primaryButton, secondaryButton } from "../ui";
import { SLOT_LABELS, SLOTS } from "./PlanDialog";

export function formatDay(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

/** Confirmation d'un déplacement ou d'un remplacement qui aurait des conséquences. */
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
    <Modal title="Attention, ce changement a des conséquences" onClose={onCancel}>
      <ul className="mb-4 list-disc space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-300">
        {warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">Les manques iront dans la liste de courses.</p>
      <div className="flex gap-2">
        <button className={primaryButton} onClick={onConfirm}>
          Continuer quand même
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
  focus,
}: {
  meal: Meal;
  focus?: { key: string; label: string } | null;
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
  const [alternatives, setAlternatives] = useState<MealAlternative[] | null>(null);
  const [loadingAlternatives, setLoadingAlternatives] = useState(false);
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

  async function replace(recipeId: string) {
    setError(null);
    try {
      const { warnings } = await api.replaceMeal(meal.id, recipeId, false);
      if (warnings.length && !(await askConfirmation(warnings))) return;
      await api.replaceMeal(meal.id, recipeId, true);
      onChanged();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Remplacement impossible.");
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

        {planned && meal.can_edit && meal.kind === "recipe" && (
          <AlternativesSection
            focusLabel={focus?.label}
            alternatives={alternatives}
            loading={loadingAlternatives}
            onSearch={showAlternatives}
            onReplace={replace}
            onOpenRecipe={(id) => onOpenRecipe(id, meal.servings)}
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
  onReplace: (recipeId: string) => void;
  onOpenRecipe: (recipeId: string) => void;
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
          Aucune recette connue ne fait mieux pour ce repas. Importe ou invente d'autres recettes depuis l'onglet Repas.
        </p>
      ) : (
        <ul className="space-y-2">
          {alternatives.map(({ recipe, reasons, in_stock }) => (
            <li key={recipe.id} className="flex items-start justify-between gap-2 text-sm">
              <button className="text-left" onClick={() => onOpenRecipe(recipe.id)}>
                <span className="font-medium hover:underline">{recipe.title}</span>
                {recipe.source === "ai" && <span className="ml-1 rounded bg-violet-100 px-1 text-[10px] font-semibold text-violet-800 dark:bg-violet-950 dark:text-violet-300">IA</span>}
                <span className={"block text-xs " + (in_stock ? "text-emerald-700 dark:text-emerald-400" : "text-stone-500")}>{reasons.join(" · ")}</span>
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
