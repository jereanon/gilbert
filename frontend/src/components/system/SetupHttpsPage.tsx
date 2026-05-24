import { useEffect, useState } from "react";
import { fetchTlsInfo, certDownloadUrl, type TlsInfo } from "@/api/tls";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/PageHeader";

export function SetupHttpsPage() {
  const [info, setInfo] = useState<TlsInfo | null | "loading">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTlsInfo()
      .then(setInfo)
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
        setInfo(null);
      });
  }, []);

  if (info === "loading") {
    return (
      <div>
        <PageHeader eyebrow="SYSTEM" title="Set up HTTPS" />
        <div className="mx-auto max-w-3xl px-6 py-6 text-sm text-muted-foreground">
          Loading…
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="SYSTEM"
        title="Set up HTTPS"
        description="Gilbert generated a self-signed certificate so browsers can grant microphone and camera access on the LAN. Trust the certificate on each device once."
      />

      <div className="mx-auto max-w-3xl space-y-4 px-6 py-6">
        {info === null && (
          <Card>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                HTTPS is disabled or the certificate is not available.
              </p>
              {error && (
                <p className="mt-2 text-sm text-destructive">{error}</p>
              )}
            </CardContent>
          </Card>
        )}

        {info !== null && (
          <>
            <Card>
              <CardHeader>
                <CardTitle>Certificate</CardTitle>
                <CardDescription>Active server certificate</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div>
                  <div className="text-muted-foreground text-xs mb-1">
                    SHA-256 fingerprint
                  </div>
                  <code className="font-mono break-all text-xs">
                    {info.sha256_fingerprint}
                  </code>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs mb-1">
                    Valid until
                  </div>
                  <div>{new Date(info.not_valid_after).toLocaleDateString()}</div>
                </div>
                <div>
                  <div className="text-muted-foreground text-xs mb-1">
                    Covers
                  </div>
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {info.san.map((s) => (
                      <code
                        key={s}
                        className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs"
                      >
                        {s}
                      </code>
                    ))}
                  </div>
                </div>
                <div className="pt-1">
                  <a href={certDownloadUrl()} download="gilbert.crt">
                    <Button variant="outline" size="sm">
                      Download gilbert.crt
                    </Button>
                  </a>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Install on this device</CardTitle>
                <CardDescription>
                  Open the collapsible section for your operating system and
                  follow the steps after downloading the certificate above.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <OsSection title="macOS">
                  <ol className="list-decimal space-y-1 pl-5">
                    <li>Open Keychain Access.</li>
                    <li>
                      Drag <code className="font-mono text-xs">gilbert.crt</code>{" "}
                      into the <em>System</em> keychain.
                    </li>
                    <li>
                      Double-click the new entry → expand <em>Trust</em> → set{" "}
                      <em>When using this certificate</em> to{" "}
                      <em>Always Trust</em>.
                    </li>
                    <li>Close and re-authenticate. Restart the browser.</li>
                  </ol>
                </OsSection>
                <OsSection title="iOS / iPadOS">
                  <ol className="list-decimal space-y-1 pl-5">
                    <li>
                      AirDrop or email the{" "}
                      <code className="font-mono text-xs">gilbert.crt</code> file
                      to the device, then tap it.
                    </li>
                    <li>
                      Open{" "}
                      <em>Settings → General → VPN &amp; Device Management</em>.
                      Tap the downloaded profile → Install.
                    </li>
                    <li>
                      Open{" "}
                      <em>
                        Settings → General → About → Certificate Trust Settings
                      </em>
                      .
                    </li>
                    <li>Toggle on <em>Gilbert (self-signed)</em>.</li>
                  </ol>
                </OsSection>
                <OsSection title="Android">
                  <ol className="list-decimal space-y-1 pl-5">
                    <li>
                      Download{" "}
                      <code className="font-mono text-xs">gilbert.crt</code> on
                      the device.
                    </li>
                    <li>
                      Open{" "}
                      <em>
                        Settings → Security &amp; privacy → More security
                        settings → Encryption &amp; credentials → Install a
                        certificate → CA certificate
                      </em>
                      .
                    </li>
                    <li>Acknowledge the warning and pick the file.</li>
                  </ol>
                </OsSection>
                <OsSection title="Windows">
                  <ol className="list-decimal space-y-1 pl-5">
                    <li>
                      Double-click{" "}
                      <code className="font-mono text-xs">gilbert.crt</code> →
                      Install Certificate.
                    </li>
                    <li>Choose <em>Local Machine</em> → Next.</li>
                    <li>
                      Pick <em>Place all certificates in the following store</em>{" "}
                      → Browse → <em>Trusted Root Certification Authorities</em>.
                    </li>
                    <li>Finish. Restart the browser.</li>
                  </ol>
                </OsSection>
                <OsSection title="Linux (Chrome / Firefox)">
                  <ol className="list-decimal space-y-1 pl-5">
                    <li>
                      <strong>Chrome</strong>: visit{" "}
                      <code className="font-mono text-xs">
                        chrome://certificate-manager
                      </code>{" "}
                      → <em>Authorities</em> → Import{" "}
                      <code className="font-mono text-xs">gilbert.crt</code> →
                      check <em>Trust this certificate for identifying websites</em>.
                    </li>
                    <li>
                      <strong>Firefox</strong>:{" "}
                      <em>
                        Settings → Privacy &amp; Security → Certificates → View
                        Certificates → Authorities → Import
                      </em>
                      . Trust for identifying websites.
                    </li>
                  </ol>
                </OsSection>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

function OsSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details className="rounded border border-border p-3">
      <summary className="cursor-pointer font-medium">{title}</summary>
      <div className="pt-2">{children}</div>
    </details>
  );
}
