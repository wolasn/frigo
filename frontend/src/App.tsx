import { useEffect, useState } from "react";

type Health = { status: string; database: string; detail?: string };

const DATABASE_LABELS: Record<string, string> = {
  ok: "connectée",
  non_configuree: "non configurée",
  erreur: "injoignable",
};

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => setError(true));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 640, margin: "48px auto", padding: "0 16px" }}>
      <h1>Frigo &amp; Repas</h1>
      {error && <p>L'API ne répond pas.</p>}
      {!error && !health && <p>Vérification de l'API…</p>}
      {health && (
        <p>
          API en ligne · base de données {DATABASE_LABELS[health.database] ?? health.database}
          {health.detail ? ` (${health.detail})` : ""}
        </p>
      )}
    </main>
  );
}
