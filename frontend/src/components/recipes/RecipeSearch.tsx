import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, type Diet, type Difficulty, type RecipeCard, type Term } from "../../api";
import { ErrorMessage, inputClass, Loading, primaryButton, secondaryButton } from "../ui";
import PhotoIngredients from "./PhotoIngredients";
import RecipeCardView from "./RecipeCardView";

const DIFFICULTIES: { value: Difficulty; label: string }[] = [
  { value: "easy", label: "Facile" },
  { value: "medium", label: "Moyenne" },
  { value: "hard", label: "Difficile" },
];

export type SearchState = { ingredients: string[]; servings: number };

/** Recherche de recettes : ingrédients à cocher (ou en photo), filtres, sites web et recettes créées, IA. */
export default function RecipeSearch({
  onOpen,
  between,
  compact = false,
}: {
  onOpen: (card: RecipeCard, state: SearchState) => void;
  between?: ReactNode; // affiché entre le formulaire et les résultats (ex. recettes du jour)
  compact?: boolean; // dans une fenêtre : filtres repliés
}) {
  const [checked, setChecked] = useState<string[]>([]);
  const [only, setOnly] = useState(false);
  const [text, setText] = useState("");
  const [servings, setServings] = useState(2);
  const [diet, setDiet] = useState<Diet>("none");
  const [difficulties, setDifficulties] = useState<Difficulty[]>([]);
  const [maxMinutes, setMaxMinutes] = useState("");
  const [minHealth, setMinHealth] = useState("");
  const [maxHealth, setMaxHealth] = useState("");
  const [withMissingUtensils, setWithMissingUtensils] = useState(false);
  const [tolerated, setTolerated] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(!compact);
  const [photo, setPhoto] = useState(false);
  const [askAi, setAskAi] = useState(false);
  const [aiWish, setAiWish] = useState("");
  const [aiCount, setAiCount] = useState(2);
  const [results, setResults] = useState<RecipeCard[] | null>(null);
  const [resultsLabel, setResultsLabel] = useState("");
  const [siteErrors, setSiteErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .preferences()
      .then((prefs) => {
        setServings(prefs.default_servings);
        setDiet(prefs.diet);
        setTolerated(prefs.tolerated_ingredients);
      })
      .catch(() => undefined);
  }, []);

  function toggle(name: string) {
    setChecked((list) => (list.includes(name) ? list.filter((n) => n !== name) : [...list, name].slice(0, 20)));
  }

  function addAll(names: string[]) {
    setChecked((list) => [...list, ...names.filter((n) => !list.includes(n))].slice(0, 20));
  }

  const filters = () => ({
    servings,
    diet,
    difficulties,
    max_minutes: maxMinutes ? Number(maxMinutes) : undefined,
    min_health: minHealth !== "" ? Number(minHealth) : undefined,
    max_health: maxHealth !== "" ? Number(maxHealth) : undefined,
    include_missing_utensils: withMissingUtensils,
  });

  async function search(event?: FormEvent) {
    event?.preventDefault();
    const words = text.trim();
    if (!words && checked.length === 0) {
      setError("Coche au moins un ingrédient ou écris une recherche.");
      return;
    }
    setError(null);
    setSiteErrors([]);
    const isUrl = /^https?:\/\//i.test(words);
    setBusy(isUrl ? "Lecture de la recette…" : "Recherche sur Marmiton, Cuisine AZ, Ptitchef et dans les recettes créées… (jusqu'à 30 secondes)");
    try {
      if (isUrl) {
        setResults([await api.importRecipe(words)]);
        setResultsLabel("Recette importée");
      } else {
        const result = await api.searchRecipes({ ingredients: checked, only, text: words || undefined, ...filters() });
        setResults(result.recipes);
        setSiteErrors(result.errors);
        setResultsLabel(checked.length ? "Avec tes ingrédients" : "Résultats");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recherche impossible.");
    } finally {
      setBusy(null);
    }
  }

  async function invent(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy("L'IA invente des recettes… (jusqu'à une minute)");
    try {
      const cards = await api.generateRecipes({ count: aiCount, servings, diet, ingredients: checked, only, wish: aiWish.trim() || undefined });
      setResults(cards);
      setResultsLabel("Inventées par l'IA");
      setAskAi(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Génération impossible.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <form onSubmit={search} className="mb-4 space-y-3 rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
        <IngredientPicker checked={checked} hidden={tolerated} onToggle={toggle} onPhoto={() => setPhoto(true)} />
        {checked.length > 0 && (
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 size-4 accent-brand-600" checked={only} onChange={(e) => setOnly(e.target.checked)} />
            <span>
              Uniquement ces ingrédients
              <span className="block text-xs text-stone-500">
                {tolerated.length ? `Toujours tolérés : ${tolerated.join(", ")}` : "Aucun ingrédient toléré"} (réglables dans Préférences)
              </span>
            </span>
          </label>
        )}
        <input
          className={inputClass}
          placeholder="Ou une recherche libre (« gratin », « soupe »), ou le lien d'une recette"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        {compact && (
          <button type="button" className="text-sm text-brand-700 hover:underline dark:text-brand-500" onClick={() => setShowFilters((v) => !v)}>
            {showFilters ? "Masquer les filtres" : "Filtres (personnes, régime, difficulté, temps, santé)"}
          </button>
        )}
        {showFilters && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-sm">
              <span className="mb-1 block font-medium">Personnes</span>
              <input type="number" min={1} max={999} value={servings} className={inputClass}
                onChange={(e) => setServings(Math.min(999, Math.max(1, Number(e.target.value) || 1)))} />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Régime</span>
              <select className={inputClass} value={diet} onChange={(e) => setDiet(e.target.value as Diet)}>
                <option value="none">Tous</option>
                <option value="vegetarian">Végétarien</option>
                <option value="vegan">Vegan</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Temps total (préparation + cuisson)</span>
              <select className={inputClass} value={maxMinutes} onChange={(e) => setMaxMinutes(e.target.value)}>
                <option value="">Peu importe</option>
                {[15, 30, 45, 60, 90].map((m) => (
                  <option key={m} value={m}>
                    {m} min au plus
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="text-sm">
              <legend className="mb-1 font-medium">Score santé (sur 10)</legend>
              <div className="flex items-center gap-2">
                <input type="number" min={0} max={10} step={0.5} placeholder="de 0" aria-label="Score santé minimum" value={minHealth}
                  onChange={(e) => setMinHealth(e.target.value)} className={inputClass + " w-20"} />
                <span>à</span>
                <input type="number" min={0} max={10} step={0.5} placeholder="10" aria-label="Score santé maximum" value={maxHealth}
                  onChange={(e) => setMaxHealth(e.target.value)} className={inputClass + " w-20"} />
              </div>
            </fieldset>
            <fieldset className="text-sm sm:col-span-2">
              <legend className="mb-1 font-medium">Difficulté (aucune cochée : toutes)</legend>
              <div className="flex flex-wrap gap-4">
                {DIFFICULTIES.map((d) => (
                  <label key={d.value} className="flex items-center gap-1.5">
                    <input type="checkbox" className="size-4 accent-brand-600" checked={difficulties.includes(d.value)}
                      onChange={(e) => setDifficulties((list) => (e.target.checked ? [...list, d.value] : list.filter((x) => x !== d.value)))} />
                    {d.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={withMissingUtensils} onChange={(e) => setWithMissingUtensils(e.target.checked)} className="size-4 accent-brand-600" />
              Montrer aussi les recettes qui demandent un ustensile que je n'ai pas
            </label>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="submit" className={primaryButton} disabled={busy !== null}>
            Chercher des recettes
          </button>
          <button type="button" className="rounded-lg bg-violet-600 px-4 py-2 font-medium text-white transition hover:bg-violet-700 disabled:opacity-60"
            onClick={() => setAskAi((v) => !v)} disabled={busy !== null}>
            Inventer avec l'IA
          </button>
        </div>
      </form>

      {askAi && (
        <form onSubmit={invent} className="mb-4 grid gap-3 rounded-xl border border-violet-300 bg-violet-50 p-4 sm:grid-cols-[1fr_auto_auto] dark:border-violet-900 dark:bg-stone-900">
          <input className={inputClass} placeholder="Une envie ? (facultatif : soupe, plat rapide, sans four…)" value={aiWish}
            onChange={(e) => setAiWish(e.target.value)} maxLength={200} />
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
            L'IA part des ingrédients cochés{only ? " (et seulement d'eux)" : ""}, de tes préférences et des filtres. Une recette inventée
            est gardée si tu la programmes, l'épingles ou la mets en favori.
          </p>
        </form>
      )}

      {busy && <Loading label={busy} />}
      <ErrorMessage message={error} />
      {between}

      {results && !busy && (
        <section className="mb-8">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
              {resultsLabel} · {results.length}
            </h2>
            <button className="text-sm text-stone-500 hover:underline" onClick={() => setResults(null)}>
              Masquer
            </button>
          </div>
          {siteErrors.length > 0 && (
            <p className="mb-2 text-xs text-amber-700 dark:text-amber-400">Certains sites n'ont pas répondu : {siteErrors.slice(0, 2).join(" ")}</p>
          )}
          {results.length === 0 ? (
            <div className="rounded-xl border border-dashed border-stone-300 p-6 text-center text-sm text-stone-600 dark:border-stone-700 dark:text-stone-400">
              Aucune recette ne correspond.{" "}
              {only ? "Décoche « Uniquement ces ingrédients » ou ajoute des ingrédients tolérés dans Préférences." : "Essaie moins de filtres ou d'autres ingrédients."}
            </div>
          ) : (
            <div className={"grid gap-4 sm:grid-cols-2" + (compact ? "" : " lg:grid-cols-3")}>
              {results.map((card) => (
                <RecipeCardView key={card.id} card={card} onOpen={() => onOpen(card, { ingredients: checked, servings })} />
              ))}
            </div>
          )}
        </section>
      )}
      {photo && <PhotoIngredients onFound={addAll} onClose={() => setPhoto(false)} />}
    </div>
  );
}

/** Ingrédients à cocher : recherche dans la liste (noms vus dans les recettes des sites), les plus courants, photo. */
function IngredientPicker({ checked, hidden, onToggle, onPhoto }: {
  checked: string[];
  hidden: string[]; // ingrédients toujours tolérés : inutile de les proposer
  onToggle: (name: string) => void;
  onPhoto: () => void;
}) {
  const [query, setQuery] = useState("");
  const [popular, setPopular] = useState<Term[]>([]);
  const [suggestions, setSuggestions] = useState<Term[]>([]);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    api.ingredients("", 24).then(setPopular).catch(() => setPopular([]));
  }, []);

  useEffect(() => {
    window.clearTimeout(timer.current);
    const q = query.trim();
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    timer.current = window.setTimeout(() => {
      api.ingredients(q, 12).then(setSuggestions).catch(() => setSuggestions([]));
    }, 200);
  }, [query]);

  function pick(name: string) {
    onToggle(name);
    setQuery("");
    setSuggestions([]);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">Ingrédients à utiliser</span>
        <button type="button" className={secondaryButton + " py-1 text-sm"} onClick={onPhoto}>
          📷 Photo
        </button>
      </div>
      {checked.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {checked.map((name) => (
            <button key={name} type="button" onClick={() => onToggle(name)}
              className="rounded-full bg-brand-600 px-2.5 py-1 text-sm text-white hover:bg-brand-700" aria-label={`Décocher ${name}`}>
              ✓ {name} ✕
            </button>
          ))}
        </div>
      )}
      <div className="relative">
        <input className={inputClass} placeholder="Ajouter un ingrédient (carotte, poulet, riz…)" value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && suggestions[0]) {
              e.preventDefault();
              pick(suggestions[0].name);
            }
          }} />
        {suggestions.length > 0 && (
          <ul className="absolute z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-stone-200 bg-white shadow-lg dark:border-stone-700 dark:bg-stone-900">
            {suggestions.map((s) => (
              <li key={s.name}>
                <button type="button" className="flex w-full justify-between px-3 py-2 text-left text-sm hover:bg-stone-50 dark:hover:bg-stone-800" onClick={() => pick(s.name)}>
                  <span>{checked.includes(s.name) ? "✓ " : ""}{s.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {popular.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {popular.filter((t) => !checked.includes(t.name) && !hidden.some((h) => h.toLowerCase() === t.name.toLowerCase())).slice(0, 18).map((t) => (
            <button key={t.name} type="button" onClick={() => onToggle(t.name)}
              className="rounded-full border border-stone-300 px-2.5 py-0.5 text-xs text-stone-700 hover:border-brand-500 dark:border-stone-700 dark:text-stone-300">
              + {t.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
