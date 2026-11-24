import { useState } from "react";
import { api, type MealSlot, type RecipeCard } from "../../api";
import RecipeDetailDialog from "../recipes/RecipeDetailDialog";
import RecipeSearch from "../recipes/RecipeSearch";
import { ErrorMessage, Modal } from "../ui";
import { SLOT_LABELS } from "./PlanDialog";

function dayLabel(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

/** Chercher un repas pour un moment précis d'un jour, et le programmer d'un clic. */
export default function SlotSearchDialog({
  day,
  slot,
  agendaId,
  agendaName,
  onPlanned,
  onClose,
}: {
  day: string;
  slot: MealSlot;
  agendaId: string; // « personal » ou l'identifiant d'un agenda partagé
  agendaName: string;
  onPlanned: () => void;
  onClose: () => void;
}) {
  const [open, setOpen] = useState<{ card: RecipeCard; servings: number; ingredients: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const moment = `${SLOT_LABELS[slot].toLowerCase()} du ${dayLabel(day)}`;

  async function choose(ref: string, servings: number) {
    setError(null);
    try {
      await api.planMeal({ recipe_ref: ref, meal_date: day, slot, servings,
        shared_agenda_id: agendaId === "personal" ? undefined : agendaId });
      onPlanned();
      onClose();
    } catch (err) {
      setOpen(null);
      setError(err instanceof Error ? err.message : "Programmation impossible.");
    }
  }

  return (
    <Modal title={`Repas pour le ${moment}`} onClose={onClose}>
      {agendaId !== "personal" && <p className="mb-3 text-sm text-stone-500">Agenda : {agendaName}</p>}
      <ErrorMessage message={error} />
      <RecipeSearch compact onOpen={(card, state) => setOpen({ card, servings: state.servings, ingredients: state.ingredients })} />
      {open && (
        <RecipeDetailDialog
          recipeId={open.card.id}
          initialServings={open.servings}
          wanted={open.ingredients}
          chooseLabel={`Programmer pour le ${moment}`}
          onChoose={(recipe, servings) => choose(recipe.id, servings)}
          onChanged={() => undefined}
          onClose={() => setOpen(null)}
        />
      )}
    </Modal>
  );
}
