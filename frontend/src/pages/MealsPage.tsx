import { useCallback, useEffect, useState } from "react";
import { api, type DailyRecipes, type MyRecipes, type RecipeCard } from "../api";
import RecipeCardView from "../components/recipes/RecipeCardView";
import RecipeDetailDialog from "../components/recipes/RecipeDetailDialog";
import RecipeEditor from "../components/recipes/RecipeEditor";
import RecipeSearch from "../components/recipes/RecipeSearch";
import { Loading, primaryButton } from "../components/ui";

type Tab = "search" | "favorites" | "mine";

const TAB_LABELS: Record<Tab, string> = { search: "Recherche", favorites: "Épinglés & favoris", mine: "Mes recettes" };

type Open = { ref: string; servings: number; ingredients: string[] };

export default function MealsPage() {
  const [tab, setTab] = useState<Tab>("search");
  const [favorites, setFavorites] = useState<RecipeCard[] | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [daily, setDaily] = useState<DailyRecipes | null>(null);
  const [dailyFailed, setDailyFailed] = useState(false);
  const [dailyHidden, setDailyHidden] = useState(false);
  const [servings, setServings] = useState(2);

  useEffect(() => {
    api.preferences().then((p) => setServings(p.default_servings)).catch(() => undefined);
    api
      .dailyRecipes()
      .then(setDaily)
      .catch(() => setDailyFailed(true));
  }, []);

  const loadFavorites = useCallback(() => {
    setFavorites(null);
    api.favorites().then(setFavorites).catch(() => setFavorites([]));
  }, []);

  useEffect(() => {
    if (tab === "favorites") loadFavorites();
  }, [tab, loadFavorites, refreshKey]);

  const openRef = (ref: string) => setOpen({ ref, servings, ingredients: [] });

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Repas</h1>
        <div className="grid grid-cols-3 rounded-lg bg-stone-200 p-1 text-sm dark:bg-stone-800">
          {(["search", "favorites", "mine"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={"rounded-md px-3 py-1.5 font-medium " + (tab === t ? "bg-white shadow-sm dark:bg-stone-900" : "text-stone-600 dark:text-stone-400")}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>
      </div>

      <div className={tab === "search" ? "" : "hidden"}>
        <RecipeSearch
          onOpen={(card, state) => setOpen({ ref: card.id, servings: state.servings, ingredients: state.ingredients })}
          onSearch={() => setDailyHidden(true)}
          between={<DailySection daily={daily} failed={dailyFailed} onOpen={openRef} hidden={dailyHidden}
            onToggle={() => setDailyHidden((h) => !h)} />}
        />
      </div>

      {tab === "favorites" &&
        (favorites === null ? (
          <Loading />
        ) : favorites.length === 0 ? (
          <div className="rounded-xl border border-dashed border-stone-300 p-8 text-center text-stone-600 dark:border-stone-700 dark:text-stone-400">
            Aucun repas épinglé ni favori pour l'instant. Ouvre une recette pour l'ajouter.
          </div>
        ) : (
          <CardGrid cards={favorites} onOpen={openRef} />
        ))}

      {tab === "mine" && <MyRecipesTab onOpen={openRef} refreshKey={refreshKey} onChanged={() => setRefreshKey((k) => k + 1)} />}

      {open && (
        <RecipeDetailDialog
          recipeId={open.ref}
          initialServings={open.servings}
          wanted={open.ingredients}
          onChanged={() => setRefreshKey((k) => k + 1)}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

function MyRecipesTab({ onOpen, refreshKey, onChanged }: { onOpen: (id: string) => void; refreshKey: number; onChanged: () => void }) {
  const [data, setData] = useState<MyRecipes | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.myRecipes().then(setData).catch(() => setData({ mine: [], shared_with_me: [] }));
  }, [refreshKey]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Crée tes recettes, ou ouvre n'importe quelle recette et choisis « Copier pour l'adapter ».
        </p>
        <button className={primaryButton} onClick={() => setCreating(true)}>
          + Nouvelle recette
        </button>
      </div>
      {data === null ? (
        <Loading />
      ) : (
        <>
          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">Mes recettes · {data.mine.length}</h2>
            {data.mine.length === 0 ? (
              <p className="text-sm text-stone-500">Aucune recette personnelle pour l'instant.</p>
            ) : (
              <ul className="divide-y divide-stone-200 overflow-hidden rounded-xl border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
                {data.mine.map((r) => (
                  <li key={r.id}>
                    <button className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-stone-50 dark:hover:bg-stone-800" onClick={() => onOpen(r.id)}>
                      <span>
                        <span className="font-medium">{r.title}</span>
                        <span className="ml-2 text-sm text-stone-500">
                          {r.servings} pers.{r.is_vegan ? " · vegan" : r.is_vegetarian ? " · végétarien" : ""}
                          {r.shared_with > 0 && ` · partagée (${r.shared_with})`}
                        </span>
                      </span>
                      <span
                        className={
                          "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium " +
                          (r.status === "complete" ? "bg-brand-100 text-brand-700" : "bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-200")
                        }
                      >
                        {r.status === "complete" ? "complète" : "brouillon"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {data.shared_with_me.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">Partagées avec moi</h2>
              <ul className="divide-y divide-stone-200 overflow-hidden rounded-xl border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
                {data.shared_with_me.map((r) => (
                  <li key={r.id}>
                    <button className="w-full px-4 py-3 text-left hover:bg-stone-50 dark:hover:bg-stone-800" onClick={() => onOpen(r.id)}>
                      <span className="font-medium">{r.title}</span>
                      <span className="ml-2 text-sm text-stone-500">par {r.author ?? "?"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
      {creating && <RecipeEditor recipeId={null} onSaved={onChanged} onClose={() => setCreating(false)} />}
    </div>
  );
}

function CardGrid({ cards, onOpen }: { cards: RecipeCard[]; onOpen: (id: string) => void }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map((card) => (
        <RecipeCardView key={card.id} card={card} onOpen={() => onOpen(card.id)} />
      ))}
    </div>
  );
}

/** Recettes du jour : repliables ; repliées d'elles-mêmes quand on lance une recherche. */
function DailySection({ daily, failed, onOpen, hidden, onToggle }: {
  daily: DailyRecipes | null;
  failed: boolean;
  onOpen: (id: string) => void;
  hidden: boolean;
  onToggle: () => void;
}) {
  if (failed || (daily && daily.recipes.length === 0)) return null;
  return (
    <section className={hidden ? "mb-4" : "mb-8"}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
          Recettes du jour
          {daily && <span className="ml-2 font-normal normal-case tracking-normal">· {new Date(daily.day + "T12:00:00").toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}</span>}
        </h2>
        <button className="text-sm text-stone-500 hover:underline" onClick={onToggle} aria-expanded={!hidden}>
          {hidden ? "Afficher ▾" : "Masquer ▴"}
        </button>
      </div>
      {hidden ? null : daily === null ? (
        <Loading label="Choix des recettes du jour…" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {daily.recipes.map(({ recipe, reasons }) => (
            <div key={recipe.id} className="flex flex-col gap-2">
              <RecipeCardView card={recipe} onOpen={() => onOpen(recipe.id)} />
              <ul className="flex flex-wrap gap-1.5 text-xs">
                {reasons.map((r) => (
                  <li key={r} className="rounded-full bg-brand-50 px-2 py-0.5 text-brand-700 dark:bg-stone-800 dark:text-brand-500">
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
