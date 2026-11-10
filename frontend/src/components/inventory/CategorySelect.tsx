import { useEffect, useState } from "react";
import { api, type Category } from "../../api";
import { inputClass } from "../ui";

let cached: Promise<Category[]> | null = null; // la liste des catégories ne change pas : chargée une fois

/** Sélecteur « Toutes les catégories » ou une catégorie, à côté d'une recherche d'aliment. */
export default function CategorySelect({ value, onChange, className = "" }: { value: string; onChange: (id: string) => void; className?: string }) {
  const [categories, setCategories] = useState<Category[]>([]);

  useEffect(() => {
    cached ??= api.categories().catch(() => {
      cached = null;
      return [];
    });
    cached.then(setCategories);
  }, []);

  return (
    <select className={inputClass + " sm:w-56 " + className} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Catégorie">
      <option value="">Toutes les catégories</option>
      {categories.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}
