import { useEffect, useRef, type ReactNode } from "react";

export const inputClass =
  "w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-base outline-none focus:border-brand-500 " +
  "focus:ring-2 focus:ring-brand-100 dark:border-stone-700 dark:bg-stone-900 dark:focus:ring-brand-700";

export const primaryButton =
  "rounded-lg bg-brand-600 px-4 py-2 font-medium text-white transition hover:bg-brand-700 disabled:opacity-60";

export const secondaryButton =
  "rounded-lg border border-stone-300 px-4 py-2 font-medium transition hover:bg-stone-100 " +
  "dark:border-stone-700 dark:hover:bg-stone-800 disabled:opacity-60";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-500">{hint}</span>}
    </label>
  );
}

export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
      {message}
    </p>
  );
}

/** Fenêtre modale basée sur <dialog> : Échap et clic hors du cadre la ferment. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => e.target === ref.current && onClose()}
      className="m-auto w-[min(32rem,calc(100%-2rem))] rounded-2xl bg-white p-0 text-stone-900 shadow-xl backdrop:bg-black/40 dark:bg-stone-900 dark:text-stone-100"
    >
      <div className="max-h-[85dvh] overflow-y-auto p-5">
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Fermer" className="rounded-md px-2 text-xl leading-none text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800">
            ×
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

/** Petite roue qui tourne pendant un chargement, avec un texte. `inline` : version discrète à côté d'un titre. */
export function Loading({ label = "Chargement…", inline = false }: { label?: string; inline?: boolean }) {
  return (
    <span role="status" className={(inline ? "inline-flex" : "flex py-6") + " items-center gap-2 text-sm text-stone-500"}>
      <span
        aria-hidden
        className={(inline ? "size-4" : "size-6") + " animate-spin rounded-full border-[3px] border-stone-300 border-t-brand-600 dark:border-stone-700 dark:border-t-brand-500"}
      />
      {label}
    </span>
  );
}
