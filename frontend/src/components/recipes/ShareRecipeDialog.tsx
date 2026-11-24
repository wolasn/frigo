import { useEffect, useState, type FormEvent } from "react";
import { api, type Agenda, type RecipeShareOut } from "../../api";
import { ErrorMessage, inputClass, Modal, primaryButton, secondaryButton } from "../ui";

export default function ShareRecipeDialog({ recipeId, title, onClose }: { recipeId: string; title: string; onClose: () => void }) {
  const [shares, setShares] = useState<RecipeShareOut[] | null>(null);
  const [agendas, setAgendas] = useState<Agenda[]>([]);
  const [username, setUsername] = useState("");
  const [agendaId, setAgendaId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.recipeShares(recipeId).then(setShares).catch(() => setShares([]));
    api.agendas().then(setAgendas).catch(() => setAgendas([]));
  }, [recipeId]);

  async function run(action: () => Promise<RecipeShareOut[]>) {
    setError(null);
    try {
      setShares(await action());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Partage impossible.");
    }
  }

  function shareWithUser(event: FormEvent) {
    event.preventDefault();
    run(() => api.shareRecipe(recipeId, { username: username.trim() })).then(() => setUsername(""));
  }

  return (
    <Modal title={`Partager « ${title} »`} onClose={onClose}>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">
        Les personnes choisies voient la recette en lecture seule et peuvent en faire une copie. Leurs notes et favoris restent personnels.
      </p>
      <form onSubmit={shareWithUser} className="mb-3 flex gap-2">
        <input className={inputClass} placeholder="Identifiant d'une personne" value={username} onChange={(e) => setUsername(e.target.value)} autoCapitalize="none" />
        <button className={primaryButton} disabled={!username.trim()}>
          Partager
        </button>
      </form>
      {agendas.length > 0 && (
        <div className="mb-4 flex gap-2">
          <select className={inputClass} value={agendaId} onChange={(e) => setAgendaId(e.target.value)}>
            <option value="">Ou tous les membres d'un agenda partagé…</option>
            {agendas.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <button className={secondaryButton} disabled={!agendaId} onClick={() => run(() => api.shareRecipe(recipeId, { agenda_id: agendaId })).then(() => setAgendaId(""))}>
            Partager
          </button>
        </div>
      )}
      <ErrorMessage message={error} />
      <h3 className="mb-2 mt-2 text-sm font-semibold">Partagée avec</h3>
      {shares === null ? (
        <p className="text-sm text-stone-500">Chargement…</p>
      ) : shares.length === 0 ? (
        <p className="text-sm text-stone-500">Personne pour l'instant.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {shares.map((s) => (
            <li key={s.id} className="flex items-center justify-between">
              {s.label}
              <button className="text-stone-500 hover:text-red-600" onClick={() => run(() => api.unshareRecipe(recipeId, s.id))}>
                Retirer
              </button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
