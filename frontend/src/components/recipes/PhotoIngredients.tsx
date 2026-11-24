import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { canUseLiveCamera, photoFromFile, photoFromVideo, type CapturedPhoto } from "../../photo";
import { ErrorMessage, Loading, Modal, primaryButton, secondaryButton } from "../ui";

const MAX_PHOTOS = 6;

/** Photo → ingrédients reconnus, à cocher dans la recherche. Les photos ne sont jamais conservées. */
export default function PhotoIngredients({ onFound, onClose }: { onFound: (names: string[]) => void; onClose: () => void }) {
  const [photos, setPhotos] = useState<CapturedPhoto[]>([]);
  const [camera, setCamera] = useState(false);
  const [busy, setBusy] = useState(false);
  const [found, setFound] = useState<{ name: string; checked: boolean }[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const captureInput = useRef<HTMLInputElement>(null);

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
    setBusy(true);
    try {
      const result = await api.photoIngredients(photos.map((p) => ({ media_type: p.mediaType, data: p.data })));
      setPhotos([]); // les images sont oubliées dès la fin de l'analyse
      setFound(result.ingredients.map((i) => ({ name: i.name, checked: i.sure })));
      setNote(result.fallback ? "Le modèle local n'a pas répondu : analyse faite par l'API Claude." : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "L'analyse a échoué.");
    } finally {
      setBusy(false);
    }
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
    <Modal title={found ? "Ingrédients reconnus" : "Ingrédients en photo"} onClose={onClose}>
      {busy ? (
        <Loading label="Analyse des photos… (jusqu'à une minute)" />
      ) : found ? (
        <div className="space-y-4">
          {found.length === 0 ? (
            <p className="text-sm text-stone-600 dark:text-stone-400">Aucun ingrédient reconnu. Essaie une autre photo, plus proche.</p>
          ) : (
            <ul className="grid gap-1 sm:grid-cols-2">
              {found.map((item, index) => (
                <li key={item.name}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="size-4 accent-brand-600"
                      checked={item.checked}
                      onChange={(e) => setFound((list) => list!.map((x, i) => (i === index ? { ...x, checked: e.target.checked } : x)))}
                    />
                    {item.name}
                  </label>
                </li>
              ))}
            </ul>
          )}
          {note && <p className="text-xs text-stone-500">{note}</p>}
          <div className="flex gap-2">
            <button
              className={primaryButton}
              disabled={!found.some((f) => f.checked)}
              onClick={() => {
                onFound(found.filter((f) => f.checked).map((f) => f.name));
                onClose();
              }}
            >
              Cocher ces ingrédients
            </button>
            <button className={secondaryButton} onClick={() => setFound(null)}>
              Autres photos
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Photographie ce que tu as sous la main (frigo, placard, courses ; jusqu'à {MAX_PHOTOS} photos) : les ingrédients reconnus
            seront cochés pour chercher des recettes. Les photos ne sont jamais conservées.
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
          <ErrorMessage message={error} />
          <div className="flex gap-2">
            <button className={primaryButton} onClick={analyze} disabled={photos.length === 0}>
              Analyser {photos.length > 0 ? `${photos.length} photo(s)` : ""}
            </button>
            <button className={secondaryButton} onClick={onClose}>
              Annuler
            </button>
          </div>
        </div>
      )}
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
