import { useEffect, useState } from "react";
import { api, type MealDraft, type MealSlot } from "../../api";
import { isoToday } from "../../format";
import { ErrorMessage, Field, inputClass, Modal, primaryButton, secondaryButton } from "../ui";
import { SLOT_LABELS, SLOTS } from "./PlanDialog";

export type SuggestSettings = { agenda: string; servings: number; slots: MealSlot[] };

const AI_MAX = 3;

/** Choix de ce qu'il faut proposer : la semaine ou un jour, les moments, le nombre de personnes, l'IA en option. */
export default function SuggestDialog({
  days,
  agenda,
  onDrafts,
  onClose,
}: {
  days: string[];
  agenda: { id: string; name: string };
  onDrafts: (drafts: MealDraft[], settings: SuggestSettings) => void;
  onClose: () => void;
}) {
  const today = isoToday();
  const futureDays = days.filter((d) => d >= today);
  const [scope, setScope] = useState<"week" | "day">("week");
  const [day, setDay] = useState(futureDays[0] ?? days[0]);
  const [slots, setSlots] = useState<MealSlot[]>(["lunch", "dinner"]);
  const [servings, setServings] = useState(2);
  const [diet, setDiet] = useState("none");
  const [useAi, setUseAi] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .preferences()
      .then((p) => {
        setServings(p.default_servings);
        setDiet(p.diet);
      })
      .catch(() => undefined);
  }, []);

  function toggleSlot(slot: MealSlot) {
    setSlots((current) => (current.includes(slot) ? current.filter((s) => s !== slot) : [...current, slot]));
  }

  async function submit() {
    setError(null);
    const chosenDays = scope === "week" ? futureDays : [day];
    try {
      let prefer: string[] = [];
      if (useAi) {
        setBusy("L'IA invente des recettes équilibrées… (jusqu'à une minute)");
        const cards = await api.generateRecipes({
          count: Math.min(AI_MAX, chosenDays.length * slots.length),
          servings,
          max_purchases: 2,
          diet,
          wish: "repas équilibrés et variés : légumes, légumineuses ou poisson, peu de viande rouge",
        });
        prefer = cards.map((c) => c.id);
      }
      setBusy("Recherche des meilleurs repas pour la semaine…");
      const drafts = await api.suggestMeals({ days: chosenDays, slots, agenda: agenda.id, servings, prefer });
      onDrafts(drafts, { agenda: agenda.id, servings, slots });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impossible de proposer des repas.");
    } finally {
      setBusy(null);
    }
  }

  if (futureDays.length === 0) {
    return (
      <Modal title="Proposer des repas" onClose={onClose}>
        <p className="text-sm text-stone-600 dark:text-stone-400">Cette semaine est passée : choisis une semaine à venir.</p>
      </Modal>
    );
  }

  return (
    <Modal title="Proposer des repas" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Seuls les créneaux vides de l'agenda <strong>{agenda.name}</strong> sont remplis, en équilibrant la semaine et en
          utilisant d'abord ton stock. Rien n'est enregistré tant que tu ne valides pas.
        </p>
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={scope === "week"} onChange={() => setScope("week")} /> Toute la semaine
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={scope === "day"} onChange={() => setScope("day")} /> Un jour
          </label>
        </div>
        {scope === "day" && (
          <Field label="Jour">
            <select className={inputClass} value={day} onChange={(e) => setDay(e.target.value)}>
              {futureDays.map((d) => (
                <option key={d} value={d}>
                  {new Date(`${d}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Moments">
          <div className="flex flex-wrap gap-3 text-sm">
            {SLOTS.map((slot) => (
              <label key={slot} className="flex items-center gap-1.5">
                <input type="checkbox" checked={slots.includes(slot)} onChange={() => toggleSlot(slot)} /> {SLOT_LABELS[slot]}
              </label>
            ))}
          </div>
        </Field>
        <Field label="Personnes">
          <input
            type="number"
            min={1}
            max={999}
            className={inputClass + " max-w-28"}
            value={servings}
            onChange={(e) => setServings(Math.min(999, Math.max(1, Number(e.target.value) || 1)))}
          />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
          <span>
            Inventer aussi jusqu'à {AI_MAX} nouvelles recettes avec l'IA
            <span className="block text-xs text-stone-500">Elles sont placées en premier ; compte dans ta limite quotidienne de recettes IA.</span>
          </span>
        </label>
        {busy && <p className="text-sm text-stone-500">{busy}</p>}
        <ErrorMessage message={error} />
        <div className="flex gap-2">
          <button className={primaryButton} onClick={submit} disabled={!!busy || slots.length === 0}>
            Proposer
          </button>
          <button className={secondaryButton} onClick={onClose}>
            Annuler
          </button>
        </div>
      </div>
    </Modal>
  );
}
