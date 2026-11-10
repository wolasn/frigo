import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Inventory, type InventoryDetail, type MyInvitation, type NotificationSummary, type Role } from "../api";
import { ErrorMessage, inputClass, primaryButton, secondaryButton } from "../components/ui";

const ROLE_LABELS: Record<Role, string> = { admin: "Administrateur", contributor: "Contributeur", member: "Membre" };
const ROLE_HELP: Record<Role, string> = {
  admin: "tout, y compris gérer les membres et supprimer le partage",
  contributor: "en plus : planifier et modifier les repas de l'agenda partagé",
  member: "voir, ajouter et retirer des aliments, cocher les repas cuisinés et les achats",
};

export default function SharingPage({ onChanged }: { onChanged: () => void }) {
  const [inventories, setInventories] = useState<Inventory[] | null>(null);
  const [invitations, setInvitations] = useState<MyInvitation[]>([]);
  const [notifications, setNotifications] = useState<NotificationSummary | null>(null);
  const [newName, setNewName] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.inventories().then(setInventories).catch(() => setError("Impossible de charger tes inventaires."));
    api.myInvitations().then(setInvitations).catch(() => setInvitations([]));
    api.notifications().then(setNotifications).catch(() => setNotifications(null));
    onChanged();
  }, [onChanged]);

  useEffect(() => {
    load();
    // Ouvrir cette page vaut lecture des notifications.
    api.readNotifications().then(onChanged).catch(() => undefined);
  }, [load, onChanged]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action impossible.");
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const created = await api.createSharedInventory(newName.trim());
      setNewName("");
      setOpen(created.id);
    });
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="mb-1 text-2xl font-semibold">Partages</h1>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Un inventaire partagé (frigo de la coloc, de la famille…) a son propre agenda et sa propre liste de courses. Chaque membre choisit s'il est pris en compte dans ses propositions de repas.
        </p>
      </div>

      <ErrorMessage message={error} />

      {invitations.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">Invitations reçues</h2>
          <ul className="space-y-2">
            {invitations.map((inv) => (
              <li key={inv.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-500 bg-white p-4 dark:bg-stone-900">
                <span>
                  <strong>{inv.invited_by ?? "Quelqu'un"}</strong> t'invite à rejoindre <strong>« {inv.inventory_name} »</strong>
                </span>
                <span className="flex gap-2">
                  <button className={primaryButton} onClick={() => run(() => api.acceptInvitation(inv.id))}>
                    Rejoindre
                  </button>
                  <button className={secondaryButton} onClick={() => run(() => api.declineInvitation(inv.id))}>
                    Refuser
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">Mes inventaires</h2>
        {inventories === null ? (
          <p className="text-stone-500">Chargement…</p>
        ) : (
          <ul className="space-y-3">
            {inventories.map((inventory) => (
              <li key={inventory.id} className="rounded-xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
                <button className="flex w-full items-center justify-between gap-3 p-4 text-left" onClick={() => setOpen(open === inventory.id ? null : inventory.id)}>
                  <span>
                    <span className="font-medium">{inventory.name}</span>
                    <span className="ml-2 text-sm text-stone-500">
                      {inventory.kind === "personal" ? "personnel" : `partagé · ${ROLE_LABELS[inventory.role].toLowerCase()}`}
                    </span>
                  </span>
                  <span className="text-stone-400">{open === inventory.id ? "▴" : "▾"}</span>
                </button>
                {open === inventory.id && <InventoryPanel inventory={inventory} run={run} onClosed={() => setOpen(null)} />}
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={create} className="mt-4 flex max-w-lg gap-2">
          <input className={inputClass} placeholder="Nom du nouvel inventaire partagé (ex. Frigo de la coloc)" value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={60} />
          <button type="submit" className={primaryButton} disabled={!newName.trim()}>
            Créer
          </button>
        </form>
      </section>

      {notifications && notifications.items.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">Notifications récentes</h2>
          <ul className="space-y-1 text-sm">
            {notifications.items.map((n) => (
              <li key={n.id} className={n.read ? "text-stone-500" : "font-medium"}>
                {new Date(n.created_at).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })} · {n.message}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function InventoryPanel({
  inventory,
  run,
  onClosed,
}: {
  inventory: Inventory;
  run: (action: () => Promise<unknown>) => Promise<void>;
  onClosed: () => void;
}) {
  const [detail, setDetail] = useState<InventoryDetail | null>(null);
  const [username, setUsername] = useState("");
  const [name, setName] = useState(inventory.name);
  const shared = inventory.kind === "shared";
  const isAdmin = !shared || detail?.my_role === "admin";

  const reload = useCallback(() => {
    api.inventoryDetail(inventory.id).then(setDetail).catch(() => setDetail(null));
  }, [inventory.id]);
  useEffect(reload, [reload]);

  const act = (action: () => Promise<unknown>) => run(action).then(reload);
  const me = detail?.members.find((m) => m.is_me);

  return (
    <div className="space-y-5 border-t border-stone-200 p-4 dark:border-stone-800">
      {isAdmin && (
        <form
          className="flex max-w-md gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            act(() => api.renameInventory(inventory.id, name.trim()));
          }}
        >
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={60} aria-label="Nom de l'inventaire" />
          <button className={secondaryButton} disabled={!name.trim() || name.trim() === inventory.name}>
            Renommer
          </button>
        </form>
      )}

      {shared && detail && (
        <>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-brand-600"
              checked={detail.include_in_suggestions}
              onChange={(e) => act(() => api.setIncludeInSuggestions(inventory.id, e.target.checked))}
            />
            Prendre en compte cet inventaire dans mes propositions de repas
          </label>

          <div>
            <h3 className="mb-2 font-medium">Membres</h3>
            <ul className="divide-y divide-stone-200 dark:divide-stone-800">
              {detail.members.map((m) => (
                <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    {m.display_name} <span className="text-sm text-stone-500">@{m.username}{m.is_me && " (toi)"}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {isAdmin ? (
                      <select
                        className={inputClass + " w-auto py-1 text-sm"}
                        value={m.role}
                        onChange={(e) => act(() => api.changeRole(inventory.id, m.user_id, e.target.value as Role))}
                        title={ROLE_HELP[m.role]}
                      >
                        {(["admin", "contributor", "member"] as Role[]).map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-sm text-stone-600 dark:text-stone-400">{ROLE_LABELS[m.role]}</span>
                    )}
                    {isAdmin && !m.is_me && (
                      <button className="text-sm text-red-700 hover:underline dark:text-red-400" onClick={() => act(() => api.removeMember(inventory.id, m.user_id))}>
                        Retirer
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-stone-500">
              Membre : {ROLE_HELP.member}. Contributeur : {ROLE_HELP.contributor}. Administrateur : {ROLE_HELP.admin}.
            </p>
          </div>

          {isAdmin && (
            <div>
              <h3 className="mb-2 font-medium">Inviter quelqu'un</h3>
              <form
                className="flex max-w-md gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  act(() => api.invite(inventory.id, username.trim())).then(() => setUsername(""));
                }}
              >
                <input className={inputClass} placeholder="Son identifiant" value={username} onChange={(e) => setUsername(e.target.value)} autoCapitalize="none" />
                <button className={primaryButton} disabled={!username.trim()}>
                  Inviter
                </button>
              </form>
              {detail.invitations.length > 0 && (
                <ul className="mt-2 space-y-1 text-sm">
                  {detail.invitations.map((i) => (
                    <li key={i.id} className="flex items-center gap-3">
                      <span className="text-stone-600 dark:text-stone-400">
                        Invitation en attente : {i.display_name} (@{i.username})
                      </span>
                      <button className="text-stone-500 hover:underline" onClick={() => act(() => api.cancelInvitation(inventory.id, i.id))}>
                        Annuler
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}

      <p className="text-sm text-stone-500">
        Lieux de rangement : {inventory.locations.map((l) => l.name).join(", ")}. Ils se gèrent depuis la page Inventaire.
      </p>

      {shared && me && (
        <div className="flex flex-wrap gap-2 border-t border-stone-200 pt-4 dark:border-stone-800">
          <button
            className={secondaryButton}
            onClick={() => {
              if (window.confirm(`Quitter « ${inventory.name} » ?`)) run(() => api.removeMember(inventory.id, me.user_id)).then(onClosed);
            }}
          >
            Quitter ce partage
          </button>
          {isAdmin && (
            <button
              className="rounded-lg px-4 py-2 font-medium text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-stone-800"
              onClick={() => {
                if (window.confirm(`Supprimer « ${inventory.name} » pour tous ses membres ? Ses aliments, son agenda et sa liste de courses seront effacés. C'est définitif.`))
                  run(() => api.deleteInventory(inventory.id)).then(onClosed);
              }}
            >
              Supprimer le partage
            </button>
          )}
        </div>
      )}
    </div>
  );
}
