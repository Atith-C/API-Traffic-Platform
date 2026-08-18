import { useState } from "react";
import { useDashboard, useOrganizations } from "../api/hooks";
import { StatCard } from "../components/StatCard";
import { setToken } from "../api/client";

export function Dashboard() {
  const orgs = useOrganizations();
  const [orgId, setOrgId] = useState<string | null>(null);
  const selected = orgId ?? orgs.data?.items[0]?.id ?? null;
  const dash = useDashboard(selected);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-500">Live API traffic — refreshes every 15s</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={selected ?? ""}
            onChange={(e) => setOrgId(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {orgs.data?.items.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              setToken(null);
              location.reload();
            }}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          >
            Sign out
          </button>
        </div>
      </header>

      {orgs.data && orgs.data.items.length === 0 && (
        <p className="rounded-lg border border-slate-200 bg-white p-6 text-slate-500">
          You don't belong to any organizations yet.
        </p>
      )}

      {dash.data && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Requests" value={dash.data.summary.request_count} hint="last 7 days" />
            <StatCard label="Errors" value={dash.data.summary.error_count} />
            <StatCard
              label="Error rate"
              value={`${(dash.data.summary.error_rate * 100).toFixed(1)}%`}
            />
            <StatCard label="Avg latency" value={`${dash.data.summary.avg_latency_ms}ms`} />
            <StatCard label="p95 latency" value={`${dash.data.summary.p95_latency_ms}ms`} />
            <StatCard label="Active keys" value={dash.data.summary.active_keys} />
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="mb-3 text-sm font-semibold text-slate-700">Top endpoints</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-400">
                    <th className="pb-2">Path</th>
                    <th className="pb-2 text-right">Requests</th>
                    <th className="pb-2 text-right">Avg ms</th>
                  </tr>
                </thead>
                <tbody>
                  {dash.data.top_endpoints.map((e) => (
                    <tr key={e.path} className="border-t border-slate-100">
                      <td className="py-2 font-mono text-slate-700">/{e.path}</td>
                      <td className="py-2 text-right tabular-nums">{e.request_count}</td>
                      <td className="py-2 text-right tabular-nums">{e.avg_latency_ms}</td>
                    </tr>
                  ))}
                  {dash.data.top_endpoints.length === 0 && (
                    <tr>
                      <td colSpan={3} className="py-4 text-center text-slate-400">
                        No traffic yet
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="mb-3 text-sm font-semibold text-slate-700">Status breakdown</h2>
              <div className="space-y-2">
                {Object.entries(dash.data.status_breakdown).map(([klass, count]) => (
                  <div key={klass} className="flex items-center gap-3">
                    <span className="w-10 font-mono text-sm text-slate-500">{klass}</span>
                    <div className="h-3 flex-1 overflow-hidden rounded bg-slate-100">
                      <div
                        className={klass === "5xx" || klass === "4xx" ? "h-full bg-red-400" : "h-full bg-emerald-400"}
                        style={{
                          width: `${Math.min(
                            100,
                            (count / Math.max(1, dash.data!.summary.request_count)) * 100,
                          )}%`,
                        }}
                      />
                    </div>
                    <span className="w-10 text-right text-sm tabular-nums">{count}</span>
                  </div>
                ))}
                {Object.keys(dash.data.status_breakdown).length === 0 && (
                  <p className="text-center text-slate-400">No traffic yet</p>
                )}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
