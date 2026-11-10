import { useCallback, useEffect, useState } from "react";
import { api, type Food, type LocationShelfLife, type ManagedLocation, type ShelfLifeRow, type StorageType } from "../../api";
import { STORAGE_LABELS } from "../../format";
import { ErrorMessage, inputClass, Modal, secondaryButton } from "../ui";

const TYPE_HINT = "Le type donne les durées de conservation par défaut (un « Frigo du garage » se comporte comme un réfrigérateur).";

/** Lieux de rangement d'un inventaire : ajouter, renommer, changer le type, ordonner, supprimer, régler les durées. */
export default function LocationsDialog({
  inventoryId,
  inventoryName,
  canEdit,
  onChanged,
  onClose,
}: {
  inventoryId: string;
  inventoryName: string;
  canEdit: boolean;
  onChanged: () => void;
  onClose: () => void;
}) {
  const [locations, setLocations] = useState<ManagedLocation[] | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState<StorageType>("pantry");
  const [shelfLifeOf, setShelfLifeOf] = useState<ManagedLocation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.locations(inventoryId).then(setLocations).catch(() => setError("Impossible de charger les lieux."));
  }, [inventoryId]);
  useEffect(load, [load]);

  async function act(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action impossible.");
    }
  }

  function move(index: number, delta: number) {
    if (!locations) return;
    const ids = locations.map((l) => l.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + delta, 0, moved);
    act(() => api.reorderLocations(inventoryId, ids));
  }

  if (shelfLifeOf) {
    return <ShelfLifeDialog location={shelfLifeOf} canEdit={canEdit} onBack={() => setShelfLifeOf(null)} onChanged={onChanged} onClose={onClose} />;
  }

  return (
    <Modal title={`Lieux de rangement · ${inventoryName}`} onClose={onClose}>
      <div className="space-y-4">
        {!canEdit && <p className="text-sm text-stone-500">Seuls les administrateurs de cet inventaire modifient ses lieux.</p>}
        <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 dark:divide-stone-800 dark:border-stone-800">
          {(locations ?? []).map((location, index) => (
            <li key={location.id} className="flex flex-wrap items-center gap-2 p-2">
              {canEdit ? (
                <>
                  <input
                    className={inputClass + " min-w-0 flex-1 py-1"}
                    defaultValue={location.name}
                    aria-label="Nom du lieu"
                    maxLength={60}
                    onBlur={(e) => {
                      const value = e.target.value.trim();
                      if (value && value !== location.name) act(() => api.updateLocation(location.id, { name: value }));
                    }}
                  />
                  <select
                    className={inputClass + " w-auto py-1"}
                    value={location.storage_type}
                    aria-label="Type de lieu"
                    title={TYPE_HINT}
                    onChange={(e) => act(() => api.updateLocation(location.id, { storage_type: e.target.value as StorageType }))}
                  >
                    {Object.entries(STORAGE_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <span className="flex-1">
                  {location.name} <span className="text-xs text-stone-500">· {STORAGE_LABELS[location.storage_type]}</span>
                </span>
              )}
              <span className="text-xs text-stone-500">{location.item_count} article(s)</span>
              <span className="flex items-center gap-1">
                <button className="rounded px-2 py-1 text-sm text-brand-700 hover:underline dark:text-brand-500" onClick={() => setShelfLifeOf(location)}>
                  Durées
                </button>
                {canEdit && (
                  <>
                    <button className="rounded px-1.5 text-stone-500 hover:bg-stone-100 disabled:opacity-30 dark:hover:bg-stone-800" disabled={index === 0} onClick={() => move(index, -1)} aria-label={`Monter ${location.name}`}>
                      ↑
                    </button>
                    <button
                      className="rounded px-1.5 text-stone-500 hover:bg-stone-100 disabled:opacity-30 dark:hover:bg-stone-800"
                      disabled={index === (locations?.length ?? 0) - 1}
                      onClick={() => move(index, 1)}
                      aria-label={`Descendre ${location.name}`}
                    >
                      ↓
                    </button>
                    <button
                      className="rounded px-1.5 text-stone-400 hover:text-red-600 disabled:opacity-30"
                      disabled={location.item_count > 0}
                      title={location.item_count > 0 ? "Déplace d'abord ses articles" : undefined}
                      onClick={() => act(() => api.deleteLocation(location.id))}
                      aria-label={`Supprimer ${location.name}`}
                    >
                      ✕
                    </button>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>

        {canEdit && (
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              act(() => api.addLocation(inventoryId, name.trim(), type)).then(() => setName(""));
            }}
          >
            <input className={inputClass + " min-w-0 flex-1"} placeholder="Nouveau lieu (ex. Cave, Frigo du garage)" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
            <select className={inputClass + " w-auto"} value={type} onChange={(e) => setType(e.target.value as StorageType)} aria-label="Type du nouveau lieu">
              {Object.entries(STORAGE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <button className={secondaryButton} disabled={!name.trim()}>
              Ajouter
            </button>
          </form>
        )}
        <p className="text-xs text-stone-500">{TYPE_HINT}</p>
        <ErrorMessage message={error} />
      </div>
    </Modal>
  );
}

function ShelfLifeDialog({
  location,
  canEdit,
  onBack,
  onChanged,
  onClose,
}: {
  location: ManagedLocation;
  canEdit: boolean;
  onBack: () => void;
  onChanged: () => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<LocationShelfLife | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Food[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.locationShelfLife(location.id).then(setData).catch(() => setError("Impossible de charger les durées."));
  }, [location.id]);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    const timer = setTimeout(() => api.searchFoods(query.trim()).then(setResults).catch(() => setResults([])), 250);
    return () => clearTimeout(timer);
  }, [query]);

  async function save(kind: "categories" | "foods", id: string, days: number | null) {
    setError(null);
    try {
      setData(await api.setShelfLife(location.id, kind, id, days));
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible.");
    }
  }

  const listed = new Set((data?.foods ?? []).map((f) => f.id));

  return (
    <Modal title={`Durées de conservation · ${location.name}`} onClose={onClose}>
      <div className="space-y-4">
        <button className="text-sm text-brand-700 hover:underline dark:text-brand-500" onClick={onBack}>
          ‹ Retour aux lieux
        </button>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Durée d'un produit fermé rangé ici, en jours. Les valeurs par défaut sont celles d'un lieu de type{" "}
          {STORAGE_LABELS[location.storage_type].toLowerCase()} ; une durée propre à un aliment passe avant celle de sa catégorie. Les dates
          estimées des articles déjà rangés ici sont recalculées.
        </p>
        {data && (
          <>
            <ShelfLifeTable title="Par catégorie" rows={data.categories} canEdit={canEdit} onSave={(id, days) => save("categories", id, days)} />
            <ShelfLifeTable title="Aliments particuliers" rows={data.foods} canEdit={canEdit} onSave={(id, days) => save("foods", id, days)} />
            {canEdit && (
              <div>
                <input className={inputClass} placeholder="Régler un autre aliment : tape son nom" value={query} onChange={(e) => setQuery(e.target.value)} />
                {results.filter((f) => !listed.has(f.id)).length > 0 && (
                  <ul className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-stone-200 text-sm dark:border-stone-800">
                    {results
                      .filter((f) => !listed.has(f.id))
                      .map((f) => {
                        const category = data.categories.find((c) => c.id === f.category_id);
                        return (
                          <li key={f.id}>
                            <button
                              className="w-full px-2 py-1.5 text-left hover:bg-stone-100 dark:hover:bg-stone-800"
                              onClick={() => save("foods", f.id, category?.days ?? category?.default_days ?? 7).then(() => setQuery(""))}
                            >
                              {f.name} <span className="text-xs text-stone-500">· {f.category_name}</span>
                            </button>
                          </li>
                        );
                      })}
                  </ul>
                )}
              </div>
            )}
          </>
        )}
        <ErrorMessage message={error} />
      </div>
    </Modal>
  );
}

function ShelfLifeTable({
  title,
  rows,
  canEdit,
  onSave,
}: {
  title: string;
  rows: ShelfLifeRow[];
  canEdit: boolean;
  onSave: (id: string, days: number | null) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <section>
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 text-sm dark:divide-stone-800 dark:border-stone-800">
        {rows.map((row) => {
          const value = row.days ?? row.default_days;
          return (
            <li key={row.id} className="flex items-center gap-2 px-2 py-1.5">
              <span className="min-w-0 flex-1">{row.name}</span>
              {canEdit ? (
                <div className="w-20 shrink-0">
                <input
                  key={`${row.id}-${value}`}
                  type="number"
                  min={0}
                  max={3650}
                  inputMode="numeric"
                  className={inputClass + " py-1 text-right" + (row.days !== null ? " border-brand-500" : "")}
                  defaultValue={value ?? ""}
                  placeholder="—"
                  aria-label={`Jours pour ${row.name}`}
                  onBlur={(e) => {
                    const raw = e.target.value.trim();
                    if (raw === "") {
                      if (row.days !== null) onSave(row.id, null);
                      return;
                    }
                    const days = Math.min(3650, Math.max(0, Math.round(Number(raw))));
                    if (!Number.isNaN(days) && days !== value) onSave(row.id, days === row.default_days ? null : days);
                  }}
                />
                </div>
              ) : (
                <span className="w-20 text-right">{value ?? "—"}</span>
              )}
              <span className="w-24 shrink-0 text-xs text-stone-500">
                {row.days !== null ? (
                  canEdit ? (
                    <button className="hover:underline" onClick={() => onSave(row.id, null)}>
                      défaut : {row.default_days ?? "—"} ↺
                    </button>
                  ) : (
                    `défaut : ${row.default_days ?? "—"}`
                  )
                ) : (
                  "par défaut"
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
