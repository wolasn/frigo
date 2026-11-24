import { useEffect, useState } from "react";
import { api, type Category, type Food } from "../api";
import { inputClass, primaryButton, secondaryButton, ErrorMessage, Field } from "./ui";
import CategorySelect from "./CategorySelect";

const REFERENCE_UNITS: { value: Food["reference_unit"]; label: string }[] = [
  { value: "g", label: "Au poids (g, kg)" },
  { value: "ml", label: "Au volume (ml, L)" },
  { value: "piece", label: "À la pièce" },
];

/** Recherche dans le catalogue, avec création d'un aliment personnel s'il manque. */
export default function FoodPicker({ value, onChange }: { value: Food | null; onChange: (food: Food | null) => void }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [results, setResults] = useState<Food[]>([]);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (value) return;
    const timer = setTimeout(() => {
      api.searchFoods(query, category).then(setResults).catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [query, category, value]);

  if (value) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-stone-300 px-3 py-2 dark:border-stone-700">
        <span>
          <span className="font-medium">{value.name}</span>
          <span className="ml-2 text-sm text-stone-500">{value.category_name}</span>
        </span>
        <button type="button" onClick={() => onChange(null)} className="text-sm text-brand-700 hover:underline dark:text-brand-500">
          Changer
        </button>
      </div>
    );
  }

  if (creating) {
    return <CreateFood initialName={query} onCreated={onChange} onCancel={() => setCreating(false)} />;
  }

  return (
    <div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          className={inputClass}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher : carotte, lait, riz…"
          autoFocus
        />
        <CategorySelect value={category} onChange={setCategory} />
      </div>
      <ul className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-stone-200 dark:border-stone-800">
        {results.map((food) => (
          <li key={food.id}>
            <button
              type="button"
              onClick={() => onChange(food)}
              className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-stone-100 dark:hover:bg-stone-800"
            >
              <span>{food.name}</span>
              <span className="text-xs text-stone-500">
                {food.category_name}
                {food.is_private && " · perso"}
              </span>
            </button>
          </li>
        ))}
        <li>
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="w-full px-3 py-2 text-left text-sm font-medium text-brand-700 hover:bg-stone-100 dark:text-brand-500 dark:hover:bg-stone-800"
          >
            + Créer {query.trim() ? `« ${query.trim()} »` : "un aliment"}
          </button>
        </li>
      </ul>
    </div>
  );
}

function CreateFood({
  initialName,
  onCreated,
  onCancel,
}: {
  initialName: string;
  onCreated: (food: Food) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initialName.trim());
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [unit, setUnit] = useState<Food["reference_unit"]>("g");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.categories().then(setCategories).catch(() => setCategories([]));
  }, []);

  async function create() {
    setError(null);
    try {
      onCreated(await api.createFood(name.trim(), categoryId, unit));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Création impossible.");
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-stone-200 p-3 dark:border-stone-800">
      <p className="text-sm text-stone-600 dark:text-stone-400">Nouvel aliment, visible seulement par toi.</p>
      <Field label="Nom">
        <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
      </Field>
      <Field label="Catégorie">
        <select className={inputClass} value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="">Choisir…</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Se compte">
        <select className={inputClass} value={unit} onChange={(e) => setUnit(e.target.value as Food["reference_unit"])}>
          {REFERENCE_UNITS.map((u) => (
            <option key={u.value} value={u.value}>
              {u.label}
            </option>
          ))}
        </select>
      </Field>
      <ErrorMessage message={error} />
      <div className="flex gap-2">
        <button type="button" className={primaryButton} disabled={!name.trim() || !categoryId} onClick={create}>
          Créer
        </button>
        <button type="button" className={secondaryButton} onClick={onCancel}>
          Annuler
        </button>
      </div>
    </div>
  );
}
