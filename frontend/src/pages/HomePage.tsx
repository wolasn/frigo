import { useCallback, useEffect, useRef, useState } from "react";
import { api, type User } from "../api";
import { SuperAdminBanner } from "../components/StatusViews";
import AgendaPage from "./AgendaPage";
import MealsPage from "./MealsPage";
import PreferencesPage from "./PreferencesPage";
import SharingPage from "./SharingPage";
import ShoppingPage from "./ShoppingPage";
import UtensilsPage from "./UtensilsPage";

type SectionId = "meals" | "agenda" | "shopping" | "utensils" | "sharing" | "preferences";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "meals", label: "Repas" },
  { id: "agenda", label: "Agenda" },
  { id: "shopping", label: "Courses" },
  { id: "utensils", label: "Ustensiles" },
  { id: "sharing", label: "Partages" },
  { id: "preferences", label: "Préférences" },
];

function initialSection(): SectionId {
  const hash = window.location.hash.slice(1) as SectionId;
  return SECTIONS.some((s) => s.id === hash) ? hash : "meals";
}

export default function HomePage({
  user,
  onLoggedOut,
  onUserChanged,
}: {
  user: User;
  onLoggedOut: () => void;
  onUserChanged: (user: User) => void;
}) {
  const [section, setSection] = useState<SectionId>(initialSection);
  const [busy, setBusy] = useState(false);
  const [badge, setBadge] = useState(0);

  const badgeRequest = useRef(0);
  const refreshBadge = useCallback(() => {
    // Seule la réponse la plus récente compte : une réponse plus ancienne arrivée en retard est ignorée.
    const request = ++badgeRequest.current;
    api
      .notifications()
      .then((n) => request === badgeRequest.current && setBadge(n.unread + n.pending_invitations))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshBadge();
    const timer = setInterval(refreshBadge, 60_000);
    return () => clearInterval(timer);
  }, [refreshBadge]);

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
                  onClick={() => go(s.id)}
                  aria-current={section === s.id ? "page" : undefined}
                  className={
                    "relative shrink-0 rounded-md px-2.5 py-1 " +
                    (section === s.id
                      ? "bg-stone-100 font-medium dark:bg-stone-800"
                      : "text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800")
                  }
                >
                  {s.label}
                  {s.id === "sharing" && badge > 0 && (
                    <span className="ml-1 rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white" aria-label={`${badge} nouveauté(s)`}>
                      {badge}
                    </span>
                  )}
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
        {user.role === "super_admin" && <SuperAdminBanner />}
        {section === "meals" && <MealsPage />}
        {section === "agenda" && <AgendaPage />}
        {section === "shopping" && <ShoppingPage />}
        {section === "utensils" && <UtensilsPage />}
        {section === "sharing" && <SharingPage onChanged={refreshBadge} />}
        {section === "preferences" && <PreferencesPage user={user} onUserChanged={onUserChanged} onAccountDeleted={onLoggedOut} />}
      </main>
    </div>
  );
}
