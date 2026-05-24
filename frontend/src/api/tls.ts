// Option A: use apiFetch + catch ApiError(404) so callers get null for "TLS not configured"
import { apiFetch, ApiError } from "./client";

export interface TlsInfo {
  san: string[];
  not_valid_after: string;
  sha256_fingerprint: string;
}

export async function fetchTlsInfo(): Promise<TlsInfo | null> {
  try {
    return await apiFetch<TlsInfo>("/api/tls/info");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function certDownloadUrl(): string {
  return "/api/tls/cert.crt";
}
