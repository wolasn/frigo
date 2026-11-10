import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Inventory, type Item, type MyRecipes, type ProposalQuery, type RecipeCard } from "../api";
import PlanDialog from "../components/agenda/PlanDialog";
import RecipeCardView from "../components/recipes/RecipeCardView";
import RecipeEditor from "../components/recipes/RecipeEditor";
import RecipeDetailDialog from "../components/recipes/RecipeDetailDialog";
import { ErrorMessage, inputClass, primaryButton, secondaryButton } from "../components/ui";
import { expiryText, formatQuantity, STATUS_STYLES } from "../format";

type Tab = "proposals" | "favorites" | "mine";

const TAB_LABELS: Record<Tab, string> = { proposals: "Propositions", favorites: "Épinglés & favoris", mine: "Mes recettes" };

export default function MealsPage() {
  const [tab, setTab] = useState<Tab>("proposals");
  const [inventories, setInventories] = useState<Inventory[]>([]);
  const [selectedInventories, setSelectedInventories] = useState<string[] | null>(null);
  const [servings, setServings] = useState(2);
  const [mode, setMode] = useState<ProposalQuery["mode"]>("inventory");
  const [maxPurchases, setMaxPurchases] = useState("3");
  const [diet, setDiet] = useState<ProposalQuery["diet"]>("none");
  const [withMissingUtensils, setWithMissingUtensils] = useState(false);
  const [maxDifficulty, setMaxDifficulty] = useState<"" | "easy" | "medium" | "hard">("");
  const [maxMinutes, setMaxMinutes] = useState("");
  const [minHealth, setMinHealth] = useState("");
  const [cards, setCards] = useState<RecipeCard[] | null>(null);
  const [leftovers, setLeftovers] = useState<Item[]>([]);
  const [planLeftover, setPlanLeftover] = useState<Item | null>(null);
  const [openRecipe, setOpenRecipe] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState<RecipeCard[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [askAi, setAskAi] = useState(false);
  const [aiWish, setAiWish] = useState("");
  const [aiCount, setAiCount] = useState(2);
  const [resultsLabel, setResultsLabel] = useState("Résultats Marmiton");
  const [error, setError] = useState<string | null>(null);

  const loadLeftovers = useCallback((list: Inventory[]) => {
    Promise.all(list.map((i) => api.items(i.id)))
      .then((results) => setLeftovers(results.flatMap((r) => r.items).filter((i) => i.kind === "leftover")))
      .catch(() => setLeftovers([]));
  }, []);

  useEffect(() => {
    // Les préférences donnent le régime et le nombre de personnes de départ ; l'inventaire suit.
    api
      .preferences()
      .then((prefs) => {
        setServings(prefs.default_servings);
        setDiet(prefs.diet);
      })
      .catch(() => undefined)
      .finally(() =>
        api.inventories().then((list) => {
          setInventories(list);
          setSelectedInventories(list.filter((i) => i.include_in_suggestions).map((i) => i.id));
          loadLeftovers(list);
        }),
      );
  }, [loadLeftovers]);

  const load = useCallback(() => {
    if (selectedInventories === null || tab === "mine") return;
    setError(null);
    const request =
      tab === "favorites"
        ? api.favorites()
        : api.proposals({
            servings,
            mode,
            max_purchases: mode === "purchases" && maxPurchases !== "" ? Number(maxPurchases) : undefined,
            diet,
            include_missing_utensils: withMissingUtensils,
            inventory_ids: selectedInventories,
            max_difficulty: maxDifficulty || undefined,
            max_minutes: maxMinutes ? Number(maxMinutes) : undefined,
            min_health: minHealth ? Number(minHealth) : undefined,
          });
    request.then(setCards).catch((err) => setError(err instanceof Error ? err.message : "Chargement impossible."));
  }, [tab, servings, mode, maxPurchases, diet, withMissingUtensils, selectedInventories, maxDifficulty, maxMinutes, minHealth]);

  useEffect(load, [load]);

  async function discover() {
    setBusy("Recherche sur Marmiton avec tes ingrédients… (jusqu'à 30 secondes)");
    setError(null);
    try {
      const result = await api.discoverRecipes();
      setSearchResults(result.recipes);
      setResultsLabel("Résultats Marmiton");
      setSearchText(result.queries.join(", "));
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recherche impossible.");
    } finally {
      setBusy(null);
    }
  }

  async function generateWithAi(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy("L'IA invente des recettes avec ton inventaire… (jusqu'à une minute)");
    try {
      const cards = await api.generateRecipes({
        count: aiCount,
        servings,
        max_purchases: mode === "inventory" ? 0 : maxPurchases === "" ? null : Number(maxPurchases),
        diet,
        wish: aiWish.trim() || undefined,
      });
      setSearchResults(cards);
      setResultsLabel("Recettes inventées par l'IA");
      setAskAi(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Génération impossible.");
    } finally {
      setBusy(null);
    }
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    const text = searchText.trim();
    if (!text) return;
    setError(null);
    const isUrl = /^https?:\/\//i.test(text);
    setBusy(isUrl ? "Import de la recette…" : "Recherche sur Marmiton…");
    try {
      setSearchResults(isUrl ? [await api.importRecipe(text)] : await api.searchRecipes(text));
      setResultsLabel("Résultats Marmiton");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recherche impossible.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Repas</h1>
        <div className="grid grid-cols-3 rounded-lg bg-stone-200 p-1 text-sm dark:bg-stone-800">
          {(["proposals", "favorites", "mine"] as const).map((t) => (
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

      {tab === "mine" && <MyRecipesTab onOpen={setOpenRecipe} refreshKey={refreshKey} onChanged={() => setRefreshKey((k) => k + 1)} />}

      {tab === "proposals" && (
        <>
          {leftovers.length > 0 && (
            <section className="mb-6">
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">À finir</h2>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {leftovers.map((l) => (
                  <div key={l.id} className="shrink-0 rounded-xl border border-stone-200 bg-white px-4 py-3 dark:border-stone-800 dark:bg-stone-900">
                    <p className="font-medium">{l.name}</p>
                    <p className="text-sm text-stone-600 dark:text-stone-400">
                      {formatQuantity(l.quantity, l.unit)}
                      {l.reserved > 0 && ` · ${l.reserved} planifiée(s)`}
                    </p>
                    <span className={"mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium " + STATUS_STYLES[l.status]}>{expiryText(l)}</span>
                    {l.quantity - l.reserved > 0 && (
                      <button className="mt-2 block text-sm font-medium text-brand-700 hover:underline dark:text-brand-500" onClick={() => setPlanLeftover(l)}>
                        Planifier
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="mb-4 grid gap-3 rounded-xl border border-stone-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-4 dark:border-stone-800 dark:bg-stone-900">
            <label className="text-sm">
              <span className="mb-1 block font-medium">Personnes</span>
              <input
                type="number"
                min={1}
                max={999}
                value={servings}
                onChange={(e) => setServings(Math.min(999, Math.max(1, Number(e.target.value) || 1)))}
                className={inputClass}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Ingrédients</span>
              <select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as ProposalQuery["mode"])}>
                <option value="inventory">Uniquement mon inventaire</option>
                <option value="purchases">Avec quelques achats</option>
              </select>
            </label>
            {mode === "purchases" && (
              <label className="text-sm">
                <span className="mb-1 block font-medium">Achats au plus</span>
                <select className={inputClass} value={maxPurchases} onChange={(e) => setMaxPurchases(e.target.value)}>
                  {[1, 2, 3, 4, 5, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      {n} ingrédient{n > 1 ? "s" : ""}
                    </option>
                  ))}
                  <option value="">Illimité (tout acheter)</option>
                </select>
              </label>
            )}
            <label className="text-sm">
              <span className="mb-1 block font-medium">Régime</span>
              <select className={inputClass} value={diet} onChange={(e) => setDiet(e.target.value as ProposalQuery["diet"])}>
                <option value="none">Tous</option>
                <option value="vegetarian">Végétarien</option>
                <option value="vegan">Vegan</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Difficulté</span>
              <select className={inputClass} value={maxDifficulty} onChange={(e) => setMaxDifficulty(e.target.value as typeof maxDifficulty)}>
                <option value="">Toutes</option>
                <option value="easy">Facile</option>
                <option value="medium">Moyenne au plus</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Temps total</span>
              <select className={inputClass} value={maxMinutes} onChange={(e) => setMaxMinutes(e.target.value)}>
                <option value="">Peu importe</option>
                {[15, 30, 45, 60, 90].map((m) => (
                  <option key={m} value={m}>
                    {m} min au plus
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Score santé</span>
              <select className={inputClass} value={minHealth} onChange={(e) => setMinHealth(e.target.value)}>
                <option value="">Tous</option>
                {[5, 6, 7, 8].map((s) => (
                  <option key={s} value={s}>
                    {s}/10 ou plus
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={withMissingUtensils} onChange={(e) => setWithMissingUtensils(e.target.checked)} className="size-4 accent-brand-600" />
              Montrer aussi les recettes qui demandent un ustensile que je n'ai pas
            </label>
            {inventories.length > 1 && selectedInventories && (
              <fieldset className="text-sm sm:col-span-2">
                <legend className="mb-1 font-medium">Inventaires pris en compte</legend>
                {inventories.map((i) => (
                  <label key={i.id} className="mr-4 inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      className="size-4 accent-brand-600"
                      checked={selectedInventories.includes(i.id)}
                      onChange={(e) =>
                        setSelectedInventories((s) => (e.target.checked ? [...(s ?? []), i.id] : (s ?? []).filter((x) => x !== i.id)))
                      }
                    />
                    {i.name}
                  </label>
                ))}
              </fieldset>
            )}
          </div>

          <div className="mb-6 flex flex-col gap-2 sm:flex-row">
            <form onSubmit={search} className="flex flex-1 gap-2">
              <input
                className={inputClass}
                placeholder="Chercher sur Marmiton, ou coller le lien d'une recette"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
              />
              <button type="submit" className={secondaryButton} disabled={busy !== null}>
                Chercher
              </button>
            </form>
            <button className={primaryButton} onClick={discover} disabled={busy !== null}>
              Trouver avec mes ingrédients
            </button>
            <button
              className="rounded-lg bg-violet-600 px-4 py-2 font-medium text-white transition hover:bg-violet-700 disabled:opacity-60"
              onClick={() => setAskAi(true)}
              disabled={busy !== null}
            >
              Inventer avec l'IA
            </button>
          </div>
          {askAi && (
            <form
              onSubmit={generateWithAi}
              className="mb-6 grid gap-3 rounded-xl border border-violet-300 bg-violet-50 p-4 sm:grid-cols-[1fr_auto_auto] dark:border-violet-900 dark:bg-stone-900"
            >
              <input
                className={inputClass}
                placeholder="Une envie ? (facultatif : soupe, plat rapide, sans four…)"
                value={aiWish}
                onChange={(e) => setAiWish(e.target.value)}
                maxLength={200}
              />
              <select className={inputClass} value={aiCount} onChange={(e) => setAiCount(Number(e.target.value))} aria-label="Nombre de recettes">
                {[1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n} recette{n > 1 ? "s" : ""}
                  </option>
                ))}
              </select>
              <button className="rounded-lg bg-violet-600 px-4 py-2 font-medium text-white hover:bg-violet-700 disabled:opacity-60" disabled={busy !== null}>
                Inventer
              </button>
              <p className="text-xs text-stone-600 sm:col-span-3 dark:text-stone-400">
                L'IA part de ton inventaire (aliments bientôt périmés d'abord), de tes préférences et des réglages ci-dessus. Les recettes créées portent le badge IA et sont visibles par tous les utilisateurs.
              </p>
            </form>
          )}
          {busy && <p className="mb-4 text-sm text-stone-600 dark:text-stone-400" role="status">{busy}</p>}

          {searchResults && (
            <section className="mb-8">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
                  {resultsLabel} · {searchResults.length}
                </h2>
                <button className="text-sm text-stone-500 hover:underline" onClick={() => setSearchResults(null)}>
                  Masquer
                </button>
              </div>
              <CardGrid cards={searchResults} onOpen={setOpenRecipe} />
            </section>
          )}
        </>
      )}

      <ErrorMessage message={error} />

      {tab === "proposals" && (
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">Propositions{cards ? ` · ${cards.length}` : ""}</h2>
      )}
      {tab === "mine" ? null : cards === null ? (
        <p className="text-stone-500">Chargement…</p>
      ) : cards.length === 0 ? (
        <div className="rounded-xl border border-dashed border-stone-300 p-8 text-center text-stone-600 dark:border-stone-700 dark:text-stone-400">
          {tab === "favorites"
            ? "Aucun repas épinglé ni favori pour l'instant. Ouvre une recette pour l'ajouter."
            : mode === "inventory"
              ? "Aucune recette connue n'est réalisable avec ton inventaire seul. Essaie « Avec quelques achats » ou « Trouver avec mes ingrédients »."
              : "Aucune recette ne correspond. Lance « Trouver avec mes ingrédients » pour en récupérer sur Marmiton."}
        </div>
      ) : (
        <CardGrid cards={cards} onOpen={setOpenRecipe} />
      )}

      {openRecipe && (
        <RecipeDetailDialog
          recipeId={openRecipe}
          initialServings={servings}
          onChanged={() => {
            load();
            setRefreshKey((k) => k + 1);
          }}
          onClose={() => setOpenRecipe(null)}
        />
      )}
      {planLeftover && (
        <PlanDialog
          title={planLeftover.name}
          leftoverItemId={planLeftover.id}
          defaultServings={Math.max(1, Math.floor(planLeftover.quantity - planLeftover.reserved))}
          maxServings={Math.max(1, Math.floor(planLeftover.quantity - planLeftover.reserved))}
          onPlanned={() => loadLeftovers(inventories)}
          onClose={() => setPlanLeftover(null)}
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
        <p className="text-stone-500">Chargement…</p>
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
