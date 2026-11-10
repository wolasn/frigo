import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Alerts, type Food, type Inventory, type Item } from "../api";
import AddItemDialog from "../components/inventory/AddItemDialog";
import { EditDialog, HistoryDialog, RemoveDialog } from "../components/inventory/ItemDialogs";
import LocationsDialog from "../components/inventory/LocationsDialog";
import { ErrorMessage, inputClass, primaryButton, secondaryButton } from "../components/ui";
import { expiryText, formatQuantity, STATUS_STYLES } from "../format";

type Dialog = { type: "add" } | { type: "history" } | { type: "locations" } | { type: "remove"; item: Item } | { type: "edit"; item: Item } | null;

export default function InventoryPage() {
  const [inventories, setInventories] = useState<Inventory[]>([]);
  const [inventoryId, setInventoryId] = useState<string | null>(null);
  const [items, setItems] = useState<Item[] | null>(null);
  const [alerts, setAlerts] = useState<Alerts>({ expired: 0, soon: 0, best_before_passed: 0 });
  const [basics, setBasics] = useState<Food[]>([]);
  const [locationFilter, setLocationFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState<string | null>(null);

  const loadInventories = useCallback(() => {
    api
      .inventories()
      .then((list) => {
        setInventories(list);
        setInventoryId((current) => current ?? list.find((i) => i.kind === "personal")?.id ?? list[0]?.id ?? null);
      })
      .catch(() => setError("Impossible de charger tes inventaires."));
  }, []);

  useEffect(() => {
    loadInventories();
    api.basics().then(setBasics).catch(() => setBasics([]));
  }, []);

  const inventory = inventories.find((i) => i.id === inventoryId) ?? null;

  const reload = useCallback(() => {
    if (!inventoryId) return;
    api
      .items(inventoryId)
      .then((data) => {
        setItems(data.items);
        setAlerts(data.alerts);
      })
      .catch(() => setError("Impossible de charger l'inventaire."));
  }, [inventoryId]);

  useEffect(reload, [reload]);

  const visibleItems = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (items ?? []).filter(
      (i) => (locationFilter === "all" || i.storage_location_id === locationFilter) && (!term || i.name.toLowerCase().includes(term)),
    );
  }, [items, locationFilter, search]);

  if (!inventory) {
    return error ? <ErrorMessage message={error} /> : <p className="text-stone-500">Chargement…</p>;
  }

  const groups = inventory.locations
    .map((location) => ({ location, items: visibleItems.filter((i) => i.storage_location_id === location.id) }))
    .filter((g) => g.items.length > 0);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">Inventaire</h1>
          {inventories.length > 1 && (
            <select className={inputClass + " w-auto py-1"} value={inventory.id} onChange={(e) => setInventoryId(e.target.value)}>
              {inventories.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={secondaryButton} onClick={() => setDialog({ type: "locations" })}>
            Lieux
          </button>
          <button className={secondaryButton} onClick={() => setDialog({ type: "history" })}>
            Historique
          </button>
          <button className={primaryButton} onClick={() => setDialog({ type: "add" })}>
            + Ajouter
          </button>
        </div>
      </div>

      <AlertSummary alerts={alerts} />

      {basics.length > 0 && (
        <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">
          Toujours disponible : {basics.map((b) => b.name).join(", ")}
        </p>
      )}

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <input className={inputClass + " sm:max-w-xs"} placeholder="Filtrer par nom" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {[{ id: "all", name: "Tout" }, ...inventory.locations].map((l) => (
            <button
              key={l.id}
              onClick={() => setLocationFilter(l.id)}
              className={
                "shrink-0 rounded-full px-3 py-1 text-sm " +
                (locationFilter === l.id
                  ? "bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900"
                  : "bg-stone-200 text-stone-700 hover:bg-stone-300 dark:bg-stone-800 dark:text-stone-300")
              }
            >
              {l.name}
            </button>
          ))}
        </div>
      </div>

      <ErrorMessage message={error} />

      {items === null ? (
        <p className="text-stone-500">Chargement…</p>
      ) : items.length === 0 ? (
        <EmptyState onAdd={() => setDialog({ type: "add" })} />
      ) : groups.length === 0 ? (
        <p className="text-stone-500">Aucun article ne correspond.</p>
      ) : (
        <div className="space-y-6">
          {groups.map(({ location, items: groupItems }) => (
            <section key={location.id}>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
                {location.name} · {groupItems.length}
              </h2>
              <ul className="divide-y divide-stone-200 overflow-hidden rounded-xl border border-stone-200 bg-white dark:divide-stone-800 dark:border-stone-800 dark:bg-stone-900">
                {groupItems.map((item) => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    onEdit={() => setDialog({ type: "edit", item })}
                    onRemove={() => setDialog({ type: "remove", item })}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      {dialog?.type === "add" && (
        <AddItemDialog
          inventory={inventory}
          defaultLocationId={locationFilter !== "all" ? locationFilter : undefined}
          onAdded={reload}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.type === "remove" && <RemoveDialog item={dialog.item} onDone={reload} onClose={() => setDialog(null)} />}
      {dialog?.type === "edit" && <EditDialog item={dialog.item} inventory={inventory} onDone={reload} onClose={() => setDialog(null)} />}
      {dialog?.type === "locations" && (
        <LocationsDialog
          inventoryId={inventory.id}
          inventoryName={inventory.name}
          canEdit={inventory.role === "admin"}
          onChanged={() => {
            loadInventories();
            reload();
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.type === "history" && <HistoryDialog inventory={inventory} onRestored={reload} onClose={() => setDialog(null)} />}
    </div>
  );
}

function ItemRow({ item, onEdit, onRemove }: { item: Item; onEdit: () => void; onRemove: () => void }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
      <div className="min-w-[10rem] flex-1">
        <p className="truncate font-medium">
          {item.name}
          {item.kind === "leftover" && (
            <span className="ml-2 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">reste</span>
          )}
        </p>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          {formatQuantity(item.quantity, item.unit)}
          {item.reserved > 0 && <span className="text-sky-700 dark:text-sky-400"> · dont {formatQuantity(item.reserved, item.unit)} réservé</span>}
          {item.opened_on && " · ouvert"}
        </p>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1">
      <span className={"mr-1 rounded-full px-2.5 py-1 text-xs font-medium " + STATUS_STYLES[item.status]}>
        {expiryText(item)}
        {item.date_type === "estimated" && <span title="Date estimée"> ≈</span>}
      </span>
        <button onClick={onEdit} className="rounded-md px-2 py-1 text-sm text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800">
          Modifier
        </button>
        <button onClick={onRemove} className="rounded-md px-2 py-1 text-sm font-medium text-brand-700 hover:bg-brand-50 dark:text-brand-500 dark:hover:bg-stone-800">
          Retirer
        </button>
      </div>
    </li>
  );
}

function AlertSummary({ alerts }: { alerts: Alerts }) {
  const chips = [
    alerts.expired > 0 && { text: `${alerts.expired} périmé(s)`, style: STATUS_STYLES.expired },
    alerts.soon > 0 && { text: `${alerts.soon} expire(nt) bientôt`, style: STATUS_STYLES.soon },
    alerts.best_before_passed > 0 && { text: `${alerts.best_before_passed} DDM dépassée(s)`, style: STATUS_STYLES.best_before_passed },
  ].filter(Boolean) as { text: string; style: string }[];
  if (chips.length === 0) return null;
  return (
    <div className="mb-4 flex flex-wrap gap-2" role="status">
      {chips.map((c) => (
        <span key={c.text} className={"rounded-full px-3 py-1 text-sm font-medium " + c.style}>
          {c.text}
        </span>
      ))}
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="rounded-xl border border-dashed border-stone-300 p-8 text-center dark:border-stone-700">
      <p className="mb-1 font-medium">Ton inventaire est vide</p>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">Ajoute ce que tu as dans ton frigo, tes placards ou ta corbeille à fruits.</p>
      <button className={primaryButton} onClick={onAdd}>
        Ajouter un premier article
      </button>
    </div>
  );
}
