import { useEffect, useState } from "react";
import { api, type Inventory, type Item, type ItemUpdate, type Removal, type RemovalReason } from "../../api";
import { formatQuantity, isoToday, REASON_LABELS, unitLabel } from "../../format";
import { ErrorMessage, Field, inputClass, Modal, primaryButton, secondaryButton, Loading } from "../ui";

const MANUAL_REASONS: RemovalReason[] = ["consumed", "discarded", "given", "other"];

export function RemoveDialog({ item, onDone, onClose }: { item: Item; onDone: () => void; onClose: () => void }) {
  const [partial, setPartial] = useState(false);
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function remove(reason: RemovalReason) {
    setError(null);
    const amount = partial ? Number(quantity.replace(",", ".")) : undefined;
    if (partial && !(amount && amount > 0)) return setError("Indique la quantité retirée.");
    try {
      await api.removeItem(item.id, reason, amount, partial ? item.unit : undefined);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retrait impossible.");
    }
  }

  return (
    <Modal title={`Retirer « ${item.name} »`} onClose={onClose}>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">En stock : {formatQuantity(item.quantity, item.unit)}</p>
      <div className="mb-4 grid grid-cols-2 rounded-lg bg-stone-200 p-1 text-sm dark:bg-stone-800">
        {[false, true].map((p) => (
          <button
            key={String(p)}
            type="button"
            onClick={() => setPartial(p)}
            className={"rounded-md py-1.5 font-medium " + (partial === p ? "bg-white shadow-sm dark:bg-stone-900" : "text-stone-600 dark:text-stone-400")}
          >
            {p ? "Une partie" : "Tout"}
          </button>
        ))}
      </div>
      {partial && (
        <div className="mb-4">
          <Field label={`Quantité retirée (${unitLabel(item.unit)})`}>
            <input className={inputClass} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} autoFocus />
          </Field>
        </div>
      )}
      <p className="mb-2 text-sm font-medium">Pourquoi ?</p>
      <div className="grid grid-cols-2 gap-2">
        {MANUAL_REASONS.map((reason) => (
          <button key={reason} type="button" className={secondaryButton} onClick={() => remove(reason)}>
            {REASON_LABELS[reason]}
          </button>
        ))}
      </div>
      <div className="mt-3">
        <ErrorMessage message={error} />
      </div>
    </Modal>
  );
}

export function EditDialog({
  item,
  inventory,
  onDone,
  onClose,
}: {
  item: Item;
  inventory: Inventory;
  onDone: () => void;
  onClose: () => void;
}) {
  const [quantity, setQuantity] = useState(String(item.quantity).replace(".", ","));
  const [unit, setUnit] = useState(item.unit);
  const [locationId, setLocationId] = useState(item.storage_location_id);
  const [expiresOn, setExpiresOn] = useState(item.expires_on);
  const [dateType, setDateType] = useState<"use_by" | "best_before">(item.date_type === "best_before" ? "best_before" : "use_by");
  const [opened, setOpened] = useState(item.opened_on !== null);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setError(null);
    const amount = Number(quantity.replace(",", "."));
    if (!(amount > 0)) return setError("Indique une quantité supérieure à zéro.");
    const body: ItemUpdate = {};
    if (amount !== item.quantity || unit !== item.unit) Object.assign(body, { quantity: amount, unit });
    if (locationId !== item.storage_location_id) body.storage_location_id = locationId;
    if (opened !== (item.opened_on !== null)) body.opened_on = opened ? isoToday() : null;
    const dateChanged = expiresOn !== item.expires_on;
    const typeChanged = item.date_type !== "estimated" && dateType !== item.date_type;
    if (dateChanged || typeChanged) Object.assign(body, { expires_on: expiresOn, date_type: item.kind === "leftover" ? "use_by" : dateType });
    try {
      await api.updateItem(item.id, body);
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Modification impossible.");
    }
  }

  return (
    <Modal title={`Modifier « ${item.name} »`} onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label={item.kind === "leftover" ? "Parts" : "Quantité"}>
            <input className={inputClass} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </Field>
          {item.kind === "ingredient" && (
            <Field label="Unité">
              <select className={inputClass} value={unit} onChange={(e) => setUnit(e.target.value)}>
                {item.units.map((u) => (
                  <option key={u} value={u}>
                    {unitLabel(u)}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
        <Field label="Rangé dans" hint={item.date_type === "estimated" ? "Changer de lieu recalcule la date estimée." : undefined}>
          <select className={inputClass} value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            {inventory.locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date limite" hint={item.date_type === "estimated" && expiresOn === item.expires_on ? "Estimée" : undefined}>
            <input type="date" className={inputClass} value={expiresOn} onChange={(e) => setExpiresOn(e.target.value)} />
          </Field>
          {item.kind === "ingredient" && (item.date_type !== "estimated" || expiresOn !== item.expires_on) && (
            <Field label="Type de date">
              <select className={inputClass} value={dateType} onChange={(e) => setDateType(e.target.value as "use_by" | "best_before")}>
                <option value="use_by">DLC</option>
                <option value="best_before">DDM</option>
              </select>
            </Field>
          )}
        </div>
        {item.kind === "ingredient" && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={opened} onChange={(e) => setOpened(e.target.checked)} className="size-4 accent-brand-600" />
            Ouvert
          </label>
        )}
        <ErrorMessage message={error} />
        <div className="flex gap-2">
          <button type="button" className={primaryButton} onClick={save}>
            Enregistrer
          </button>
          <button type="button" className={secondaryButton} onClick={onClose}>
            Annuler
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function HistoryDialog({ inventory, onRestored, onClose }: { inventory: Inventory; onRestored: () => void; onClose: () => void }) {
  const [removals, setRemovals] = useState<Removal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api.removals(inventory.id).then(setRemovals).catch(() => setError("Historique indisponible."));
  }
  useEffect(load, [inventory.id]);

  async function restore(removal: Removal) {
    setError(null);
    try {
      await api.restore(removal.id);
      onRestored();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Restauration impossible.");
    }
  }

  return (
    <Modal title="Historique des retraits (1 mois)" onClose={onClose}>
      <ErrorMessage message={error} />
      {removals === null ? (
        <Loading />
      ) : removals.length === 0 ? (
        <p className="text-stone-500">Aucun retrait ce mois-ci.</p>
      ) : (
        <ul className="divide-y divide-stone-200 dark:divide-stone-800">
          {removals.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 py-2.5">
              <div className={r.undone_at ? "opacity-50" : ""}>
                <p className="font-medium">
                  {r.name} <span className="font-normal text-stone-500">· {formatQuantity(r.quantity, r.unit)}</span>
                </p>
                <p className="text-xs text-stone-500">
                  {REASON_LABELS[r.reason]} le {new Date(r.removed_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
                  {r.removed_by && ` par ${r.removed_by}`}
                  {r.undone_at && " · remis"}
                </p>
              </div>
              {!r.undone_at && (
                <button type="button" className="shrink-0 text-sm font-medium text-brand-700 hover:underline dark:text-brand-500" onClick={() => restore(r)}>
                  Remettre
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
