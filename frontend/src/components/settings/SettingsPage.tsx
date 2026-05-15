/**
 * SettingsPage — admin-only configuration management.
 *
 * Layout:
 *   PageHeader across the top.
 *   Below: left rail of categories (desktop) / Select dropdown
 *   (mobile) + a scrollable content pane showing the active
 *   category's sections.
 *
 * Category selection is synced to the URL search params so the
 * browser history / back button works.
 */

import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useWsApi } from "@/hooks/useWsApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layout/PageHeader";
import { ConfigSection } from "./ConfigSection";
import { ServiceToggles } from "./ServiceToggles";
import { PluginPanelSlot } from "@/components/PluginPanelSlot";
import { cn } from "@/lib/utils";
import type { ConfigCategory } from "@/types/config";

export function SettingsPage() {
  const api = useWsApi();
  const { connected } = useWebSocket();
  const [searchParams, setSearchParams] = useSearchParams();

  const { data, isLoading } = useQuery({
    queryKey: ["config"],
    queryFn: api.describeConfig,
    enabled: connected,
    refetchInterval: 30_000,
  });

  const categories: ConfigCategory[] = data?.categories ?? [];
  const activeCategory = searchParams.get("category") || "";

  // Auto-select the first category if none in the URL.
  useEffect(() => {
    if (!activeCategory && categories.length > 0) {
      setSearchParams({ category: categories[0].name }, { replace: true });
    }
  }, [categories, activeCategory, setSearchParams]);

  const setCategory = (name: string) => {
    setSearchParams({ category: name });
  };

  const current = categories.find((c) => c.name === activeCategory);
  const totalSections = categories.reduce(
    (acc, c) => acc + c.sections.length,
    0,
  );

  if (isLoading) {
    return (
      <div>
        <PageHeader eyebrow="ADMIN" title="Settings" />
        <LoadingSpinner text="Loading configuration..." className="p-8" />
      </div>
    );
  }

  if (categories.length === 0) {
    return (
      <div>
        <PageHeader eyebrow="ADMIN" title="Settings" />
        <div className="px-6 py-12 text-center">
          <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
            No configurable services
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Nothing to configure yet. Services declare their config
            params when they register.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        eyebrow="ADMIN"
        title="Settings"
        description={
          <>
            {categories.length} categor
            {categories.length === 1 ? "y" : "ies"}, {totalSections} service
            {totalSections === 1 ? "" : "s"}.
          </>
        }
      />

      {/* Mobile — Select dropdown. Below md we don't have room for
          a persistent rail; the dropdown keeps the same surface
          (category names + counts) within reach. */}
      <div className="border-b border-border px-4 py-2 md:hidden">
        <Select
          value={activeCategory}
          onValueChange={(v) => {
            if (v) setCategory(v);
          }}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select category..." />
          </SelectTrigger>
          <SelectContent>
            {categories.map((cat) => (
              <SelectItem key={cat.name} value={cat.name}>
                {cat.name}
                <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                  {cat.sections.length}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Desktop rail */}
        <aside className="hidden md:flex w-56 shrink-0 flex-col border-r border-border">
          <nav className="flex flex-col gap-px p-2">
            {categories.map((cat) => {
              const active = cat.name === activeCategory;
              return (
                <Link
                  key={cat.name}
                  to={{ search: `?category=${encodeURIComponent(cat.name)}` }}
                  className={cn(
                    "group relative flex items-center justify-between gap-2",
                    "h-8 px-2.5 rounded-md text-sm leading-none",
                    "transition-[background-color,color] duration-(--duration-fast) ease-(--ease-out)",
                    active
                      ? "bg-foreground/8 text-foreground font-medium"
                      : "text-foreground/75 hover:bg-foreground/5 hover:text-foreground",
                  )}
                >
                  {active && (
                    <span
                      aria-hidden
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-r-full bg-(--signal)"
                    />
                  )}
                  <span className="truncate">{cat.name}</span>
                  <span className="font-mono text-[10.5px] text-muted-foreground">
                    {cat.sections.length}
                  </span>
                </Link>
              );
            })}
          </nav>
        </aside>

        {/* Content pane */}
        <main className="flex-1 min-w-0 overflow-y-auto">
          <div className="px-4 py-4 md:px-6 md:py-6 space-y-3">
            {current && current.name === "Services" ? (
              <ServiceToggles sections={current.sections} />
            ) : current ? (
              <>
                {current.sections.map((section) => (
                  <ConfigSection key={section.namespace} section={section} />
                ))}
                {/* Plugins can contribute admin-scoped panels to a
                    category via a "settings.<category>" slot. The slot
                    only renders panels whose plugin declared
                    required_role="admin", filtered server-side. */}
                <PluginPanelSlot
                  slot={`settings.${current.name.toLowerCase()}`}
                />
              </>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}
