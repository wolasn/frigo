import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, type AdminSettings, type Category, type Food, type Preferences, type User } from "../api";
import { ErrorMessage, Field, inputClass, primaryButton, secondaryButton, Loading } from "../components/ui";

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900">
      <h2 className="font-semibold">{title}</h2>
      {hint && <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">{hint}</p>}
      <div className={hint ? "" : "mt-3"}>{children}</div>
    </section>
  );
}

/** Recherche d'un aliment du catalogue (sans création). */
function FoodSearch({ placeholder, onPick }: { placeholder: string; onPick: (food: Food) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Food[]>([]);

  useEffect(() => {
    if (!query.trim()) return setResults([]);
    const timer = setTimeout(() => api.searchFoods(query).then(setResults).catch(() => setResults([])), 200);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <div className="relative max-w-sm">
      <input className={inputClass} placeholder={placeholder} value={query} onChange={(e) => setQuery(e.target.value)} />
      {results.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-stone-200 bg-white shadow-lg dark:border-stone-700 dark:bg-stone-900">
          {results.map((food) => (
            <li key={food.id}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left hover:bg-stone-100 dark:hover:bg-stone-800"
                onClick={() => {
                  onPick(food);
                  setQuery("");
                }}
              >
                {food.name} <span className="text-xs text-stone-500">{food.category_name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function PreferencesPage({ user, onUserChanged, onAccountDeleted }: {
  user: User;
  onUserChanged: (user: User) => void;
  onAccountDeleted: () => void;
}) {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [passwords, setPasswords] = useState({ current: "", next: "", confirm: "" });
  const [newThreshold, setNewThreshold] = useState({ categoryId: "", days: "1" });
  const [deletePassword, setDeletePassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.preferences().then(setPrefs).catch(() => setError("Impossible de charger tes préférences."));
    api.categories().then(setCategories).catch(() => setCategories([]));
  }, []);

  async function save(action: () => Promise<Preferences>, done?: string) {
    setError(null);
    setMessage(null);
    try {
      setPrefs(await action());
      if (done) setMessage(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible.");
    }
  }

  async function saveName(event: FormEvent) {
    event.preventDefault();
    try {
      onUserChanged(await api.updateProfile(displayName.trim()));
      setMessage("Nom enregistré.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible.");
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (passwords.next !== passwords.confirm) return setError("Les deux nouveaux mots de passe ne sont pas identiques.");
    try {
      await api.changePassword(passwords.current, passwords.next);
      setPasswords({ current: "", next: "", confirm: "" });
      setMessage("Mot de passe changé. Tes autres appareils ont été déconnectés.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Changement impossible.");
    }
  }

  async function deleteAccount(event: FormEvent) {
    event.preventDefault();
    if (!window.confirm("Supprimer définitivement ton compte et toutes tes données ? C'est irréversible.")) return;
    try {
      await api.deleteAccount(deletePassword);
      onAccountDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suppression impossible.");
    }
  }

  if (!prefs) return error ? <ErrorMessage message={error} /> : <Loading />;

  const unusedCategories = categories.filter((c) => !prefs.thresholds.some((t) => t.category_id === c.id));

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold">Préférences</h1>
      <ErrorMessage message={error} />
      {message && <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700 dark:bg-stone-800 dark:text-brand-500">{message}</p>}

      {user.role === "super_admin" && <AdminSettingsSection />}

      <Section title="Repas" hint="Valeurs utilisées par défaut dans les propositions de repas.">
        <div className="grid max-w-md grid-cols-2 gap-3">
          <Field label="Régime">
            <select className={inputClass} value={prefs.diet} onChange={(e) => save(() => api.updatePreferences({ diet: e.target.value as Preferences["diet"] }))}>
              <option value="none">Tous</option>
              <option value="vegetarian">Végétarien</option>
              <option value="vegan">Vegan</option>
            </select>
          </Field>
          <Field label="Personnes">
            <input
              type="number"
              min={1}
              max={999}
              className={inputClass}
              defaultValue={prefs.default_servings}
              onBlur={(e) => {
                const value = Math.min(999, Math.max(1, Number(e.target.value) || 1));
                if (value !== prefs.default_servings) save(() => api.updatePreferences({ default_servings: value }));
              }}
            />
          </Field>
        </div>
      </Section>

      <Section title="Alertes de péremption" hint="Un aliment est signalé « expire bientôt » quand il lui reste ce nombre de jours ou moins.">
        <div className="max-w-xs">
          <Field label="Seuil général (jours)">
            <input
              type="number"
              min={0}
              max={60}
              className={inputClass}
              defaultValue={prefs.expiring_soon_days}
              onBlur={(e) => {
                const value = Math.min(60, Math.max(0, Number(e.target.value) || 0));
                if (value !== prefs.expiring_soon_days) save(() => api.updatePreferences({ expiring_soon_days: value }), "Seuil enregistré.");
              }}
            />
          </Field>
        </div>
        <p className="mb-2 mt-4 text-sm font-medium">Seuils par catégorie</p>
        <ul className="mb-3 space-y-1.5">
          {prefs.thresholds.map((t) => (
            <li key={t.category_id} className="flex items-center gap-3 text-sm">
              <span className="w-48">{t.category_name}</span>
              <input
                type="number"
                min={0}
                max={60}
                defaultValue={t.days}
                className={inputClass + " w-20 py-1"}
                onBlur={(e) => {
                  const value = Math.min(60, Math.max(0, Number(e.target.value) || 0));
                  if (value !== t.days) save(() => api.setThreshold(t.category_id, value));
                }}
                aria-label={`Jours pour ${t.category_name}`}
              />
              jours
              <button className="text-stone-500 hover:text-red-600" onClick={() => save(() => api.removeThreshold(t.category_id))}>
                Retirer
              </button>
            </li>
          ))}
        </ul>
        <div className="flex max-w-md gap-2">
          <select className={inputClass} value={newThreshold.categoryId} onChange={(e) => setNewThreshold({ ...newThreshold, categoryId: e.target.value })}>
            <option value="">Ajouter une catégorie…</option>
            {unusedCategories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={0}
            max={60}
            className={inputClass + " w-20"}
            value={newThreshold.days}
            onChange={(e) => setNewThreshold({ ...newThreshold, days: e.target.value })}
            aria-label="Jours"
          />
          <button
            className={secondaryButton}
            disabled={!newThreshold.categoryId}
            onClick={() =>
              save(() => api.setThreshold(newThreshold.categoryId, Math.min(60, Math.max(0, Number(newThreshold.days) || 0)))).then(() =>
                setNewThreshold({ categoryId: "", days: "1" }),
              )
            }
          >
            Ajouter
          </button>
        </div>
      </Section>

      <Section
        title="Aliments exclus"
        hint="Allergie : une recette qui en contient n'est jamais proposée. N'aime pas : la recette est proposée, mais l'aliment est signalé."
      >
        <ul className="mb-3 space-y-1.5">
          {prefs.exclusions.map((e) => (
            <li key={e.food_id} className="flex items-center gap-3 text-sm">
              <span className="w-48">{e.name}</span>
              <select
                className={inputClass + " w-auto py-1"}
                value={e.reason}
                onChange={(ev) => save(() => api.setExclusion(e.food_id, ev.target.value as "allergy" | "dislike"))}
              >
                <option value="allergy">Allergie</option>
                <option value="dislike">N'aime pas</option>
              </select>
              <button className="text-stone-500 hover:text-red-600" onClick={() => save(() => api.removeExclusion(e.food_id))}>
                Retirer
              </button>
            </li>
          ))}
        </ul>
        <FoodSearch placeholder="Ajouter un aliment (ex. arachide)" onPick={(food) => save(() => api.setExclusion(food.id, "dislike"))} />
      </Section>

      <Section title="Toujours disponible" hint="Ces basiques ne sont jamais comptés comme manquants ni ajoutés à la liste de courses.">
        <div className="mb-3 flex flex-wrap gap-1.5">
          {prefs.basics.map((b) => (
            <span key={b.food_id} className="inline-flex items-center gap-1 rounded-full bg-stone-100 px-3 py-1 text-sm dark:bg-stone-800">
              {b.name}
              {b.removable ? (
                <button aria-label={`Retirer ${b.name}`} className="text-stone-400 hover:text-red-600" onClick={() => save(() => api.removeBasic(b.food_id))}>
                  ×
                </button>
              ) : (
                <span className="text-xs text-stone-500">(pour tous)</span>
              )}
            </span>
          ))}
        </div>
        <FoodSearch placeholder="Ajouter un basique (ex. sel, poivre, huile)" onPick={(food) => save(() => api.addBasic(food.id))} />
      </Section>

      <Section title="Mon compte">
        <form onSubmit={saveName} className="mb-5 flex max-w-md items-end gap-2">
          <Field label={`Nom affiché (identifiant : ${user.username})`}>
            <input className={inputClass} value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={60} />
          </Field>
          <button className={secondaryButton} disabled={!displayName.trim() || displayName.trim() === user.display_name}>
            Enregistrer
          </button>
        </form>
        <form onSubmit={savePassword} className="grid max-w-md gap-3">
          <Field label="Mot de passe actuel">
            <input type="password" autoComplete="current-password" className={inputClass} value={passwords.current} onChange={(e) => setPasswords({ ...passwords, current: e.target.value })} />
          </Field>
          <Field label="Nouveau mot de passe" hint="10 caractères minimum. Tes autres appareils seront déconnectés.">
            <input type="password" autoComplete="new-password" minLength={10} className={inputClass} value={passwords.next} onChange={(e) => setPasswords({ ...passwords, next: e.target.value })} />
          </Field>
          <Field label="Confirmer le nouveau mot de passe">
            <input type="password" autoComplete="new-password" className={inputClass} value={passwords.confirm} onChange={(e) => setPasswords({ ...passwords, confirm: e.target.value })} />
          </Field>
          <button className={primaryButton + " justify-self-start"} disabled={!passwords.current || passwords.next.length < 10}>
            Changer le mot de passe
          </button>
        </form>
      </Section>

      <section className="rounded-xl border border-red-300 p-5 dark:border-red-900">
        <h2 className="font-semibold text-red-700 dark:text-red-400">Supprimer mon compte</h2>
        <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
          Efface ton compte, ton inventaire personnel, ton agenda, tes recettes et tes préférences. Tes inventaires partagés sont transmis au membre le plus ancien, ou supprimés si tu y étais seul.
        </p>
        <form onSubmit={deleteAccount} className="flex max-w-md items-end gap-2">
          <Field label="Mot de passe">
            <input type="password" autoComplete="current-password" className={inputClass} value={deletePassword} onChange={(e) => setDeletePassword(e.target.value)} />
          </Field>
          <button className="rounded-lg bg-red-600 px-4 py-2 font-medium text-white hover:bg-red-700 disabled:opacity-60" disabled={!deletePassword}>
            Supprimer
          </button>
        </form>
      </section>
    </div>
  );
}

/** Paramètres globaux (super-administrateur) : mode d'analyse photo appliqué à tout le monde. */
function AdminSettingsSection() {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    api
      .adminSettings()
      .then((s) => {
        setSettings(s);
        setUrl(s.photo_local_url);
        setModel(s.photo_local_model);
      })
      .catch(() => setFailure("Impossible de lire les paramètres globaux."));
  }, []);

  async function save(change: Partial<AdminSettings>) {
    setFailure(null);
    try {
      setSettings(await api.updateAdminSettings(change));
      setSaved("Enregistré.");
      setTimeout(() => setSaved(null), 2000);
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "Enregistrement impossible.");
    }
  }

  if (!settings) return failure ? <ErrorMessage message={failure} /> : null;
  return (
    <Section title="Administration · IA" hint="Réglage appliqué à tous les utilisateurs.">
      <div className="space-y-3 text-sm">
        <label className="flex items-start gap-2">
          <input type="radio" className="mt-1" checked={settings.photo_engine === "claude"} onChange={() => save({ photo_engine: "claude" })} />
          <span>
            <span className="font-medium">API Claude (Claude Sonnet 5.5)</span>
            <span className="block text-stone-500">Précis, lit les dates sur les emballages ; environ 0,02 $ par photo, la photo quitte le PC le temps de l'analyse.</span>
          </span>
        </label>
        <label className="flex items-start gap-2">
          <input type="radio" className="mt-1" checked={settings.photo_engine === "local"} onChange={() => save({ photo_engine: "local" })} />
          <span>
            <span className="font-medium">Modèle local (Ollama)</span>
            <span className="block text-stone-500">Gratuit, rien ne sort du PC ; moins précis et plus lent, demande une carte graphique.</span>
          </span>
        </label>
        {settings.photo_engine === "local" && (
          <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <input className={inputClass} value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Adresse d'Ollama" placeholder="http://host.docker.internal:11434" />
            <input className={inputClass} value={model} onChange={(e) => setModel(e.target.value)} aria-label="Modèle" placeholder="qwen2.5vl:7b" />
            <button className={secondaryButton} onClick={() => save({ photo_local_url: url.trim(), photo_local_model: model.trim() })}>
              Enregistrer
            </button>
          </div>
        )}
        <label className="block border-t border-stone-200 pt-3 dark:border-stone-800">
          <span className="mb-1 block font-medium">Modèle des recettes inventées par l'IA</span>
          <select
            className={inputClass}
            value={settings.ai_recipe_model}
            onChange={(e) => save({ ai_recipe_model: e.target.value as AdminSettings["ai_recipe_model"] })}
          >
            <option value="claude-opus-5-5">Claude Opus 5.5 : le plus inventif, environ 0,03 $ par recette</option>
            <option value="claude-sonnet-5-5">Claude Sonnet 5.5 : très bon, environ 0,015 $ par recette</option>
            <option value="claude-haiku-5-5">Claude Haiku 5.5 : le plus économique, moins de 0,001 $ par recette</option>
          </select>
        </label>
        {saved && <p className="text-brand-700 dark:text-brand-500">{saved}</p>}
        <ErrorMessage message={failure} />
      </div>
    </Section>
  );
}
