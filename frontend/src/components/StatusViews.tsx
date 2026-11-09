import { useEffect, useState, type FormEvent } from "react";
import { api, statusWithKey, type DbStatus } from "../api";
import { ErrorMessage, inputClass, secondaryButton } from "./ui";

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

function StatusDetails({ status }: { status: DbStatus }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      <dt className="text-stone-500">État</dt>
      <dd>{status.status === "ok" ? "Disponible" : status.status === "down" ? "Indisponible" : "Inconnu"}</dd>
      {status.live && (
        <>
          <dt className="text-stone-500">Vérification immédiate</dt>
          <dd>{status.live === "ok" ? "La base répond" : status.live}</dd>
        </>
      )}
      {status.cause && (
        <>
          <dt className="text-stone-500">Cause</dt>
          <dd>{status.cause}</dd>
        </>
      )}
      <dt className="text-stone-500">Depuis</dt>
      <dd>{when(status.since)}</dd>
      <dt className="text-stone-500">Dernière vérification</dt>
      <dd>{when(status.last_check)}</dd>
      {status.email_error && (
        <>
          <dt className="text-stone-500">E-mail d'alerte</dt>
          <dd className="text-red-700 dark:text-red-400">{status.email_error}</dd>
        </>
      )}
    </dl>
  );
}

/** Écran affiché quand l'application ne peut pas joindre la base. */
export function UnavailableScreen() {
  const [key, setKey] = useState("");
  const [status, setStatus] = useState<DbStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdmin, setShowAdmin] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setStatus(await statusWithKey(key));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Accès refusé.");
    }
  }

  return (
    <main className="mx-auto max-w-md px-4 py-16">
      <h1 className="mb-2 text-2xl font-semibold">Service momentanément indisponible</h1>
      <p className="mb-6 text-stone-600 dark:text-stone-400">Réessaie dans quelques instants. Si le problème dure, contacte l'administrateur.</p>
      <button className="text-sm text-stone-500 hover:underline" onClick={() => setShowAdmin(!showAdmin)}>
        Accès administrateur
      </button>
      {showAdmin && (
        <div className="mt-3 space-y-3">
          <form onSubmit={submit} className="flex gap-2">
            <input type="password" className={inputClass} placeholder="Clé de la page de statut" value={key} onChange={(e) => setKey(e.target.value)} />
            <button className={secondaryButton} disabled={!key}>
              Voir
            </button>
          </form>
          <ErrorMessage message={error} />
          {status && <StatusDetails status={status} />}
        </div>
      )}
    </main>
  );
}

/** Bandeau du super-administrateur : panne en cours, incident récent ou alerte e-mail impossible. */
export function SuperAdminBanner() {
  const [status, setStatus] = useState<DbStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.dbStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  if (!status) return null;
  const recentIncident =
    status.last_incident_end && Date.now() - new Date(status.last_incident_end).getTime() < 7 * 24 * 3600 * 1000;
  const neverChecked = status.status === "unknown";
  if (status.status === "ok" && !recentIncident && !status.email_error && !neverChecked) return null;

  const message =
    status.status === "down"
      ? `Base signalée indisponible depuis le ${when(status.since)}.`
      : neverChecked
        ? "La vérification automatique de la base n'a pas encore tourné (tous les jours à 6 h)."
        : recentIncident
          ? `Incident récent : base indisponible du ${when(status.last_incident_start)} au ${when(status.last_incident_end)}.`
          : `Les alertes e-mail ne partent pas : ${status.email_error}`;

  async function checkNow() {
    setBusy(true);
    try {
      setStatus(await api.checkDbNow());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-5 rounded-xl bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <strong>Super-admin :</strong> {message}
        </span>
        <span className="flex gap-3">
          <button className="font-medium hover:underline" onClick={() => setOpen(!open)}>
            {open ? "Masquer" : "Détails"}
          </button>
          <button className="font-medium hover:underline" onClick={checkNow} disabled={busy}>
            {busy ? "Vérification…" : "Vérifier maintenant"}
          </button>
        </span>
      </div>
      {open && (
        <div className="mt-3">
          <StatusDetails status={status} />
        </div>
      )}
    </div>
  );
}
