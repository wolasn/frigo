import { useState } from "react";
import { api, type User } from "../api";
import AgendaPage from "./AgendaPage";
import InventoryPage from "./InventoryPage";
import MealsPage from "./MealsPage";
import ShoppingPage from "./ShoppingPage";
import UtensilsPage from "./UtensilsPage";

type SectionId = "inventory" | "meals" | "utensils" | "agenda" | "shopping";

const SECTIONS: { id: SectionId; label: string; ready: boolean }[] = [
  { id: "inventory", label: "Inventaire", ready: true },
  { id: "meals", label: "Repas", ready: true },
  { id: "agenda", label: "Agenda", ready: true },
  { id: "shopping", label: "Courses", ready: true },
  { id: "utensils", label: "Ustensiles", ready: true },
];

function initialSection(): SectionId {
  const hash = window.location.hash.slice(1) as SectionId;
  return SECTIONS.some((s) => s.id === hash && s.ready) ? hash : "inventory";
}

export default function HomePage({ user, onLoggedOut }: { user: User; onLoggedOut: () => void }) {
  const [section, setSection] = useState<SectionId>(initialSection);
  const [busy, setBusy] = useState(false);

  function go(id: SectionId) {
    setSection(id);
    window.history.replaceState(null, "", `#${id}`);
  }

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
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-5">
            <span className="hidden shrink-0 font-semibold sm:inline">Frigo &amp; Repas</span>
            <nav className="flex gap-1 overflow-x-auto text-sm">
              {SECTIONS.map((s) => (
                <button
                  key={s.id}
                  disabled={!s.ready}
                  onClick={() => go(s.id)}
                  title={s.ready ? undefined : "Bientôt disponible"}
                  aria-current={section === s.id ? "page" : undefined}
                  className={
                    "shrink-0 rounded-md px-2.5 py-1 " +
                    (section === s.id
                      ? "bg-stone-100 font-medium dark:bg-stone-800"
                      : s.ready
                        ? "text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800"
                        : "text-stone-400 dark:text-stone-600")
                  }
                >
                  {s.label}
                </button>
              ))}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-3 text-sm">
            <span className="hidden text-stone-600 md:inline dark:text-stone-400">
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

      <main className="mx-auto max-w-5xl px-4 py-6">
        {section === "inventory" && <InventoryPage />}
        {section === "meals" && <MealsPage />}
        {section === "utensils" && <UtensilsPage />}
        {section === "agenda" && <AgendaPage />}
        {section === "shopping" && <ShoppingPage />}
      </main>
    </div>
  );
}
