import { useEffect, useState } from "react";
import { api, type Food, type RecipeEdit, type RecipeInput, type Utensil } from "../../api";
import { unitLabel } from "../../format";
import FoodPicker from "../inventory/FoodPicker";
import { ErrorMessage, Field, inputClass, Modal, primaryButton, secondaryButton, Loading } from "../ui";

const EXTRA_UNITS = ["cs", "cc", "pincee"];
const EXTRA_LABELS: Record<string, string> = { cs: "c. à soupe", cc: "c. à café", pincee: "pincée(s)" };

type Row = { key: number; food: Food | null; text: string; quantity: string; unit: string; optional: boolean };

let nextKey = 1;
const emptyRow = (): Row => ({ key: nextKey++, food: null, text: "", quantity: "", unit: "", optional: false });

function unitsOf(food: Food | null): string[] {
  return food ? [...food.units, ...EXTRA_UNITS] : [];
}

function rowsFrom(edit: RecipeEdit): Row[] {
  return edit.ingredients.map((i) => ({
    key: nextKey++,
    food: i.food_id
      ? ({ id: i.food_id, name: i.food_name ?? i.text, units: i.units.filter((u) => !EXTRA_UNITS.includes(u)), category_name: "" } as Food)
      : null,
    text: i.food_id ? "" : i.text,
    quantity: i.quantity !== null ? String(i.quantity).replace(".", ",") : "",
    unit: i.unit ?? "",
    optional: i.is_optional,
  }));
}

/** Création ou modification d'une recette personnelle. */
export default function RecipeEditor({ recipeId, onSaved, onClose }: { recipeId: string | null; onSaved: () => void; onClose: () => void }) {
  const [loaded, setLoaded] = useState(recipeId === null);
  const [id, setId] = useState<string | null>(recipeId);
  const [title, setTitle] = useState("");
  const [servings, setServings] = useState(4);
  const [prep, setPrep] = useState("");
  const [cook, setCook] = useState("");
  const [difficulty, setDifficulty] = useState<RecipeInput["difficulty"]>(null);
  const [imageUrl, setImageUrl] = useState("");
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const [steps, setSteps] = useState<string[]>([""]);
  const [utensils, setUtensils] = useState<Utensil[]>([]);
  const [chosen, setChosen] = useState<Record<string, "required" | "optional">>({});
  const [missing, setMissing] = useState<string[]>([]);
  const [status, setStatus] = useState<"draft" | "complete">("draft");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.utensils().then(setUtensils).catch(() => setUtensils([]));
    if (!recipeId) return;
    api
      .recipeForEdit(recipeId)
      .then((edit) => {
        setTitle(edit.title);
        setServings(edit.servings);
        setPrep(edit.prep_minutes?.toString() ?? "");
        setCook(edit.cook_minutes?.toString() ?? "");
        setDifficulty(edit.difficulty);
        setImageUrl(edit.image_url ?? "");
        setRows(edit.ingredients.length ? rowsFrom(edit) : [emptyRow()]);
        setSteps(edit.steps.length ? edit.steps : [""]);
        setChosen(Object.fromEntries(edit.utensils.map((u) => [u.utensil_id, u.optional ? "optional" : "required"])));
        setMissing(edit.missing);
        setStatus(edit.status);
        setLoaded(true);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Recette introuvable."));
  }, [recipeId]);

  function updateRow(key: number, patch: Partial<Row>) {
    setRows((list) => list.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function moveStep(index: number, delta: number) {
    setSteps((list) => {
      const next = [...list];
      const [step] = next.splice(index, 1);
      next.splice(index + delta, 0, step);
      return next;
    });
  }

  async function save(complete: boolean) {
    setError(null);
    const body: RecipeInput = {
      title: title.trim(),
      servings,
      prep_minutes: prep ? Number(prep) : null,
      cook_minutes: cook ? Number(cook) : null,
      difficulty,
      image_url: imageUrl.trim() || null,
      ingredients: rows
        .filter((r) => r.food || r.text.trim())
        .map((r) => {
          const quantity = Number(r.quantity.replace(",", "."));
          return {
            food_id: r.food?.id ?? null,
            text: r.food ? null : r.text.trim(),
            quantity: quantity > 0 ? quantity : null,
            unit: r.food ? r.unit || unitsOf(r.food)[0] : null,
            is_optional: r.optional,
          };
        }),
      steps: steps.map((s) => s.trim()).filter(Boolean),
      utensils: Object.entries(chosen).map(([utensil_id, kind]) => ({ utensil_id, optional: kind === "optional" })),
      complete,
    };
    setBusy(true);
    try {
      const saved = id ? await api.saveRecipe(id, body) : await api.createRecipe(body);
      setId(saved.id);
      setMissing(saved.missing);
      setStatus(saved.status);
      onSaved();
      if (complete) onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) {
    return (
      <Modal title="Recette" onClose={onClose}>
        {error ? <ErrorMessage message={error} /> : <Loading />}
      </Modal>
    );
  }

  return (
    <Modal title={id ? "Modifier ma recette" : "Nouvelle recette"} onClose={onClose}>
      <div className="space-y-5">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          {status === "complete"
            ? "Recette complète : elle apparaît dans les propositions."
            : "Brouillon : visible seulement dans « Mes recettes ». Marque-la complète pour qu'elle soit proposée."}
        </p>

        <Field label="Titre">
          <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
        </Field>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="Personnes">
            <input type="number" min={1} max={999} className={inputClass} value={servings} onChange={(e) => setServings(Math.min(999, Math.max(1, Number(e.target.value) || 1)))} />
          </Field>
          <Field label="Préparation (min)">
            <input type="number" min={0} className={inputClass} value={prep} onChange={(e) => setPrep(e.target.value)} />
          </Field>
          <Field label="Cuisson (min)">
            <input type="number" min={0} className={inputClass} value={cook} onChange={(e) => setCook(e.target.value)} />
          </Field>
          <Field label="Difficulté">
            <select className={inputClass} value={difficulty ?? ""} onChange={(e) => setDifficulty((e.target.value || null) as RecipeInput["difficulty"])}>
              <option value="">—</option>
              <option value="easy">Facile</option>
              <option value="medium">Moyen</option>
              <option value="hard">Difficile</option>
            </select>
          </Field>
        </div>
        <Field label="Image (lien, facultatif)">
          <input className={inputClass} value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://…" maxLength={500} />
        </Field>

        <section>
          <h3 className="mb-2 font-semibold">Ingrédients</h3>
          <ul className="space-y-3">
            {rows.map((row) => (
              <li key={row.key} className="rounded-lg border border-stone-200 p-3 dark:border-stone-800">
                {row.food || !row.text ? (
                  <FoodPicker value={row.food} onChange={(food) => updateRow(row.key, { food, unit: food ? unitsOf(food)[0] : "" })} />
                ) : (
                  <input className={inputClass} value={row.text} onChange={(e) => updateRow(row.key, { text: e.target.value })} />
                )}
                {row.food && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      className={inputClass + " w-24"}
                      inputMode="decimal"
                      placeholder="Qté"
                      value={row.quantity}
                      onChange={(e) => updateRow(row.key, { quantity: e.target.value })}
                      aria-label="Quantité"
                    />
                    <select className={inputClass + " w-36"} value={row.unit} onChange={(e) => updateRow(row.key, { unit: e.target.value })} aria-label="Unité">
                      {unitsOf(row.food).map((u) => (
                        <option key={u} value={u}>
                          {EXTRA_LABELS[u] ?? unitLabel(u)}
                        </option>
                      ))}
                    </select>
                    <label className="flex items-center gap-1.5 text-sm">
                      <input type="checkbox" className="size-4 accent-brand-600" checked={row.optional} onChange={(e) => updateRow(row.key, { optional: e.target.checked })} />
                      facultatif
                    </label>
                    <button className="ml-auto text-sm text-stone-500 hover:text-red-600" onClick={() => setRows((list) => list.filter((r) => r.key !== row.key))}>
                      Retirer
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          <button className={secondaryButton + " mt-2 py-1.5 text-sm"} onClick={() => setRows((list) => [...list, emptyRow()])}>
            + Ingrédient
          </button>
        </section>

        <section>
          <h3 className="mb-2 font-semibold">Étapes</h3>
          <ol className="space-y-2">
            {steps.map((step, index) => (
              <li key={index} className="flex gap-2">
                <span className="pt-2 text-sm text-stone-500">{index + 1}.</span>
                <textarea
                  className={inputClass + " min-h-16"}
                  value={step}
                  onChange={(e) => setSteps((list) => list.map((s, i) => (i === index ? e.target.value : s)))}
                />
                <div className="flex flex-col gap-1 text-sm text-stone-500">
                  <button disabled={index === 0} onClick={() => moveStep(index, -1)} aria-label="Monter" className="disabled:opacity-30">↑</button>
                  <button disabled={index === steps.length - 1} onClick={() => moveStep(index, 1)} aria-label="Descendre" className="disabled:opacity-30">↓</button>
                  <button onClick={() => setSteps((list) => (list.length > 1 ? list.filter((_, i) => i !== index) : [""]))} aria-label="Supprimer l'étape">×</button>
                </div>
              </li>
            ))}
          </ol>
          <button className={secondaryButton + " mt-2 py-1.5 text-sm"} onClick={() => setSteps((list) => [...list, ""])}>
            + Étape
          </button>
        </section>

        <section>
          <h3 className="mb-2 font-semibold">Ustensiles</h3>
          <div className="flex flex-wrap gap-1.5">
            {utensils.map((u) => {
              const state = chosen[u.id];
              const next = state === undefined ? "required" : state === "required" ? "optional" : undefined;
              return (
                <button
                  key={u.id}
                  onClick={() =>
                    setChosen((c) => {
                      const copy = { ...c };
                      if (next) copy[u.id] = next;
                      else delete copy[u.id];
                      return copy;
                    })
                  }
                  className={
                    "rounded-full px-3 py-1 text-sm " +
                    (state === "required"
                      ? "bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900"
                      : state === "optional"
                        ? "border border-dashed border-stone-500"
                        : "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300")
                  }
                >
                  {u.name}
                  {state === "optional" && " (facultatif)"}
                </button>
              );
            })}
          </div>
          <p className="mt-1 text-xs text-stone-500">Un clic : requis. Deux clics : facultatif. Trois clics : retiré.</p>
        </section>

        {missing.length > 0 && status === "draft" && id && (
          <p className="text-sm text-stone-600 dark:text-stone-400">Pour la marquer complète, il manque : {missing.join(", ")}.</p>
        )}
        <ErrorMessage message={error} />
        <div className="flex flex-wrap gap-2">
          <button className={primaryButton} disabled={busy || !title.trim()} onClick={() => save(true)}>
            Enregistrer comme complète
          </button>
          <button className={secondaryButton} disabled={busy || !title.trim()} onClick={() => save(false)}>
            Enregistrer en brouillon
          </button>
        </div>
      </div>
    </Modal>
  );
}
