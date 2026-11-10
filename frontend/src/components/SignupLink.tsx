import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorMessage, inputClass, primaryButton, secondaryButton } from "./ui";

/** Lien d'inscription à l'appli : une seule utilisation, valable 10 minutes. */
export default function SignupLink() {
  const [link, setLink] = useState<{ url: string; expires: number } | null>(null);
  const [now, setNow] = useState(Date.now());
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!link) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [link]);

  async function create() {
    setError(null);
    setBusy(true);
    try {
      const { code, expires_at } = await api.createSignupInvitation();
      const url = `${window.location.origin}/?invitation=${encodeURIComponent(code)}`;
      setLink({ url, expires: new Date(expires_at).getTime() });
      setNow(Date.now());
      setCopied(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Création du lien impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false); // presse-papiers indisponible : le lien reste sélectionnable
    }
  }

  const left = link ? Math.max(0, Math.round((link.expires - now) / 1000)) : 0;
  const expired = link !== null && left === 0;

  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">Inviter quelqu'un sur l'appli</h2>
      <div className="space-y-3 rounded-xl border border-stone-200 bg-white p-4 text-sm dark:border-stone-800 dark:bg-stone-900">
        <p className="text-stone-600 dark:text-stone-400">
          L'appli est privée : on ne peut créer un compte qu'avec un lien d'invitation. Chaque lien sert une seule fois et
          expire au bout de 10 minutes.
        </p>
        {link && !expired && (
          <div className="space-y-2">
            <div className="flex gap-2">
              <input className={inputClass} readOnly value={link.url} onFocus={(e) => e.target.select()} aria-label="Lien d'inscription" />
              <button className={secondaryButton} onClick={() => copy(link.url)}>
                {copied ? "Copié" : "Copier"}
              </button>
            </div>
            <p className="text-stone-500">
              Valable encore {Math.floor(left / 60)} min {String(left % 60).padStart(2, "0")} s, pour une seule inscription.
            </p>
          </div>
        )}
        {expired && <p className="text-amber-700 dark:text-amber-400">Ce lien a expiré.</p>}
        <ErrorMessage message={error} />
        <button className={primaryButton} onClick={create} disabled={busy}>
          {link ? "Créer un nouveau lien" : "Créer un lien d'inscription"}
        </button>
      </div>
    </section>
  );
}
