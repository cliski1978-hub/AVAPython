/** Request configuration for the AVA API client. */

export interface ApiClientConfig {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * The single shared HTTP client for the AVA Python backend.
 *
 * The web, desktop, and mobile applications must not independently duplicate
 * FastAPI request logic; they should use this client.
 */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.fetchImpl = config.fetchImpl ?? ((...args) => fetch(...args));
    this.timeoutMs = config.requestTimeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  async request(path: string, init: RequestInit = {}): Promise<Response> {
    const url = `${this.baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(init.headers as Record<string, string> | undefined),
    };
    if (init.body != null && !("Content-Type" in headers)) {
      headers["Content-Type"] = "application/json";
    }

    try {
      const response = await this.fetchImpl(url, {
        ...init,
        signal: controller.signal,
        headers,
      });

      if (!response.ok) {
        throw new ApiError(
          `Request failed: ${response.status}`,
          response.status,
          await parseErrorBody(response),
        );
      }

      return response;
    } finally {
      clearTimeout(timeout);
    }
  }
}

/** Read an error body once, parsing JSON when possible and falling back to raw text. */
async function parseErrorBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === "") {
    return text;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}