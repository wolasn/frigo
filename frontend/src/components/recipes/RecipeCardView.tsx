import type { RecipeCard } from "../../api";

export const DIFFICULTY_LABELS = { easy: "Facile", medium: "Moyen", hard: "Difficile" } as const;

export function HealthBadge({ score }: { score: number | null }) {
  if (score === null) return null;
  const style =
    score >= 7
      ? "bg-brand-100 text-brand-700"
      : score >= 4
        ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
  return (
    <span className={"rounded-full px-2 py-0.5 text-xs font-medium " + style} title="Score santé sur 10">
      Santé {score.toLocaleString("fr-FR")}/10
    </span>
  );
}

export function SourceBadge({ source }: { source: RecipeCard["source"] }) {
  if (source === "ai") {
    return <span className="rounded-full bg-violet-600 px-2 py-0.5 text-xs font-bold text-white">IA</span>;
  }
  if (source === "user") {
    return <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-800 dark:bg-sky-950 dark:text-sky-300">Perso</span>;
  }
  return null;
}

function minutes(card: RecipeCard): string | null {
  const total = (card.prep_minutes ?? 0) + (card.cook_minutes ?? 0);
  if (!total) return null;
  return total >= 60 ? `${Math.floor(total / 60)} h ${total % 60 ? String(total % 60).padStart(2, "0") : ""}` : `${total} min`;
}

export default function RecipeCardView({ card, onOpen }: { card: RecipeCard; onOpen: () => void }) {
  const time = minutes(card);
  return (
    <button
      onClick={onOpen}
      className="flex flex-col overflow-hidden rounded-xl border border-stone-200 bg-white text-left transition hover:shadow-md dark:border-stone-800 dark:bg-stone-900"
    >
      <div className="relative aspect-[16/9] w-full bg-stone-200 dark:bg-stone-800">
        {card.image_url && <img src={card.image_url} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />}
        <div className="absolute left-2 top-2 flex gap-1">
          {card.is_pinned && <span className="rounded-full bg-white/90 px-2 py-0.5 text-xs font-medium text-stone-900">📌 Épinglé</span>}
          {card.is_favorite && <span className="rounded-full bg-white/90 px-2 py-0.5 text-xs text-amber-600">★</span>}
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-start justify-between gap-2">
          <p className="font-medium leading-snug">{card.title}</p>
          <SourceBadge source={card.source} />
        </div>
        <div className="flex flex-wrap gap-1 text-xs text-stone-600 dark:text-stone-400">
          {card.difficulty && <span>{DIFFICULTY_LABELS[card.difficulty]}</span>}
          {time && <span>· {time}</span>}
          {card.is_vegan ? <span>· Vegan</span> : card.is_vegetarian ? <span>· Végétarien</span> : null}
          {card.times_cooked > 0 && <span>· Déjà cuisiné {card.times_cooked}×</span>}
        </div>
        <div className="flex flex-wrap gap-1">
          <HealthBadge score={card.health_score} />
          {card.rating && <span className="text-xs text-amber-600">{"★".repeat(card.rating)}</span>}
        </div>
        {card.expiring_used.length > 0 && (
          <p className="text-xs text-amber-700 dark:text-amber-400">Utilise : {card.expiring_used.join(", ")} (bientôt périmé)</p>
        )}
        {card.missing.length > 0 ? (
          <p className="text-xs text-stone-600 dark:text-stone-400">À acheter : {card.missing.join(", ")}</p>
        ) : (
          <p className="text-xs font-medium text-brand-700 dark:text-brand-500">Tout est disponible</p>
        )}
        {card.missing_utensils.length > 0 && (
          <p className="text-xs font-medium text-red-700 dark:text-red-400">Ustensile manquant : {card.missing_utensils.join(", ")}</p>
        )}
        {card.disliked.length > 0 && (
          <p className="text-xs font-medium text-orange-700 dark:text-orange-400">Contient : {card.disliked.join(", ")} (tu n'aimes pas)</p>
        )}
      </div>
    </button>
  );
}
