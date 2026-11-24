import { useEffect, useState } from "react";
import { api, type Agenda, type MealSlot } from "../../api";
import { isoToday } from "../../format";
import { ErrorMessage, Field, inputClass, Modal, primaryButton } from "../ui";

export const SLOT_LABELS: Record<MealSlot, string> = {
  breakfast: "Petit-déjeuner",
  lunch: "Déjeuner",
  snack: "Encas",
  dinner: "Dîner",
};
export const SLOTS: MealSlot[] = ["breakfast", "lunch", "snack", "dinner"];

/** Programmer une recette dans un agenda (personnel ou partagé), à n'importe quelle date. */
export default function PlanDialog({
  title,
  recipeRef,
  defaultServings,
  onPlanned,
  onClose,
}: {
  title: string;
  recipeRef: string;
  defaultServings: number;
  onPlanned: () => void;
  onClose: () => void;
}) {
  const [date, setDate] = useState(isoToday());
  const [slot, setSlot] = useState<MealSlot>(new Date().getHours() < 14 ? "lunch" : "dinner");
  const [servings, setServings] = useState(defaultServings);
  const [agendas, setAgendas] = useState<Agenda[]>([]);
  const [agendaId, setAgendaId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .agendas()
      .then((list) => setAgendas(list.filter((a) => a.my_role !== "member")))
      .catch(() => setAgendas([]));
  }, []);

  async function plan() {
    setError(null);
    try {
      await api.planMeal({ recipe_ref: recipeRef, meal_date: date, slot, servings, shared_agenda_id: agendaId || undefined });
      onPlanned();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Programmation impossible.");
    }
  }

  return (
    <Modal title={`Programmer « ${title} »`} onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
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
        </div>
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
