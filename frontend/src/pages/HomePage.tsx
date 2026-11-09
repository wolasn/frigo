import { useState } from "react";
import { api, type User } from "../api";

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
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <span className="font-semibold">Frigo &amp; Repas</span>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-stone-600 dark:text-stone-400">
              {user.display_name}
              {user.role === "super_admin" && (
                <span className="ml-2 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">
                  super-admin
                </span>
              )}
            </span>
            <button
              onClick={logout}
              disabled={busy}
              className="rounded-lg border border-stone-300 px-3 py-1.5 hover:bg-stone-100 dark:border-stone-700 dark:hover:bg-stone-800"
            >
              Se déconnecter
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="mb-2 text-2xl font-semibold">Bonjour {user.display_name}</h1>
        <p className="text-stone-600 dark:text-stone-400">
          Ton compte et ton inventaire personnel sont prêts. La gestion de l'inventaire arrive à la prochaine étape.
        </p>
      </main>
    </div>
  );
}
