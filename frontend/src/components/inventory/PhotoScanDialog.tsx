import { useEffect, useRef, useState } from "react";
import { api, type DateType, type Food, type Inventory, type PhotoScan, type ScanLine } from "../../api";
import { canUseLiveCamera, photoFromFile, photoFromVideo, type CapturedPhoto } from "../../photo";
import { ErrorMessage, inputClass, Loading, Modal, primaryButton, secondaryButton } from "../ui";
import FoodPicker from "./FoodPicker";

const MAX_PHOTOS = 6;

type Edit = {
  include: boolean;
  food: Food | null;
  quantity: string;
  unit: string;
  locationId: string;
  expiresOn: string;
  dateType: DateType;
  merge: boolean;
};

function initialEdit(line: ScanLine, fallbackLocation: string): Edit {
  const units = line.food?.units ?? [];
  return {
    include: true,
    food: line.food,
    quantity: line.quantity !== null ? String(line.quantity).replace(".", ",") : "",
    unit: line.unit && (units.length === 0 || units.includes(line.unit)) ? line.unit : units[0] ?? line.unit ?? "",
    locationId: line.storage_location_id ?? fallbackLocation,
    expiresOn: line.expires_on ?? "",
    dateType: line.date_type && line.date_type !== "estimated" ? line.date_type : "use_by",
    merge: line.merge_with !== null,
  };
}

/** Inventaire par photo : prendre ou importer des photos, vérifier la liste détectée, valider. */
export default function PhotoScanDialog({
  inventories,
  inventoryId,
  onDone,
  onManual,
  onClose,
}: {
  inventories: Inventory[];
  inventoryId: string;
  onDone: (message: string) => void;
  onManual: () => void;
  onClose: () => void;
}) {
  const [photos, setPhotos] = useState<CapturedPhoto[]>([]);
  const [target, setTarget] = useState(inventoryId);
  const [camera, setCamera] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [scan, setScan] = useState<PhotoScan | null>(null);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const captureInput = useRef<HTMLInputElement>(null);
  const inventory = inventories.find((i) => i.id === target) ?? inventories[0];

  // Modèle local : on le charge sur le PC pendant que l'utilisateur prend ses photos.
  useEffect(() => {
    api.warmUpPhotoModel().catch(() => undefined);
  }, []);

  async function addFiles(files: FileList | null) {
    if (!files) return;
    setError(null);
    const room = MAX_PHOTOS - photos.length;
    try {
      const added = await Promise.all([...files].slice(0, room).map(photoFromFile));
      setPhotos((current) => [...current, ...added]);
      if (files.length > room) setError(`${MAX_PHOTOS} photos au plus par analyse.`);
    } catch {
      setError("Impossible de lire cette image.");
    }
  }

  function takePhotos() {
    if (canUseLiveCamera()) setCamera(true);
    else captureInput.current?.click(); // appareil photo du téléphone (adresse non sécurisée)
  }

  async function analyze() {
    setError(null);
    setFailed(false);
    setBusy("Analyse des photos… (jusqu'à une minute)");
    try {
      const result = await api.analyzePhotos(
        photos.map((p) => ({ media_type: p.mediaType, data: p.data })),
        target,
      );
      setPhotos([]); // les images sont oubliées dès la fin de l'analyse
      const fallback = inventory?.locations[0]?.id ?? "";
      setEdits(Object.fromEntries(result.lines.map((l) => [l.id, initialEdit(l, fallback)])));
      setScan(result);
    } catch (err) {
      setFailed(true);
      setError(err instanceof Error ? err.message : "L'analyse a échoué.");
    } finally {
      setBusy(null);
    }
  }

  async function chooseOption(line: ScanLine, option: string) {
    const found = await api.searchFoods(option).catch(() => [] as Food[]);
    const food = found.find((f) => f.name.toLowerCase() === option.toLowerCase()) ?? found[0] ?? null;
    update(line.id, { food, ...(food && !food.units.includes(edits[line.id].unit) ? { unit: food.units[0] } : {}) });
  }

  function update(id: string, change: Partial<Edit>) {
    setEdits((current) => ({ ...current, [id]: { ...current[id], ...change } }));
  }

  async function validate() {
    if (!scan) return;
    setError(null);
    setBusy("Ajout à l'inventaire…");
    try {
      const lines = scan.lines.map((line) => {
        const e = edits[line.id];
        if (!e.include) return { id: line.id, include: false };
        return {
          id: line.id,
          include: true,
          food_id: e.food?.id,
          quantity: e.quantity ? Number(e.quantity.replace(",", ".")) : undefined,
          unit: e.unit || undefined,
          storage_location_id: e.locationId || undefined,
          expires_on: e.expiresOn || undefined,
          date_type: e.expiresOn ? e.dateType : undefined,
          merge: line.merge_with !== null && e.merge,
        };
      });
      const { added, merged } = await api.validateScan(scan.id, lines);
      onDone(`${added} article(s) ajouté(s)${merged ? `, ${merged} fusionné(s) avec un article existant` : ""}.`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation impossible.");
    } finally {
      setBusy(null);
    }
  }

  function close() {
    if (scan && scan.status === "review") api.cancelScan(scan.id).catch(() => undefined);
    onClose();
  }

  if (camera) {
    return (
      <LiveCamera
        count={photos.length}
        onShot={(photo) => setPhotos((current) => (current.length < MAX_PHOTOS ? [...current, photo] : current))}
        onError={(message) => {
          setCamera(false);
          setError(message);
        }}
        onDone={() => setCamera(false)}
      />
    );
  }

  return (
    <Modal title={scan ? "Vérifie ce qui a été reconnu" : "Ajouter par photo"} onClose={close}>
      {busy ? (
        <Loading label={busy} />
      ) : scan ? (
        <Review
          scan={scan}
          edits={edits}
          inventory={inventory}
          onChange={update}
          onOption={chooseOption}
          onValidate={validate}
          onCancel={close}
        />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Photographie ton frigo, un placard ou tes courses (jusqu'à {MAX_PHOTOS} photos). Tu pourras corriger la liste avant de
            l'ajouter. Les photos ne sont jamais conservées : elles sont oubliées dès la fin de l'analyse.
          </p>
          <div className="flex flex-wrap gap-2">
            <button className={primaryButton} onClick={takePhotos} disabled={photos.length >= MAX_PHOTOS}>
              📷 Prendre des photos
            </button>
            <button className={secondaryButton} onClick={() => fileInput.current?.click()} disabled={photos.length >= MAX_PHOTOS}>
              🖼️ Importer des photos
            </button>
          </div>
          <input ref={fileInput} type="file" accept="image/*" multiple hidden onChange={(e) => addFiles(e.target.files).then(() => (e.target.value = ""))} />
          <input ref={captureInput} type="file" accept="image/*" capture="environment" hidden onChange={(e) => addFiles(e.target.files).then(() => (e.target.value = ""))} />

          {photos.length > 0 && (
            <div className="grid grid-cols-3 gap-2">
              {photos.map((p) => (
                <div key={p.id} className="relative">
                  <img src={p.preview} alt="" className="aspect-square w-full rounded-lg object-cover" />
                  <button
                    className="absolute right-1 top-1 rounded-full bg-black/60 px-2 text-sm text-white"
                    onClick={() => setPhotos((current) => current.filter((x) => x.id !== p.id))}
                    aria-label="Retirer cette photo"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          {inventories.length > 1 && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Ajouter dans</span>
              <select className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)}>
                {inventories.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <ErrorMessage message={error} />
          {failed && (
            <button className={secondaryButton} onClick={onManual}>
              Saisir à la main
            </button>
          )}
          <div className="flex gap-2">
            <button className={primaryButton} onClick={analyze} disabled={photos.length === 0}>
              Analyser {photos.length > 0 ? `${photos.length} photo(s)` : ""}
            </button>
            <button className={secondaryButton} onClick={close}>
              Annuler
            </button>
          </div>
        </div>
      )}
      {scan && <ErrorMessage message={error} />}
    </Modal>
  );
}

/** Caméra dans la page : les images restent en mémoire, rien n'est enregistré dans la galerie. */
function LiveCamera({
  count,
  onShot,
  onError,
  onDone,
}: {
  count: number;
  onShot: (photo: CapturedPhoto) => void;
  onError: (message: string) => void;
  onDone: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [flash, setFlash] = useState(false);
  const errorHandler = useRef(onError);
  errorHandler.current = onError;

  useEffect(() => {
    let stream: MediaStream | null = null;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } }, audio: false })
      .then((s) => {
        stream = s;
        if (video.current) video.current.srcObject = s;
      })
      .catch(() => errorHandler.current("Impossible d'ouvrir la caméra (autorisation refusée ?). Tu peux importer des photos."));
    return () => stream?.getTracks().forEach((t) => t.stop()); // la caméra s'éteint en quittant
  }, []); // une seule ouverture : les photos prises ne relancent pas la caméra

  function shoot() {
    if (!video.current || !video.current.videoWidth) return;
    onShot(photoFromVideo(video.current));
    setFlash(true);
    setTimeout(() => setFlash(false), 150);
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black">
      <video ref={video} autoPlay playsInline muted className={"min-h-0 flex-1 object-contain" + (flash ? " opacity-40" : "")} />
      <div className="flex items-center justify-between gap-4 p-4">
        <span className="text-sm text-white">
          {count}/{MAX_PHOTOS} photo(s)
        </span>
        <button
          className="size-16 rounded-full border-4 border-white bg-white/30 disabled:opacity-40"
          onClick={shoot}
          disabled={count >= MAX_PHOTOS}
          aria-label="Prendre la photo"
        />
        <button className="rounded-lg bg-white px-4 py-2 font-medium text-stone-900" onClick={onDone}>
          Terminé
        </button>
      </div>
    </div>
  );
}

function Review({
  scan,
  edits,
  inventory,
  onChange,
  onOption,
  onValidate,
  onCancel,
}: {
  scan: PhotoScan;
  edits: Record<string, Edit>;
  inventory: Inventory | undefined;
  onChange: (id: string, change: Partial<Edit>) => void;
  onOption: (line: ScanLine, option: string) => void;
  onValidate: () => void;
  onCancel: () => void;
}) {
  if (scan.lines.length === 0) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-stone-600 dark:text-stone-400">Aucun aliment reconnu sur ces photos.</p>
        <button className={secondaryButton} onClick={onCancel}>
          Fermer
        </button>
      </div>
    );
  }
  const kept = scan.lines.filter((l) => edits[l.id]?.include).length;
  return (
    <div className="space-y-3">
      <p className="text-sm text-stone-600 dark:text-stone-400">
        Corrige si besoin, décoche ce qui ne doit pas être ajouté. Les lignes surlignées sont incertaines.
      </p>
      <ul className="space-y-2">
        {scan.lines.map((line) => {
          const e = edits[line.id];
          const units = e.food?.units ?? (e.unit ? [e.unit] : []);
          return (
            <li
              key={line.id}
              className={
                "rounded-lg border p-3 text-sm " +
                (!e.include
                  ? "border-stone-200 opacity-50 dark:border-stone-800"
                  : line.doubtful && !e.food
                    ? "border-amber-400 bg-amber-50 dark:border-amber-700 dark:bg-amber-950"
                    : line.doubtful
                      ? "border-amber-300 dark:border-amber-800"
                      : "border-stone-200 dark:border-stone-800")
              }
            >
              <label className="mb-2 flex items-center gap-2 font-medium">
                <input type="checkbox" checked={e.include} onChange={(ev) => onChange(line.id, { include: ev.target.checked })} className="size-4 accent-brand-600" />
                Vu : « {line.label} »
                {line.doubtful && <span className="text-xs font-normal text-amber-700 dark:text-amber-400">à vérifier</span>}
              </label>
              {e.include && (
                <div className="space-y-2">
                  {line.question && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-amber-800 dark:text-amber-300">{line.question}</span>
                      {line.options.map((option) => (
                        <button
                          key={option}
                          className={
                            "rounded-full border px-2.5 py-0.5 text-xs " +
                            (e.food?.name.toLowerCase() === option.toLowerCase()
                              ? "border-brand-600 bg-brand-600 text-white"
                              : "border-stone-300 hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800")
                          }
                          onClick={() => onOption(line, option)}
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  )}
                  <FoodPicker
                    value={e.food}
                    onChange={(food) => onChange(line.id, { food, ...(food && !food.units.includes(e.unit) ? { unit: food.units[0] } : {}) })}
                  />
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <input className={inputClass} inputMode="decimal" placeholder="Quantité" value={e.quantity} onChange={(ev) => onChange(line.id, { quantity: ev.target.value })} aria-label="Quantité" />
                    <select className={inputClass} value={e.unit} onChange={(ev) => onChange(line.id, { unit: ev.target.value })} aria-label="Unité">
                      {units.map((u) => (
                        <option key={u} value={u}>
                          {u === "piece" ? "pièce(s)" : u}
                        </option>
                      ))}
                    </select>
                    {line.merge_with && e.merge ? (
                      <p className="col-span-2 self-center text-xs text-stone-500">Ajouté à l'article existant (expire le {line.merge_with.expires_on.split("-").reverse().join("/")}).</p>
                    ) : (
                      <>
                        <select className={inputClass} value={e.locationId} onChange={(ev) => onChange(line.id, { locationId: ev.target.value })} aria-label="Rangé dans">
                          {inventory?.locations.map((l) => (
                            <option key={l.id} value={l.id}>
                              {l.name}
                            </option>
                          ))}
                        </select>
                        <input type="date" className={inputClass} value={e.expiresOn} onChange={(ev) => onChange(line.id, { expiresOn: ev.target.value })} aria-label="Date limite (vide = estimée)" title="Vide = date estimée" />
                      </>
                    )}
                  </div>
                  {e.expiresOn && !(line.merge_with && e.merge) && (
                    <select className={inputClass + " w-auto py-1 text-xs"} value={e.dateType} onChange={(ev) => onChange(line.id, { dateType: ev.target.value as DateType })} aria-label="Type de date">
                      <option value="use_by">DLC (à consommer jusqu'au)</option>
                      <option value="best_before">DDM (de préférence avant)</option>
                    </select>
                  )}
                  {line.merge_with && (
                    <div className="flex gap-3 text-xs">
                      <label className="flex items-center gap-1">
                        <input type="radio" checked={e.merge} onChange={() => onChange(line.id, { merge: true })} /> Fusionner avec l'existant
                      </label>
                      <label className="flex items-center gap-1">
                        <input type="radio" checked={!e.merge} onChange={() => onChange(line.id, { merge: false })} /> Nouveau lot
                      </label>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button className={primaryButton} onClick={onValidate} disabled={kept === 0}>
          Ajouter {kept} article(s)
        </button>
        <button className={secondaryButton} onClick={onCancel}>
          Annuler
        </button>
      </div>
      <p className="text-xs text-stone-500">
        Analyse : {scan.engine === "claude" ? "API Claude" : "modèle local"}
        {scan.fallback && " (le modèle local n'a pas répondu)"}.
      </p>
    </div>
  );
}
