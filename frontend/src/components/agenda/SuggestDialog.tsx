import { useEffect, useState } from "react";
import { api, type MealDraft, type MealSlot } from "../../api";
import { ErrorMessage, Field, inputClass, Modal, primaryButton, secondaryButton } from "../ui";
import { SLOT_LABELS, SLOTS } from "./PlanDialog";

export type SuggestSettings = { agenda: string; servings: number; slots: MealSlot[] };

/** Choix de ce qu'il faut proposer : la semaine ou un jour, les moments, le nombre de personnes. */
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
  const [scope, setScope] = useState<"week" | "day">("week");
  const [day, setDay] = useState(days[0]);
  const [slots, setSlots] = useState<MealSlot[]>(["lunch", "dinner"]);
  const [servings, setServings] = useState(2);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .preferences()
      .then((p) => setServings(p.default_servings))
      .catch(() => undefined);
  }, []);

  function toggleSlot(slot: MealSlot) {
    setSlots((current) => (current.includes(slot) ? current.filter((s) => s !== slot) : [...current, slot]));
  }

  async function submit() {
    setError(null);
    const chosenDays = scope === "week" ? days : [day];
    try {
      setBusy("Recherche de recettes de saison sur les sites… (jusqu'à 30 secondes)");
      const drafts = await api.suggestMeals({ days: chosenDays, slots, agenda: agenda.id, servings });
      onDrafts(drafts, { agenda: agenda.id, servings, slots });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impossible de proposer des repas.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal title="Proposer des repas" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Seuls les moments vides de l'agenda <strong>{agenda.name}</strong> sont remplis, comme les recettes du jour : des
          recettes de saison trouvées sur les sites (et tes recettes), variées, sans dessert, sans reprendre celles des deux dernières
          semaines, en équilibrant la semaine. Rien n'est enregistré tant que tu ne valides pas.
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
              {days.map((d) => (
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
