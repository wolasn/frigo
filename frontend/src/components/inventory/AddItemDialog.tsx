import { useState } from "react";
import { api, type Food, type Inventory, type ItemCreate } from "../../api";
import { isoToday, unitLabel } from "../../format";
import { ErrorMessage, Field, inputClass, Modal, primaryButton } from "../ui";
import FoodPicker from "./FoodPicker";

type Kind = "ingredient" | "leftover";

export default function AddItemDialog({
  inventory,
  defaultLocationId,
  onAdded,
  onClose,
}: {
  inventory: Inventory;
  defaultLocationId?: string;
  onAdded: () => void;
  onClose: () => void;
}) {
  const fridge = inventory.locations.find((l) => l.storage_type === "fridge");
  const [kind, setKind] = useState<Kind>("ingredient");
  const [food, setFood] = useState<Food | null>(null);
  const [leftoverName, setLeftoverName] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [unit, setUnit] = useState("");
  const [locationId, setLocationId] = useState(defaultLocationId ?? fridge?.id ?? inventory.locations[0]?.id ?? "");
  const [expiresOn, setExpiresOn] = useState("");
  const [dateType, setDateType] = useState<"use_by" | "best_before">("use_by");
  const [opened, setOpened] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [addedCount, setAddedCount] = useState(0);

  const units = kind === "leftover" ? ["portion"] : (food?.units ?? []);
  const currentUnit = units.includes(unit) ? unit : units[0];

  function pickFood(next: Food | null) {
    setFood(next);
    setUnit(next?.units[0] ?? "");
  }

  async function submit(event: { preventDefault(): void }, addAnother: boolean) {
    event.preventDefault();
    setError(null);
    const amount = Number(quantity.replace(",", "."));
    if (!(amount > 0)) return setError("Indique une quantité supérieure à zéro.");

    const body: ItemCreate = {
      kind,
      quantity: amount,
      storage_location_id: locationId,
      ...(kind === "ingredient" ? { food_id: food?.id, unit: currentUnit } : { leftover_name: leftoverName.trim() }),
      ...(expiresOn ? { expires_on: expiresOn, date_type: kind === "leftover" ? "use_by" : dateType } : {}),
      ...(opened ? { opened_on: isoToday() } : {}),
    };
    setBusy(true);
    try {
      await api.addItem(inventory.id, body);
      onAdded();
      if (addAnother) {
        setFood(null);
        setLeftoverName("");
        setQuantity("1");
        setExpiresOn("");
        setOpened(false);
        setAddedCount((n) => n + 1);
      } else {
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ajout impossible.");
    } finally {
      setBusy(false);
    }
  }

  const ready = kind === "ingredient" ? food !== null : leftoverName.trim() !== "";

  return (
    <Modal title="Ajouter à l'inventaire" onClose={onClose}>
      <form onSubmit={(e) => submit(e, false)} className="space-y-4">
        <div className="grid grid-cols-2 rounded-lg bg-stone-200 p-1 text-sm dark:bg-stone-800">
          {(["ingredient", "leftover"] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKind(k)}
              className={"rounded-md py-1.5 font-medium " + (kind === k ? "bg-white shadow-sm dark:bg-stone-900" : "text-stone-600 dark:text-stone-400")}
            >
              {k === "ingredient" ? "Ingrédient" : "Reste / plat préparé"}
            </button>
          ))}
        </div>

        {kind === "ingredient" ? (
          <Field label="Aliment">
            <FoodPicker value={food} onChange={pickFood} />
          </Field>
        ) : (
          <Field label="Nom du plat">
            <input className={inputClass} value={leftoverName} onChange={(e) => setLeftoverName(e.target.value)} placeholder="Reste de lasagnes" maxLength={80} />
          </Field>
        )}

        <div className="grid grid-cols-2 gap-3">
          <Field label={kind === "leftover" ? "Nombre de parts" : "Quantité"} hint={kind === "leftover" ? "1 part = 1 repas pour 1 personne" : undefined}>
            <input className={inputClass} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </Field>
          {kind === "ingredient" && (
            <Field label="Unité">
              <select className={inputClass} value={currentUnit ?? ""} onChange={(e) => setUnit(e.target.value)} disabled={!food}>
                {units.map((u) => (
                  <option key={u} value={u}>
                    {unitLabel(u)}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>

        <Field label="Rangé dans">
          <select className={inputClass} value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            {inventory.locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Date limite" hint={expiresOn ? undefined : "Vide = estimée automatiquement"}>
            <input type="date" className={inputClass} value={expiresOn} onChange={(e) => setExpiresOn(e.target.value)} />
          </Field>
          {kind === "ingredient" && expiresOn && (
            <Field label="Type de date">
              <select className={inputClass} value={dateType} onChange={(e) => setDateType(e.target.value as "use_by" | "best_before")}>
                <option value="use_by">À consommer jusqu'au (DLC)</option>
                <option value="best_before">De préférence avant (DDM)</option>
              </select>
            </Field>
          )}
        </div>

        {kind === "ingredient" && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={opened} onChange={(e) => setOpened(e.target.checked)} className="size-4 accent-brand-600" />
            Déjà ouvert
          </label>
        )}

        <ErrorMessage message={error} />
        {addedCount > 0 && <p className="text-sm text-brand-700 dark:text-brand-500">{addedCount} article(s) ajouté(s).</p>}

        <div className="flex flex-wrap gap-2">
          <button type="submit" className={primaryButton} disabled={!ready || busy}>
            Ajouter
          </button>
          <button
            type="button"
            className="rounded-lg px-4 py-2 font-medium text-brand-700 hover:bg-brand-50 disabled:opacity-60 dark:text-brand-500 dark:hover:bg-stone-800"
            disabled={!ready || busy}
            onClick={(e) => submit(e, true)}
          >
            Ajouter et continuer
          </button>
        </div>
      </form>
    </Modal>
  );
}
