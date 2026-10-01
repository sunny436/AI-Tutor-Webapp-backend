import { apiBaseUrl, authSecret } from "@/lib/server/config";
import { handleSessionExpired } from "@/lib/server/expired";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: Request): Promise<Response> {
  return handleSessionExpired(request, { apiBaseUrl: apiBaseUrl(), cookieSecret: authSecret() });
}
