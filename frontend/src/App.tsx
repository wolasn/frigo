import { useEffect, useState } from "react";
import { api, ApiError, type User } from "./api";
import AuthPage from "./pages/AuthPage";
import HomePage from "./pages/HomePage";

type State = { status: "loading" } | { status: "anonymous" } | { status: "error" } | { status: "ready"; user: User };

export default function App() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    api
      .me()
      .then((user) => setState({ status: "ready", user }))
      .catch((err) => setState(err instanceof ApiError && err.status === 401 ? { status: "anonymous" } : { status: "error" }));
  }, []);

  if (state.status === "loading") {
    return <p className="p-8 text-stone-500">Chargement…</p>;
  }
  if (state.status === "error") {
    return (
      <p className="p-8 text-stone-600 dark:text-stone-400">
        Le service est momentanément indisponible. Réessaie dans un instant, ou contacte l'administrateur.
      </p>
    );
  }
  if (state.status === "anonymous") {
    return <AuthPage onAuthenticated={(user) => setState({ status: "ready", user })} />;
  }
  return (
    <HomePage
      user={state.user}
      onLoggedOut={() => setState({ status: "anonymous" })}
      onUserChanged={(user) => setState({ status: "ready", user })}
    />
  );
}
