import { useEffect, useState, type FormEvent } from "react";
import { api, type Utensil } from "../api";
import { ErrorMessage, inputClass, secondaryButton, Loading } from "../components/ui";

const CATEGORIES: { id: Utensil["category"]; label: string }[] = [
  { id: "cooking", label: "Cuisson" },
  { id: "preparation", label: "Préparation" },
  { id: "container", label: "Récipients" },
];

export default function UtensilsPage() {
  const [utensils, setUtensils] = useState<Utensil[] | null>(null);
  const [name, setName] = useState("");
  const [category, setCategory] = useState<Utensil["category"]>("container");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.utensils().then(setUtensils).catch(() => setError("Impossible de charger les ustensiles."));
  }, []);

  async function toggle(utensil: Utensil) {
    setUtensils((list) => list?.map((u) => (u.id === utensil.id ? { ...u, owned: !u.owned } : u)) ?? null);
    try {
      await api.setUtensilOwned(utensil.id, !utensil.owned);
    } catch {
      setUtensils((list) => list?.map((u) => (u.id === utensil.id ? utensil : u)) ?? null);
      setError("Modification impossible.");
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const created = await api.createUtensil(name.trim(), category);
      setUtensils((list) => [...(list ?? []), created]);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ajout impossible.");
    }
  }

  async function remove(utensil: Utensil) {
    try {
      await api.deleteUtensil(utensil.id);
      setUtensils((list) => list?.filter((u) => u.id !== utensil.id) ?? null);
    } catch {
      setError("Suppression impossible.");
    }
  }

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">Mes ustensiles</h1>
      <p className="mb-5 text-sm text-stone-600 dark:text-stone-400">
        Les recettes qui demandent un ustensile non coché sont masquées des propositions (sauf si tu choisis de les montrer).
      </p>
      <ErrorMessage message={error} />
      {utensils === null ? (
        <Loading />
      ) : (
        <div className="grid gap-5 sm:grid-cols-3">
          {CATEGORIES.map((c) => (
            <section key={c.id}>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">{c.label}</h2>
              <ul className="space-y-1">
                {utensils
                  .filter((u) => u.category === c.id)
                  .map((u) => (
                    <li key={u.id} className="flex items-center justify-between gap-2">
                      <label className="flex items-center gap-2">
                        <input type="checkbox" checked={u.owned} onChange={() => toggle(u)} className="size-4 accent-brand-600" />
                        {u.name}
                      </label>
                      {u.is_custom && (
                        <button onClick={() => remove(u)} className="text-xs text-stone-500 hover:text-red-600" aria-label={`Supprimer ${u.name}`}>
                          Supprimer
                        </button>
                      )}
                    </li>
                  ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <form onSubmit={add} className="mt-8 flex max-w-xl flex-col gap-2 sm:flex-row">
        <input className={inputClass} placeholder="Autre ustensile (ex. machine à pain)" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
        <select className={inputClass + " sm:w-44"} value={category} onChange={(e) => setCategory(e.target.value as Utensil["category"])}>
          {CATEGORIES.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
        <button type="submit" className={secondaryButton} disabled={!name.trim()}>
          Ajouter
        </button>
      </form>
    </div>
  );
}
