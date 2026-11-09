import { useState } from "react";
import { api, type User } from "../api";
import InventoryPage from "./InventoryPage";

const SECTIONS = [
  { id: "inventory", label: "Inventaire", ready: true },
  { id: "meals", label: "Repas", ready: false },
  { id: "agenda", label: "Agenda", ready: false },
  { id: "shopping", label: "Courses", ready: false },
] as const;

export default function HomePage({ user, onLoggedOut }: { user: User; onLoggedOut: () => void }) {
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    try {
      await api.logout();
    } finally {
      onLoggedOut();
    }
  }

  return (
    <div className="min-h-dvh">
      <header className="border-b border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-5">
            <span className="shrink-0 font-semibold">Frigo &amp; Repas</span>
            <nav className="flex gap-1 overflow-x-auto text-sm">
              {SECTIONS.map((s) => (
                <span
                  key={s.id}
                  title={s.ready ? undefined : "Bientôt disponible"}
                  className={
                    "shrink-0 rounded-md px-2.5 py-1 " +
                    (s.ready ? "bg-stone-100 font-medium dark:bg-stone-800" : "text-stone-400 dark:text-stone-600")
                  }
                >
                  {s.label}
                </span>
              ))}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-3 text-sm">
            <span className="hidden text-stone-600 sm:inline dark:text-stone-400">
              {user.display_name}
              {user.role === "super_admin" && (
                <span className="ml-2 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">super-admin</span>
              )}
            </span>
            <button
              onClick={logout}
              disabled={busy}
              className="rounded-lg border border-stone-300 px-3 py-1.5 hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800"
            >
              Déconnexion
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-6">
        <InventoryPage />
      </main>
    </div>
  );
}
