import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Meal, type MealSlot } from "../api";
import MealDialog, { formatDay, MoveWarningDialog, moveWithCheck } from "../components/agenda/MealDialog";
import { SLOT_LABELS, SLOTS } from "../components/agenda/PlanDialog";
import RecipeDetailDialog from "../components/recipes/RecipeDetailDialog";
import { ErrorMessage, secondaryButton } from "../components/ui";
import { isoToday } from "../format";

const AGENDA_COLORS = [
  "border-l-sky-500",
  "border-l-violet-500",
  "border-l-rose-500",
  "border-l-amber-500",
  "border-l-teal-500",
];

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function mondayOf(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return addDays(iso, -((d.getDay() + 6) % 7));
}

type Confirmation = { warnings: string[]; resolve: (ok: boolean) => void } | null;

export default function AgendaPage() {
  const [weekStart, setWeekStart] = useState(mondayOf(isoToday()));
  const [meals, setMeals] = useState<Meal[] | null>(null);
  const [pastUnmarked, setPastUnmarked] = useState<Meal[]>([]);
  const [openMeal, setOpenMeal] = useState<Meal | null>(null);
  const [openRecipe, setOpenRecipe] = useState<{ id: string; servings: number } | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [agendaFilter, setAgendaFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);
  const dragged = useRef<Meal | null>(null);

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart]);
  const today = isoToday();

  const load = useCallback(() => {
    api.agenda(days[0], days[6]).then(setMeals).catch(() => setError("Impossible de charger l'agenda."));
    api.pastUnmarked().then(setPastUnmarked).catch(() => setPastUnmarked([]));
  }, [days]);
  useEffect(load, [load]);

  const askConfirmation = useCallback(
    (warnings: string[]) => new Promise<boolean>((resolve) => setConfirmation({ warnings, resolve })),
    [],
  );

  const agendas = useMemo(() => {
    const map = new Map<string, string>();
    (meals ?? []).forEach((m) => map.set(m.agenda_id ?? "personal", m.agenda_name));
    return [...map.entries()];
  }, [meals]);
  const colorOf = (meal: Meal) =>
    meal.agenda_id ? AGENDA_COLORS[Math.max(0, agendas.findIndex(([id]) => id === meal.agenda_id)) % AGENDA_COLORS.length] : "border-l-brand-500";

  const visible = (meals ?? []).filter((m) => agendaFilter === "all" || (m.agenda_id ?? "personal") === agendaFilter);

  async function drop(day: string, slot: MealSlot) {
    const meal = dragged.current;
    dragged.current = null;
    if (!meal || (meal.meal_date === day && meal.slot === slot)) return;
    setError(null);
    try {
      if (await moveWithCheck(meal, { meal_date: day, slot }, askConfirmation)) load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Déplacement impossible.");
    }
  }

  async function resolvePast(meal: Meal, done: boolean) {
    try {
      await (done ? api.mealDone(meal.id) : api.cancelMeal(meal.id));
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action impossible.");
    }
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Agenda</h1>
        <div className="flex items-center gap-2">
          <button className={secondaryButton + " px-3 py-1.5"} onClick={() => setWeekStart(addDays(weekStart, -7))} aria-label="Semaine précédente">
            ‹
          </button>
          <button className={secondaryButton + " px-3 py-1.5 text-sm"} onClick={() => setWeekStart(mondayOf(today))}>
            Cette semaine
          </button>
          <button className={secondaryButton + " px-3 py-1.5"} onClick={() => setWeekStart(addDays(weekStart, 7))} aria-label="Semaine suivante">
            ›
          </button>
        </div>
      </div>

      {pastUnmarked.length > 0 && (
        <div className="mb-5 rounded-xl bg-amber-50 p-4 text-sm dark:bg-amber-950">
          <p className="mb-2 font-medium text-amber-900 dark:text-amber-200">Ces repas sont passés : cuisinés ou annulés ?</p>
          <ul className="space-y-1.5">
            {pastUnmarked.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {m.title} · {SLOT_LABELS[m.slot].toLowerCase()} du {formatDay(m.meal_date)}
                </span>
                <span className="flex gap-2">
                  <button className="font-medium text-brand-700 hover:underline dark:text-brand-500" onClick={() => resolvePast(m, true)}>
                    {m.kind === "recipe" ? "Cuisiné" : "Mangé"}
                  </button>
                  {m.can_edit && (
                    <button className="text-stone-600 hover:underline dark:text-stone-300" onClick={() => resolvePast(m, false)}>
                      Annulé
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {agendas.length > 1 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {[["all", "Tous les agendas"] as [string, string], ...agendas].map(([id, name]) => (
            <button
              key={id}
              onClick={() => setAgendaFilter(id)}
              className={
                "rounded-full px-3 py-1 text-sm " +
                (agendaFilter === id ? "bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900" : "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300")
              }
            >
              {name}
            </button>
          ))}
        </div>
      )}

      <ErrorMessage message={error} />

      <p className="mb-3 text-sm text-stone-500">
        Glisse un repas vers une autre case pour le déplacer (ou ouvre-le pour changer sa date). Pour en ajouter, planifie-le depuis l'onglet Repas.
      </p>

      <div className="grid gap-3 lg:grid-cols-7">
        {days.map((day) => {
          const past = day < today;
          return (
            <section
              key={day}
              className={
                "rounded-xl border bg-white p-2 dark:bg-stone-900 " +
                (day === today ? "border-brand-500" : "border-stone-200 dark:border-stone-800") +
                (past ? " opacity-60" : "")
              }
            >
              <h2 className="mb-2 px-1 text-sm font-semibold capitalize">
                {new Date(`${day}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" })}
              </h2>
              <div className="space-y-1.5">
                {SLOTS.map((slot) => {
                  const slotMeals = visible.filter((m) => m.meal_date === day && m.slot === slot).sort((a, b) => a.position - b.position);
                  return (
                    <div
                      key={slot}
                      onDragOver={(e) => !past && e.preventDefault()}
                      onDrop={() => !past && drop(day, slot)}
                      className="min-h-9 rounded-lg bg-stone-50 p-1 dark:bg-stone-950"
                    >
                      <p className="px-1 text-[11px] uppercase tracking-wide text-stone-400">{SLOT_LABELS[slot]}</p>
                      {slotMeals.map((meal) => (
                        <button
                          key={meal.id}
                          draggable={meal.can_edit && meal.status === "planned"}
                          onDragStart={() => (dragged.current = meal)}
                          onClick={() => setOpenMeal(meal)}
                          className={
                            "mt-1 block w-full rounded-md border-l-4 bg-white px-2 py-1 text-left text-sm shadow-sm dark:bg-stone-800 " +
                            colorOf(meal) +
                            (meal.status === "done" ? " line-through opacity-60" : "")
                          }
                        >
                          <span className="line-clamp-2">{meal.title}</span>
                          <span className="text-xs text-stone-500">
                            {meal.servings} {meal.kind === "leftover" ? "part(s)" : "pers."}
                            {meal.agenda_id && ` · ${meal.agenda_name}`}
                          </span>
                          {meal.shortages.length > 0 && (
                            <span className="block text-xs font-medium text-amber-700 dark:text-amber-400">⚠ {meal.shortages.length} manque(s)</span>
                          )}
                        </button>
                      ))}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>

      {openMeal && (
        <MealDialog
          meal={openMeal}
          onChanged={load}
          onClose={() => setOpenMeal(null)}
          askConfirmation={askConfirmation}
          onOpenRecipe={(id, servings) => {
            setOpenMeal(null);
            setOpenRecipe({ id, servings });
          }}
        />
      )}
      {openRecipe && (
        <RecipeDetailDialog recipeId={openRecipe.id} initialServings={openRecipe.servings} onChanged={load} onClose={() => setOpenRecipe(null)} />
      )}
      {confirmation && (
        <MoveWarningDialog
          warnings={confirmation.warnings}
          onConfirm={() => {
            confirmation.resolve(true);
            setConfirmation(null);
          }}
          onCancel={() => {
            confirmation.resolve(false);
            setConfirmation(null);
          }}
        />
      )}
    </div>
  );
}
