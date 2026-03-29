"use client";

function prettifyParameterLabel(name: string): string {
  return name
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function inferFieldType(name: string): "text" | "password" {
  const normalizedName = name.toLowerCase();
  return normalizedName.includes("password") || normalizedName.includes("secret")
    ? "password"
    : "text";
}

export function GuacamoleRequiredPrompt({
  parameters,
  values,
  submitting,
  error,
  targetHost,
  onValueChange,
  onSubmit,
  onCancel,
}: {
  parameters: string[];
  values: Record<string, string>;
  submitting: boolean;
  error: string | null;
  targetHost?: string | null;
  onValueChange: (name: string, value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  if (!parameters.length) {
    return null;
  }

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-950/72 p-4 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-slate-700/80 bg-slate-900/96 shadow-2xl shadow-black/40">
        <div className="border-b border-slate-700/80 px-5 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-300">Guacamole Credentials</p>
          <h3 className="mt-2 text-lg font-semibold text-slate-100">Remote desktop requires additional parameters</h3>
          <p className="mt-1 text-sm text-slate-400">
            {targetHost ? `Provide credentials for ${targetHost}.` : "Provide the requested values so the session can continue."}
          </p>
        </div>

        <div className="space-y-4 px-5 py-5">
          <div className="grid gap-4">
            {parameters.map((parameter) => {
              const fieldType = inferFieldType(parameter);
              return (
                <label key={parameter} className="block text-sm">
                  <span className="mb-1 block text-slate-300">{prettifyParameterLabel(parameter)}</span>
                  <input
                    type={fieldType}
                    autoComplete={fieldType === "password" ? "current-password" : "username"}
                    value={values[parameter] ?? ""}
                    onChange={(event) => onValueChange(parameter, event.target.value)}
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                    placeholder={parameter}
                    disabled={submitting}
                  />
                </label>
              );
            })}
          </div>

          {error && (
            <div className="rounded-lg border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
              {error}
            </div>
          )}

          <div className="flex items-center justify-between gap-3 border-t border-slate-800 pt-4">
            <button
              onClick={onCancel}
              disabled={submitting}
              className="rounded-lg border border-slate-600 bg-slate-950/70 px-4 py-2 text-sm font-medium text-slate-300 hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Cancel Session
            </button>
            <button
              onClick={onSubmit}
              disabled={submitting}
              className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {submitting ? "Sending..." : "Continue"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}