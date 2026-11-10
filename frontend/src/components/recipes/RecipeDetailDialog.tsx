import { useEffect, useState } from "react";
import { api, type IngredientStatus, type RecipeDetail } from "../../api";
import { formatDate } from "../../format";
import { ErrorMessage, inputClass, Modal, primaryButton, secondaryButton } from "../ui";
import PlanDialog from "../agenda/PlanDialog";
import RecipeEditor from "./RecipeEditor";
import ShareRecipeDialog from "./ShareRecipeDialog";
import { DIFFICULTY_LABELS, HealthBadge, SourceBadge } from "./RecipeCardView";

const STATUS: Record<IngredientStatus, { label: string; style: string }> = {
  ok: { label: "En stock", style: "text-brand-700 dark:text-brand-500" },
  infinite: { label: "Toujours dispo", style: "text-brand-700 dark:text-brand-500" },
  partial: { label: "Pas assez", style: "text-amber-700 dark:text-amber-400" },
  missing: { label: "À acheter", style: "text-red-700 dark:text-red-400" },
  unknown: { label: "Non reconnu", style: "text-stone-500" },
  seasoning: { label: "À vérifier", style: "text-stone-500" },
};

export default function RecipeDetailDialog({
  recipeId,
  initialServings,
  onChanged,
  onClose,
}: {
  recipeId: string;
  initialServings: number;
  onChanged: () => void;
  onClose: () => void;
}) {
  const [servings, setServings] = useState(initialServings);
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);

  async function copy() {
    setError(null);
    try {
      const created = await api.copyRecipe(recipeId);
      onChanged();
      setEditing(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Copie impossible.");
    }
  }

  async function remove() {
    if (!window.confirm("Supprimer définitivement cette recette ?")) return;
    try {
      await api.deleteRecipe(recipeId);
      onChanged();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suppression impossible.");
    }
  }

  useEffect(() => {
    api
      .recipe(recipeId, servings)
      .then((r) => {
        setRecipe(r);
        setComment(r.comment ?? "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Recette indisponible."));
  }, [recipeId, servings]);

  async function update(body: Parameters<typeof api.updateMeta>[1]) {
    setError(null);
    try {
      const card = await api.updateMeta(recipeId, body);
      setRecipe((r) => (r ? { ...r, ...card, ingredients: r.ingredients, utensils: r.utensils, steps: r.steps, nutrition: r.nutrition } : r));
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible.");
    }
  }

  if (!recipe) {
    return (
      <Modal title="Recette" onClose={onClose}>
        {error ? <ErrorMessage message={error} /> : <p className="text-stone-500">Chargement…</p>}
      </Modal>
    );
  }

  const commentChanged = (recipe.comment ?? "") !== comment.trim();

  return (
    <Modal title={recipe.title} onClose={onClose}>
      <div className="space-y-5">
        {recipe.image_url && (
          <img src={recipe.image_url} alt="" className="aspect-[16/9] w-full rounded-lg object-cover" onError={(e) => (e.currentTarget.style.display = "none")} />
        )}

        <div className="flex flex-wrap items-center gap-2 text-sm text-stone-600 dark:text-stone-400">
          <SourceBadge source={recipe.source} />
          {recipe.difficulty && <span>{DIFFICULTY_LABELS[recipe.difficulty]}</span>}
          {recipe.prep_minutes ? <span>· Préparation {recipe.prep_minutes} min</span> : null}
          {recipe.cook_minutes ? <span>· Cuisson {recipe.cook_minutes} min</span> : null}
          {recipe.is_vegan ? <span>· Vegan</span> : recipe.is_vegetarian ? <span>· Végétarien</span> : null}
          <HealthBadge score={recipe.health_score} />
        </div>

        {recipe.status === "draft" && (
          <p className="rounded-lg bg-stone-100 px-3 py-2 text-sm dark:bg-stone-800">Brouillon : n'apparaît pas dans les propositions.</p>
        )}
        <div className="flex flex-wrap gap-2 text-sm">
          {recipe.is_mine ? (
            <>
              <button className={secondaryButton + " py-1.5"} onClick={() => setEditing(recipe.id)}>
                Modifier
              </button>
              {recipe.status === "complete" && (
                <button className={secondaryButton + " py-1.5"} onClick={() => setSharing(true)}>
                  Partager
                </button>
              )}
              <button className="rounded-lg px-3 py-1.5 text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-stone-800" onClick={remove}>
                Supprimer
              </button>
            </>
          ) : (
            <button className={secondaryButton + " py-1.5"} onClick={copy}>
              Copier pour l'adapter
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button className={primaryButton + " py-1.5 text-sm"} onClick={() => setPlanning(true)}>
            Planifier
          </button>
          <button className={secondaryButton + " py-1.5 text-sm"} onClick={() => update({ is_favorite: !recipe.is_favorite })}>
            {recipe.is_favorite ? "★ Favori" : "☆ Ajouter aux favoris"}
          </button>
          <div className="flex items-center gap-0.5" aria-label="Ma note">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                onClick={() => update({ rating: recipe.rating === n ? null : n })}
                className={"text-xl " + ((recipe.rating ?? 0) >= n ? "text-amber-500" : "text-stone-300 dark:text-stone-600")}
                aria-label={`${n} étoile${n > 1 ? "s" : ""}`}
              >
                ★
              </button>
            ))}
          </div>
          {recipe.times_cooked > 0 && (
            <span className="text-sm text-stone-500">
              Déjà cuisiné {recipe.times_cooked}×{recipe.last_cooked_on && `, la dernière fois le ${formatDate(recipe.last_cooked_on)}`}
            </span>
          )}
        </div>

        <div className="space-y-2">
          <textarea
            className={inputClass + " min-h-16"}
            placeholder="Mon commentaire (obligatoire pour épingler)"
            value={comment}
            maxLength={1000}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            {commentChanged && (
              <button
                className={secondaryButton + " py-1.5 text-sm"}
                onClick={() => {
                  if (recipe.is_pinned && !comment.trim()) {
                    // Un repas épinglé exige un commentaire : le supprimer retire l'épingle, après confirmation.
                    if (window.confirm("Supprimer le commentaire retire aussi l'épingle. Continuer ?")) update({ comment: null, is_pinned: false });
                    return;
                  }
                  update({ comment: comment.trim() || null });
                }}
              >
                Enregistrer le commentaire
              </button>
            )}
            <button
              className={(recipe.is_pinned ? secondaryButton : primaryButton) + " py-1.5 text-sm"}
              onClick={() => update(recipe.is_pinned ? { is_pinned: false } : { is_pinned: true, comment: comment.trim() || null })}
            >
              {recipe.is_pinned ? "Retirer l'épingle" : "📌 Épingler"}
            </button>
          </div>
          <ErrorMessage message={error} />
        </div>

        <section>
          <div className="mb-2 flex items-center justify-between gap-3">
            <h3 className="font-semibold">Ingrédients</h3>
            <label className="flex items-center gap-2 text-sm">
              Pour
              <input
                type="number"
                min={1}
                max={999}
                value={servings}
                onChange={(e) => setServings(Math.min(999, Math.max(1, Number(e.target.value) || 1)))}
                className={inputClass + " w-20 py-1"}
              />
              pers.
            </label>
          </div>
          <ul className="divide-y divide-stone-200 text-sm dark:divide-stone-800">
            {recipe.ingredients.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 py-1.5">
                <span>
                  {i.amount && <span className="font-medium">{i.amount} </span>}
                  {i.name}
                  {i.expiring && <span className="ml-1 text-amber-600">· bientôt périmé</span>}
                  {i.disliked && <span className="ml-1 text-orange-600">· tu n'aimes pas</span>}
                </span>
                <span className={"shrink-0 text-xs font-medium " + STATUS[i.status].style}>{STATUS[i.status].label}</span>
              </li>
            ))}
          </ul>
        </section>

        {recipe.utensils.length > 0 && (
          <section>
            <h3 className="mb-2 font-semibold">Ustensiles</h3>
            <div className="flex flex-wrap gap-1.5">
              {recipe.utensils.map((u) => (
                <span
                  key={u.name}
                  className={
                    "rounded-full px-2.5 py-1 text-xs " +
                    (u.owned ? "bg-stone-100 dark:bg-stone-800" : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300")
                  }
                >
                  {u.name}
                  {!u.owned && " (manquant)"}
                </span>
              ))}
            </div>
          </section>
        )}

        <section>
          <h3 className="mb-2 font-semibold">Recette</h3>
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            {recipe.steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </section>

        {recipe.nutrition?.points && (
          <section className="text-sm">
            <h3 className="mb-2 font-semibold">Score santé : détail</h3>
            <ul className="space-y-0.5">
              {recipe.nutrition.points.map((p) => (
                <li key={p.label} className={p.points < 0 ? "text-red-700 dark:text-red-400" : "text-brand-700 dark:text-brand-500"}>
                  {p.points > 0 ? "+" : ""}
                  {p.points} : {p.label}
                </li>
              ))}
            </ul>
            {recipe.nutrition.per_serving?.kcal && (
              <p className="mt-1 text-stone-500">{Math.round(recipe.nutrition.per_serving.kcal)} kcal par portion</p>
            )}
          </section>
        )}

        {recipe.external_url && (
          <a href={recipe.external_url} target="_blank" rel="noreferrer" className="inline-block text-sm text-brand-700 hover:underline dark:text-brand-500">
            Voir la recette sur Marmiton ↗
          </a>
        )}
      </div>
      {editing && (
        <RecipeEditor
          recipeId={editing}
          onSaved={onChanged}
          onClose={() => {
            setEditing(null);
            if (editing !== recipeId) onClose();  // une copie : on referme la recette d'origine
            else api.recipe(recipeId, servings).then(setRecipe).catch(() => onClose());
          }}
        />
      )}
      {sharing && <ShareRecipeDialog recipeId={recipe.id} title={recipe.title} onClose={() => setSharing(false)} />}
      {planning && (
        <PlanDialog
          title={recipe.title}
          recipeId={recipe.id}
          defaultServings={servings}
          onPlanned={onChanged}
          onClose={() => setPlanning(false)}
        />
      )}
    </Modal>
  );
}
