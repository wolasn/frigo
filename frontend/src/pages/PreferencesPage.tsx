import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, type AdminSettings, type AgentRun, type AiUsage, type Category, type UsageCall, type UserUsage, type Food, type Preferences, type User } from "../api";
import { ErrorMessage, Field, inputClass, primaryButton, secondaryButton, Loading } from "../components/ui";
import CategorySelect from "../components/inventory/CategorySelect";

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
  const [category, setCategory] = useState("");
  const [results, setResults] = useState<Food[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  // La liste se ferme au clic en dehors de la recherche (ou avec Échap), comme une liste déroulante.
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  useEffect(() => {
    if (!query.trim() && !category) return setResults([]);
    const timer = setTimeout(() => api.searchFoods(query, category).then(setResults).catch(() => setResults([])), 200);
    return () => clearTimeout(timer);
  }, [query, category]);

  return (
    <div ref={box} className="relative max-w-xl">
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          className={inputClass}
          placeholder={placeholder}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
        />
        <CategorySelect
          value={category}
          onChange={(id) => {
            setCategory(id);
            setOpen(true);
          }}
        />
      </div>
      {open && results.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-stone-200 bg-white shadow-lg dark:border-stone-700 dark:bg-stone-900">
          {results.map((food) => (
            <li key={food.id}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left hover:bg-stone-100 dark:hover:bg-stone-800"
                onClick={() => {
                  onPick(food);
                  setQuery("");
                  setOpen(false);
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
      {user.role === "super_admin" && <DailyAgentSection />}
      {user.role === "super_admin" && <AiUsageSection />}

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
            <label className="flex items-start gap-2 sm:col-span-3">
              <input
                type="checkbox"
                className="mt-1"
                checked={settings.photo_local_fallback}
                onChange={(e) => save({ photo_local_fallback: e.target.checked })}
              />
              <span>
                Si le modèle local ne répond pas (PC éteint, en veille ou hors réseau), analyser avec l'API Claude
                <span className="block text-stone-500">Sinon, l'analyse échoue et l'aliment s'ajoute à la main.</span>
              </span>
            </label>
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

const AGENT_STATUS: Record<AgentRun["status"], string> = { changed: "a changé le menu", kept: "a gardé le menu", error: "erreur" };
const TOOL_LABELS: Record<string, string> = {
  profil: "profil",
  inventaire: "inventaire",
  historique: "historique",
  recettes_du_jour_actuelles: "menu actuel",
  chercher_dans_la_base: "recherche base",
  chercher_sur_marmiton: "Marmiton",
  detail_recette: "détail",
  definir_recettes_du_jour: "nouveau menu",
};

/** Agent IA des recettes du jour (super-administrateur) : activation, modèle, consignes, essai et journal. */
function DailyAgentSection() {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [prompt, setPrompt] = useState("");
  const [runs, setRuns] = useState<AgentRun[] | null>(null);
  const [running, setRunning] = useState(false);
  const [last, setLast] = useState<AgentRun | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const loadRuns = () => api.dailyAgentRuns().then(setRuns).catch(() => setRuns([]));

  useEffect(() => {
    api
      .adminSettings()
      .then((s) => {
        setSettings(s);
        setPrompt(s.daily_agent_prompt);
      })
      .catch(() => setFailure("Impossible de lire les réglages de l'agent."));
    loadRuns();
  }, []);

  async function save(change: Partial<AdminSettings>) {
    setFailure(null);
    try {
      const updated = await api.updateAdminSettings(change);
      setSettings(updated);
      setPrompt(updated.daily_agent_prompt);
      setSaved("Enregistré.");
      setTimeout(() => setSaved(null), 2000);
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "Enregistrement impossible.");
    }
  }

  async function runNow() {
    setFailure(null);
    setRunning(true);
    setLast(null);
    try {
      setLast(await api.runDailyAgent());
      loadRuns();
    } catch (err) {
      setFailure(err instanceof Error ? err.message : "Lancement impossible.");
    } finally {
      setRunning(false);
    }
  }

  if (!settings) return failure ? <ErrorMessage message={failure} /> : null;
  return (
    <Section
      title="Administration · agent des recettes du jour"
      hint="Chaque matin, après le choix automatique, un agent IA relit le profil, l'inventaire et l'historique de chaque compte actif, cherche dans la base et sur Marmiton, puis garde ou remplace les trois recettes du jour."
    >
      <div className="space-y-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={settings.daily_agent_enabled} onChange={(e) => save({ daily_agent_enabled: e.target.checked })} />
          Faire passer l'agent chaque matin
        </label>
        <label className="block">
          <span className="mb-1 block font-medium">Modèle de l'agent</span>
          <select
            className={inputClass}
            value={settings.daily_agent_model}
            onChange={(e) => save({ daily_agent_model: e.target.value as AdminSettings["daily_agent_model"] })}
          >
            <option value="claude-opus-5-5">Claude Opus 5.5 : le plus fin</option>
            <option value="claude-sonnet-5-5">Claude Sonnet 5.5 : environ deux fois moins cher</option>
            <option value="claude-haiku-5-5">Claude Haiku 5.5 : très économique, choix plus simples</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block font-medium">Consignes de l'agent</span>
          <textarea className={inputClass + " min-h-48 font-mono text-xs"} value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={4000} />
          <span className="mt-1 block text-xs text-stone-500">
            Ce que l'agent doit privilégier. Le reste (régime, allergies, ustensiles, pas de répétition sur 14 jours) est garanti par l'application.
          </span>
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <button
            className={secondaryButton}
            disabled={prompt.trim().length < 10 || prompt === settings.daily_agent_prompt}
            onClick={() => save({ daily_agent_prompt: prompt.trim() })}
          >
            Enregistrer les consignes
          </button>
          <button className="text-stone-500 hover:underline disabled:opacity-50" disabled={prompt === settings.daily_agent_default_prompt} onClick={() => setPrompt(settings.daily_agent_default_prompt)}>
            Revenir aux consignes de départ
          </button>
          <button className={primaryButton + " sm:ml-auto"} onClick={runNow} disabled={running}>
            {running ? "L'agent réfléchit… (jusqu'à deux minutes)" : "Lancer pour moi maintenant"}
          </button>
        </div>
        {saved && <p className="text-brand-700 dark:text-brand-500">{saved}</p>}
        <ErrorMessage message={failure} />
        {last && (
          <p className="rounded-lg bg-stone-50 p-3 dark:bg-stone-950">
            <strong>{AGENT_STATUS[last.status]}</strong> · {last.steps.length} outil(s) · {dollars(last.cost_usd)}
            {last.message && <span className="mt-1 block">« {last.message} »</span>}
            {last.error && <span className="mt-1 block text-red-700 dark:text-red-400">{last.error}</span>}
            <span className="mt-1 block text-xs text-stone-500">Le résultat est visible dans l'onglet Repas.</span>
          </p>
        )}
        <div className="border-t border-stone-200 pt-3 dark:border-stone-800">
          <h3 className="mb-1 font-medium">Journal</h3>
          {runs === null ? (
            <Loading inline />
          ) : runs.length === 0 ? (
            <p className="text-stone-500">L'agent n'est pas encore passé.</p>
          ) : (
            <ul className="max-h-80 space-y-2 overflow-y-auto">
              {runs.map((r) => (
                <li key={r.id} className="rounded-lg bg-stone-50 p-2 text-xs dark:bg-stone-950">
                  <span className="font-medium">
                    {new Date(r.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} · {r.username} · {AGENT_STATUS[r.status]}
                  </span>
                  <span className="text-stone-500"> · {MODEL_LABELS[r.model] ?? r.model} · {dollars(r.cost_usd)}</span>
                  <span className="block text-stone-500">{r.steps.map((s) => TOOL_LABELS[s.outil] ?? s.outil).join(" → ")}</span>
                  {r.message && <span className="block">« {r.message} »</span>}
                  {r.error && <span className="block text-red-700 dark:text-red-400">{r.error}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Section>
  );
}

const dollars = (value: number) => `${value < 1 ? value.toFixed(4) : value.toFixed(2)} $`.replace(".", ",");
const MODEL_LABELS: Record<string, string> = {
  "claude-opus-5-5": "Opus 5.5",
  "claude-sonnet-5-5": "Sonnet 5.5",
  "claude-haiku-5-5": "Haiku 5.5",
};

/** Coût de l'IA par utilisateur (super-administrateur) : total du mois, détail des appels au clic. */
function AiUsageSection() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [allTime, setAllTime] = useState(false);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [calls, setCalls] = useState<UsageCall[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const period = allTime ? undefined : month;

  useEffect(() => {
    setUsage(null);
    setOpen(null);
    api.aiUsage(period).then(setUsage).catch(() => setFailure("Impossible de lire les coûts de l'IA."));
  }, [period]);

  const keyOf = (u: UserUsage) => u.user_id ?? `supprimé:${u.username}`;

  function toggle(u: UserUsage) {
    const key = keyOf(u);
    if (open === key) {
      setOpen(null);
      return;
    }
    setOpen(key);
    setCalls(null);
    api.aiUsageDetail(key, period).then(setCalls).catch(() => setCalls([]));
  }

  return (
    <Section title="Administration · coûts de l'IA" hint="Coût estimé à chaque appel (recettes IA, analyses photo et agent des recettes du jour), d'après les jetons et les tarifs publics.">
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <input type="month" className={inputClass + " w-auto"} value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} disabled={allTime} aria-label="Mois" />
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={allTime} onChange={(e) => setAllTime(e.target.checked)} /> Depuis le début
          </label>
        </div>
        <ErrorMessage message={failure} />
        {!usage ? (
          !failure && <Loading inline />
        ) : (
          <>
            <p>
              Total : <strong>{dollars(usage.total.cost_usd)}</strong> pour {usage.total.calls} appel(s)
            </p>
            {usage.users.length === 0 ? (
              <p className="text-stone-500">Aucun appel à l'IA sur cette période.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="text-xs text-stone-500">
                    <tr>
                      <th className="py-1 pr-2 font-medium">Utilisateur</th>
                      <th className="py-1 pr-2 text-right font-medium">Recettes</th>
                      <th className="py-1 pr-2 text-right font-medium">Photos</th>
                      <th className="py-1 pr-2 text-right font-medium">Agent</th>
                      <th className="py-1 text-right font-medium">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-200 dark:divide-stone-800">
                    {usage.users.map((u) => (
                      <UsageRow key={keyOf(u)} user={u} open={open === keyOf(u)} calls={calls} onToggle={() => toggle(u)} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </Section>
  );
}

function UsageRow({ user, open, calls, onToggle }: { user: UserUsage; open: boolean; calls: UsageCall[] | null; onToggle: () => void }) {
  return (
    <>
      <tr className="cursor-pointer hover:bg-stone-50 dark:hover:bg-stone-800" onClick={onToggle}>
        <td className="py-1.5 pr-2">
          {open ? "▾" : "▸"} {user.display_name ?? user.username}
          <span className="text-xs text-stone-500"> · {user.user_id ? user.username : "compte supprimé"}</span>
        </td>
        <td className="py-1.5 pr-2 text-right">
          {dollars(user.recipes.cost_usd)} <span className="text-xs text-stone-500">({user.recipes.calls})</span>
        </td>
        <td className="py-1.5 pr-2 text-right">
          {dollars(user.photos.cost_usd)} <span className="text-xs text-stone-500">({user.photos.calls})</span>
        </td>
        <td className="py-1.5 pr-2 text-right">
          {dollars(user.agent.cost_usd)} <span className="text-xs text-stone-500">({user.agent.calls})</span>
        </td>
        <td className="py-1.5 text-right font-medium">{dollars(user.cost_usd)}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} className="pb-2">
            {calls === null ? (
              <Loading inline />
            ) : (
              <ul className="max-h-60 space-y-0.5 overflow-y-auto rounded-lg bg-stone-50 p-2 text-xs dark:bg-stone-950">
                {calls.map((c, i) => (
                  <li key={i} className="flex flex-wrap justify-between gap-2">
                    <span>
                      {new Date(c.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} ·{" "}
                      {{ recipe: "recette", photo: "photo", agent: "agent" }[c.kind] ?? c.kind} · {MODEL_LABELS[c.model] ?? c.model}
                    </span>
                    <span className="text-stone-500">
                      {c.input_tokens} + {c.output_tokens} jetons · <span className="text-stone-700 dark:text-stone-300">{dollars(c.cost_usd)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
