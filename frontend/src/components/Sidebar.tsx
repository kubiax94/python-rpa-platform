"use client";

import { useState, type ReactNode } from "react";
import type { AuthUser } from "@/lib/auth";
import { formatRoleLabel, getHighestRole } from "@/lib/rbac";
import { ConnectionStatus } from "./ConnectionStatus";

export type MenuPage = "agents" | "tasks" | "deployments" | "settings";

interface SidebarProps {
  activePage: MenuPage;
  onNavigate: (page: MenuPage) => void;
  connected: boolean;
  agentCount: number;
  activeTaskCount: number;
  currentUser: AuthUser;
  onLogout: () => Promise<void>;
  availablePages: MenuPage[];
  guacamoleSession?: {
    agentId: string;
    connected: boolean;
    minimized: boolean;
    fullscreen: boolean;
  } | null;
}

const menuItems: { id: MenuPage; label: string; icon: ReactNode }[] = [
  {
    id: "agents",
    label: "Agents",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-13.5 0a3 3 0 0 1-3-3m3 3h13.5m-13.5-6a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0-6h13.5a3 3 0 1 0 0 6m-13.5 0h13.5m-13.5 0a3 3 0 0 1-3 3" />
      </svg>
    ),
  },
  {
    id: "tasks",
    label: "Tasks",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15a2.25 2.25 0 0 1 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25ZM6.75 12h.008v.008H6.75V12Zm0 3h.008v.008H6.75V15Zm0 3h.008v.008H6.75V18Z" />
      </svg>
    ),
  },
  {
    id: "deployments",
    label: "Deployments",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5m-16.5 0v10.5a2.25 2.25 0 0 0 2.25 2.25h12a2.25 2.25 0 0 0 2.25-2.25V6.75m-16.5 0A2.25 2.25 0 0 1 6 4.5h12a2.25 2.25 0 0 1 2.25 2.25m-9 4.5h3m-1.5-1.5v3" />
      </svg>
    ),
  },
  {
    id: "settings",
    label: "Settings",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
      </svg>
    ),
  },
];

export function Sidebar({ activePage, onNavigate, connected, agentCount, activeTaskCount, currentUser, onLogout, availablePages, guacamoleSession }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const effectiveRoleLabel = formatRoleLabel(getHighestRole(currentUser.roles));
  const userLabel = currentUser.display_name || currentUser.username || currentUser.email || currentUser.subject;
  const providerLabel = currentUser.auth_provider === "azure_entra" ? "Microsoft Entra" : currentUser.auth_provider;

  return (
    <div
      className={`flex flex-col h-screen bg-slate-900 border-r border-slate-700/50 transition-all duration-200 ${
        collapsed ? "w-16" : "w-56"
      }`}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 h-14 border-b border-slate-700/50">
        <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-sm shrink-0">
          O
        </div>
        {!collapsed && (
          <span className="font-semibold text-slate-100 text-sm whitespace-nowrap">
            My Orciestra
          </span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2 space-y-1">
        {menuItems.filter((item) => availablePages.includes(item.id)).map((item) => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              activePage === item.id
                ? "bg-blue-600/20 text-blue-400"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
            }`}
            title={collapsed ? item.label : undefined}
          >
            {item.icon}
            {!collapsed && <span>{item.label}</span>}
            {!collapsed && item.id === "agents" && agentCount > 0 && (
              <span className="ml-auto text-xs bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded-full">
                {agentCount}
              </span>
            )}
            {!collapsed && item.id === "tasks" && activeTaskCount > 0 && (
              <span className="ml-auto text-xs bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded-full">
                {activeTaskCount}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* Bottom — connection + collapse */}
      <div className="border-t border-slate-700/50 px-3 py-3 space-y-2">
        {!collapsed && (
          <div className="rounded-lg border border-slate-700/80 bg-slate-950/70 px-3 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-100">{userLabel}</p>
                <p className="mt-1 truncate text-[11px] text-slate-500">{currentUser.email || currentUser.username || providerLabel}</p>
              </div>
              <button
                type="button"
                onClick={() => void onLogout()}
                className="rounded-md border border-slate-700 px-2 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-600 hover:bg-slate-900"
              >
                Logout
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.16em] text-cyan-200">
                {effectiveRoleLabel}
              </span>
            </div>
          </div>
        )}
        {!collapsed && guacamoleSession && (
          <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-200">RDP</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                guacamoleSession.connected
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-blue-500/15 text-blue-200"
              }`}>
                {guacamoleSession.connected ? "Live" : "Opening"}
              </span>
            </div>
            <p className="mt-2 truncate text-xs font-medium text-slate-100">{guacamoleSession.agentId}</p>
            <p className="mt-1 text-[11px] text-slate-400">
              {guacamoleSession.fullscreen ? "Fullscreen" : guacamoleSession.minimized ? "Minimized" : "Docked"}
            </p>
          </div>
        )}
        {!collapsed && <ConnectionStatus connected={connected} agentCount={agentCount} />}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-center py-1.5 text-slate-500 hover:text-slate-300 transition-colors"
          title={collapsed ? "Expand" : "Collapse"}
        >
          <svg
            className={`w-4 h-4 transition-transform ${collapsed ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
          </svg>
        </button>
      </div>
    </div>
  );
}
