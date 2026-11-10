import { useEffect, useState, type FormEvent } from "react";
import { api, type User } from "../api";

type Mode = "login" | "register";

const inputClass =
  "w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-base outline-none focus:border-brand-500 " +
  "focus:ring-2 focus:ring-brand-100 dark:border-stone-700 dark:bg-stone-900 dark:focus:ring-brand-700";

// Code du lien d'inscription (https://…/?invitation=…)
const invitationCode = new URLSearchParams(window.location.search).get("invitation") ?? "";

export default function AuthPage({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [mode, setMode] = useState<Mode>(invitationCode ? "register" : "login");
  // null : vérification en cours ; true : inscription possible
  const [canRegister, setCanRegister] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .checkSignupInvitation(invitationCode)
      .then((check) => setCanRegister(check.valid))
      .catch(() => setCanRegister(false));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user =
        mode === "login"
          ? await api.login(username, password)
          : await api.register(username, displayName || username, password, invitationCode || undefined);
      if (invitationCode) window.history.replaceState(null, "", "/"); // lien utilisé : on le retire de l'adresse
      onAuthenticated(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Une erreur est survenue.");
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-2xl font-semibold">Frigo &amp; Repas</h1>
        <p className="mb-6 text-sm text-stone-600 dark:text-stone-400">
          Ton inventaire, tes repas et tes courses, au même endroit.
        </p>

        <div className="mb-5 grid grid-cols-2 rounded-lg bg-stone-200 p-1 text-sm dark:bg-stone-800" role="tablist">
          {(["login", "register"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => switchMode(m)}
              className={
                "rounded-md py-1.5 font-medium transition " +
                (mode === m
                  ? "bg-white shadow-sm dark:bg-stone-900"
                  : "text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100")
              }
            >
              {m === "login" ? "Connexion" : "Créer un compte"}
            </button>
          ))}
        </div>

        {mode === "register" && canRegister !== true ? (
          <p className="rounded-lg bg-stone-100 px-3 py-3 text-sm text-stone-700 dark:bg-stone-900 dark:text-stone-300">
            {canRegister === null
              ? "Vérification du lien…"
              : invitationCode
                ? "Ce lien d'inscription n'est plus valable : il a déjà servi ou il a expiré (10 minutes). Demande un nouveau lien à un membre."
                : "L'inscription se fait uniquement sur invitation : demande un lien à un membre de l'appli."}
          </p>
        ) : (
        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium">Identifiant</span>
            <input
              className={inputClass}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              required
              minLength={mode === "register" ? 3 : 1}
              maxLength={32}
              pattern={mode === "register" ? "[A-Za-z0-9_.\\-]{3,32}" : undefined}
              title={mode === "register" ? "3 à 32 caractères : lettres, chiffres, point, tiret, tiret bas" : undefined}
            />
          </label>

          {mode === "register" && (
            <label className="block">
              <span className="mb-1 block text-sm font-medium">Nom affiché</span>
              <input
                className={inputClass}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="nickname"
                maxLength={60}
                placeholder="Visible par les membres de tes inventaires partagés"
              />
            </label>
          )}

          <label className="block">
            <span className="mb-1 block text-sm font-medium">Mot de passe</span>
            <input
              className={inputClass}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 10 : 1}
              maxLength={200}
            />
            {mode === "register" && (
              <span className="mt-1 block text-xs text-stone-500">10 caractères minimum.</span>
            )}
          </label>

          {error && (
            <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-brand-600 py-2.5 font-medium text-white transition hover:bg-brand-700 disabled:opacity-60"
          >
            {busy ? "Un instant…" : mode === "login" ? "Se connecter" : "Créer mon compte"}
          </button>
        </form>
        )}
      </div>
    </main>
  );
}
