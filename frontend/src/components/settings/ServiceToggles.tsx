/**
 * ServiceToggles — flat list of on/off toggles for optional services.
 *
 * Renders as a single card with one row per toggleable service. The
 * "_services" pseudo-namespace exposes one boolean param per service,
 * matching the rest of the config surface.
 */

import { useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useWsApi } from "@/hooks/useWsApi";
import {
  Card,
  CardContent,
  CardEyebrow,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { SaveIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ConfigSection } from "@/types/config";

interface Props {
  sections: ConfigSection[];
}

function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ServiceToggles({ sections }: Props) {
  const queryClient = useQueryClient();
  const api = useWsApi();
  const [localValues, setLocalValues] = useState<Record<string, boolean>>({});
  const [saveStatus, setSaveStatus] = useState<string | null>(null);

  // The _services section has one boolean param per toggleable service.
  const svcSection = sections.find((s) => s.namespace === "_services");

  const merged = useMemo(
    () => ({ ...(svcSection?.values ?? {}), ...localValues }),
    [svcSection?.values, localValues],
  );

  const hasChanges = Object.keys(localValues).length > 0;

  const saveMutation = useMutation({
    mutationFn: () =>
      api.setConfigSection(svcSection!.namespace, localValues),
    onSuccess: () => {
      setLocalValues({});
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaveStatus("Saved — services restarting…");
      setTimeout(() => setSaveStatus(null), 3000);
    },
    onError: () => {
      setSaveStatus("Save failed");
      setTimeout(() => setSaveStatus(null), 3000);
    },
  });

  if (!svcSection) return null;

  return (
    <Card>
      <CardHeader>
        <CardEyebrow>services</CardEyebrow>
        <CardTitle>Optional services</CardTitle>
      </CardHeader>
      <CardContent className="py-2">
        <ul className="divide-y divide-border">
          {svcSection.params.map((p) => {
            const checked = !!merged[p.key];
            return (
              <li
                key={p.key}
                className="flex items-center justify-between gap-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{humanize(p.key)}</div>
                  {p.description ? (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {p.description}
                    </p>
                  ) : null}
                </div>
                <Switch
                  checked={checked}
                  onCheckedChange={(v: boolean) => {
                    setLocalValues((prev) => ({ ...prev, [p.key]: v }));
                    setSaveStatus(null);
                  }}
                />
              </li>
            );
          })}
        </ul>
      </CardContent>
      <CardFooter className="justify-between">
        <div className="text-xs">
          {saveStatus ? (
            <span
              className={cn(
                "font-mono",
                saveStatus.includes("fail")
                  ? "text-destructive"
                  : "text-success",
              )}
            >
              {saveStatus}
            </span>
          ) : hasChanges ? (
            <span className="font-mono text-(--signal)">
              {Object.keys(localValues).length} unsaved
            </span>
          ) : (
            <span className="text-muted-foreground">No changes.</span>
          )}
        </div>
        <Button
          size="sm"
          disabled={!hasChanges || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          <SaveIcon />
          {saveMutation.isPending ? "Saving…" : "Save"}
        </Button>
      </CardFooter>
    </Card>
  );
}
