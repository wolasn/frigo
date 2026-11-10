import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Inventory, type Meal, type MealDraft, type MealSlot } from "../api";
import MealDialog, { formatDay, MoveWarningDialog, moveWithCheck } from "../components/agenda/MealDialog";
import { SLOT_LABELS, SLOTS } from "../components/agenda/PlanDialog";
import WeekBalancePanel, { useWeekBalance } from "../components/agenda/WeekBalancePanel";
import SuggestDialog, { type SuggestSettings } from "../components/agenda/SuggestDialog";
import RecipeDetailDialog from "../components/recipes/RecipeDetailDialog";
import { ErrorMessage, primaryButton, secondaryButton } from "../components/ui";
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

type Draft = MealDraft & { key: string; agenda: string; servings: number; rejected: string[] };
const draftKey = (d: { meal_date: string; slot: MealSlot; agenda: string }) => `${d.agenda}|${d.meal_date}|${d.slot}`;

export default function AgendaPage() {
  const [weekStart, setWeekStart] = useState(mondayOf(isoToday()));
  const [meals, setMeals] = useState<Meal[] | null>(null);
  const [pastUnmarked, setPastUnmarked] = useState<Meal[]>([]);
  const [openMeal, setOpenMeal] = useState<Meal | null>(null);
  const [openRecipe, setOpenRecipe] = useState<{ id: string; servings: number } | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [agendaFilter, setAgendaFilter] = useState<string>("all");
  const [highlightKey, setHighlight] = useState<string | null>(null);
  const [sharedInventories, setSharedInventories] = useState<Inventory[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [busySlot, setBusySlot] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dragged = useRef<Meal | null>(null);

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart]);
  const today = isoToday();

  const load = useCallback(() => {
    api.agenda(days[0], days[6]).then(setMeals).catch(() => setError("Impossible de charger l'agenda."));
    api.pastUnmarked().then(setPastUnmarked).catch(() => setPastUnmarked([]));
  }, [days]);
  useEffect(load, [load]);

  useEffect(() => {
    api
      .inventories()
      .then((list) => setSharedInventories(list.filter((i) => i.kind === "shared")))
      .catch(() => setSharedInventories([]));
  }, []);

  const askConfirmation = useCallback(
    (warnings: string[]) => new Promise<boolean>((resolve) => setConfirmation({ warnings, resolve })),
    [],
  );

  // Tous les agendas : le personnel et celui de chaque inventaire partagé, même sans repas cette semaine.
  const agendas = useMemo(() => {
    const map = new Map<string, string>([["personal", "Personnel"]]);
    sharedInventories.forEach((i) => map.set(i.id, i.name));
    (meals ?? []).forEach((m) => map.set(m.agenda_id ?? "personal", m.agenda_name));
    return [...map.entries()];
  }, [meals, sharedInventories]);
  const canPlan = (agendaId: string) =>
    agendaId === "personal" || sharedInventories.some((i) => i.id === agendaId && i.role !== "member");
  const colorOf = (meal: Meal) =>
    meal.agenda_id ? AGENDA_COLORS[Math.max(0, agendas.findIndex(([id]) => id === meal.agenda_id)) % AGENDA_COLORS.length] : "border-l-brand-500";

  const balance = useWeekBalance(weekStart, agendaFilter, meals);
  const highlight = balance?.tiles.find((t) => t.key === highlightKey) ?? null;
  useEffect(() => setHighlight(null), [weekStart]);

  const visible = (meals ?? []).filter((m) => agendaFilter === "all" || (m.agenda_id ?? "personal") === agendaFilter);
  const target = agendaFilter === "all" || agendaFilter === "personal" ? "personal" : agendaFilter;
  const targetName = target === "personal" ? "Personnel" : (agendas.find(([id]) => id === target)?.[1] ?? "partagé");
  const visibleDrafts = drafts.filter((d) => agendaFilter === "all" || d.agenda === agendaFilter);

  function addDrafts(found: MealDraft[], settings: SuggestSettings) {
    setDrafts((current) => {
      const byKey = new Map(current.map((d) => [d.key, d]));
      for (const draft of found) {
        const full = { ...draft, agenda: settings.agenda, servings: settings.servings, rejected: [] as string[] };
        byKey.set(draftKey(full), { ...full, key: draftKey(full) });
      }
      return [...byKey.values()];
    });
  }

  const removeDraft = (key: string) => setDrafts((current) => current.filter((d) => d.key !== key));

  async function changeDraft(draft: Draft) {
    setError(null);
    setBusySlot(draft.key);
    try {
      const rejected = draft.recipe ? [...draft.rejected, draft.recipe.id] : draft.rejected;
      const others = drafts.filter((d) => d.key !== draft.key && d.recipe).map((d) => d.recipe!.id);
      const [next] = await api.suggestMeals({
        days: [draft.meal_date], slots: [draft.slot], agenda: draft.agenda, servings: draft.servings,
        exclude: [...rejected, ...others],
      });
      if (next) setDrafts((current) => current.map((d) => (d.key === draft.key ? { ...d, ...next, rejected } : d)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impossible de proposer autre chose.");
    } finally {
      setBusySlot(null);
    }
  }

  async function suggestSlot(day: string, slot: MealSlot) {
    setError(null);
    const key = draftKey({ agenda: target, meal_date: day, slot });
    setBusySlot(key);
    try {
      const preferences = await api.preferences().catch(() => null);
      const servings = preferences?.default_servings ?? 2;
      const exclude = drafts.filter((d) => d.recipe).map((d) => d.recipe!.id);
      addDrafts(await api.suggestMeals({ days: [day], slots: [slot], agenda: target, servings, exclude }), { agenda: target, servings, slots: [slot] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impossible de proposer un repas.");
    } finally {
      setBusySlot(null);
    }
  }

  async function validate(list: Draft[]) {
    setError(null);
    for (const draft of list) {
      if (!draft.recipe) continue;
      try {
        await api.planMeal({
          recipe_id: draft.recipe.id, meal_date: draft.meal_date, slot: draft.slot, servings: draft.servings,
          shared_inventory_id: draft.agenda === "personal" ? undefined : draft.agenda,
        });
        removeDraft(draft.key);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Planification impossible.");
        break;
      }
    }
    load();
  }

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
        <div className="flex flex-wrap items-center gap-2">
          <button className={primaryButton + " px-3 py-1.5 text-sm"} onClick={() => setSuggesting(true)} disabled={!canPlan(target)} title={canPlan(target) ? undefined : "Seuls les contributeurs et administrateurs planifient dans cet agenda"}>
            Proposer des repas
          </button>
          <button className={secondaryButton + " px-3 py-1.5"} onClick={() => setWeekStart(addDays(weekStart, -7))} aria-label="Semaine précédente">
            ‹
          </button>
          <button className={secondaryButton + " px-3 py-1.5 text-sm"} onClick={() => setWeekStart(mondayOf(today))}>
            Cette semaine
          </button>
          <button className={secondaryButton + " px-3 py-1.5"} onClick={() => setWeekStart(addDays(weekStart, 7))} aria-label="Semaine suivante">
            ›
          </button>
          <WeekPicker weekStart={weekStart} onPick={(day) => setWeekStart(mondayOf(day))} />
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
              onClick={() => {
                setAgendaFilter(id);
                setHighlight(null);
              }}
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

      <WeekBalancePanel balance={balance} selected={highlight} onSelect={setHighlight} />

      {visibleDrafts.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-dashed border-brand-500 bg-brand-50 p-3 text-sm dark:bg-stone-900">
          <span>
            <strong>{visibleDrafts.filter((d) => d.recipe).length} repas proposé(s)</strong>, encadrés en pointillés : rien n'est enregistré tant que tu ne valides pas.
            {visibleDrafts.some((d) => !d.recipe) && (
              <span className="block text-xs text-stone-500">
                Créneaux sans recette : relance « Proposer des repas » en cochant l'IA, ou importe des recettes depuis l'onglet Repas.
              </span>
            )}
          </span>
          <span className="flex gap-2">
            <button className={primaryButton + " px-3 py-1.5"} onClick={() => validate(visibleDrafts)}>
              Valider tout
            </button>
            <button className={secondaryButton + " px-3 py-1.5"} onClick={() => setDrafts((c) => c.filter((d) => !visibleDrafts.includes(d)))}>
              Tout retirer
            </button>
          </span>
        </div>
      )}

      <p className="mb-3 text-sm text-stone-500">
        Glisse un repas vers une autre case pour le déplacer (ou ouvre-le pour changer sa date). Pour en ajouter, planifie-le depuis l'onglet Repas ou utilise « Proposer des repas » (ou le + d'un créneau vide).
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
                  const slotDrafts = visibleDrafts.filter((d) => d.meal_date === day && d.slot === slot);
                  const emptyKey = draftKey({ agenda: target, meal_date: day, slot });
                  return (
                    <div
                      key={slot}
                      onDragOver={(e) => !past && e.preventDefault()}
                      onDrop={() => !past && drop(day, slot)}
                      className="min-h-9 rounded-lg bg-stone-50 p-1 dark:bg-stone-950"
                    >
                      <p className="flex items-center justify-between px-1 text-[11px] uppercase tracking-wide text-stone-400">
                        {SLOT_LABELS[slot]}
                        {!past && canPlan(target) && slotMeals.length === 0 && slotDrafts.length === 0 && (
                          <button
                            className="rounded px-1 text-sm leading-none text-stone-400 hover:bg-stone-200 hover:text-stone-700 dark:hover:bg-stone-800"
                            title="Proposer un repas pour ce créneau"
                            aria-label={`Proposer un repas : ${SLOT_LABELS[slot]}`}
                            disabled={busySlot === emptyKey}
                            onClick={() => suggestSlot(day, slot)}
                          >
                            {busySlot === emptyKey ? "…" : "+"}
                          </button>
                        )}
                      </p>
                      {slotMeals.map((meal) => (
                        <button
                          key={meal.id}
                          draggable={meal.can_edit && meal.status === "planned"}
                          onDragStart={() => (dragged.current = meal)}
                          onClick={() => setOpenMeal(meal)}
                          className={
                            "mt-1 block w-full rounded-md border-l-4 bg-white px-2 py-1 text-left text-sm shadow-sm dark:bg-stone-800 " +
                            colorOf(meal) +
                            (meal.status === "done" ? " line-through opacity-60" : "") +
                            (highlight?.meal_ids.includes(meal.id) ? " ring-2 ring-amber-500" : "")
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
                      {slotDrafts.map((draft) => (
                        <DraftCard
                          key={draft.key}
                          draft={draft}
                          busy={busySlot === draft.key}
                          onOpen={() => draft.recipe && setOpenRecipe({ id: draft.recipe.id, servings: draft.servings })}
                          onValidate={() => validate([draft])}
                          onChange={() => changeDraft(draft)}
                          onRemove={() => removeDraft(draft.key)}
                        />
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
          focus={highlight && highlight.status === "warn" && highlight.meal_ids.includes(openMeal.id) ? highlight : null}
          onChanged={load}
          onClose={() => setOpenMeal(null)}
          askConfirmation={askConfirmation}
          onOpenRecipe={(id, servings) => {
            setOpenMeal(null);
            setOpenRecipe({ id, servings });
          }}
        />
      )}
      {suggesting && (
        <SuggestDialog
          days={days}
          agenda={{ id: target, name: targetName }}
          onDrafts={addDrafts}
          onClose={() => setSuggesting(false)}
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

function DraftCard({
  draft,
  busy,
  onOpen,
  onValidate,
  onChange,
  onRemove,
}: {
  draft: Draft;
  busy: boolean;
  onOpen: () => void;
  onValidate: () => void;
  onChange: () => void;
  onRemove: () => void;
}) {
  const link = "font-medium hover:underline disabled:opacity-50";
  return (
    <div className="mt-1 rounded-md border-2 border-dashed border-brand-500 bg-white px-2 py-1 text-sm dark:bg-stone-800">
      {draft.recipe ? (
        <button className="block w-full text-left" onClick={onOpen}>
          <span className="line-clamp-2">
            {draft.recipe.title}
            {draft.recipe.source === "ai" && (
              <span className="ml-1 rounded bg-violet-100 px-1 text-[10px] font-semibold text-violet-800 dark:bg-violet-950 dark:text-violet-300">IA</span>
            )}
          </span>
          <span className="block text-xs text-stone-500">{draft.reasons.join(" · ")}</span>
        </button>
      ) : (
        <span className="block text-xs text-stone-500">{draft.reasons.join(" ")}</span>
      )}
      <span className="mt-1 flex flex-wrap gap-x-2 text-xs">
        {draft.recipe && (
          <button className={link + " text-brand-700 dark:text-brand-500"} onClick={onValidate} disabled={busy}>
            Valider
          </button>
        )}
        <button className={link + " text-stone-600 dark:text-stone-300"} onClick={onChange} disabled={busy}>
          {busy ? "…" : "Changer"}
        </button>
        <button className={link + " text-stone-500"} onClick={onRemove}>
          Retirer
        </button>
      </span>
    </div>
  );
}

/** Bouton « semaine du … » : ouvre le calendrier du navigateur ; le jour choisi donne sa semaine. */
function WeekPicker({ weekStart, onPick }: { weekStart: string; onPick: (day: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const label = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
  return (
    <span className="relative">
      <button
        className={secondaryButton + " px-3 py-1.5 text-sm"}
        onClick={() => {
          const el = input.current;
          if (!el) return;
          try {
            el.showPicker();
          } catch {
            el.focus();
            el.click();
          }
        }}
        aria-label="Choisir la semaine"
      >
        📅 {label(weekStart)} – {label(addDays(weekStart, 6))}
      </button>
      <input
        ref={input}
        type="date"
        tabIndex={-1}
        aria-hidden
        className="pointer-events-none absolute bottom-0 left-0 h-0 w-0 opacity-0"
        value={weekStart}
        onChange={(e) => e.target.value && onPick(e.target.value)}
      />
    </span>
  );
}
