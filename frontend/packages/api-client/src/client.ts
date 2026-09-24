/** Request configuration for the AVA API client. */

export interface ApiClientConfig {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}

export type ConnectivityStatus = "reachable" | "unavailable";

const connectivityListeners = new Set<(status: ConnectivityStatus) => void>();

/**
 * Subscribe to transport reachability reported by every ApiClient instance.
 * HTTP responses mean the backend was reached, including non-2xx responses;
 * only failures to obtain a response are unavailable.
 */
export function subscribeConnectivity(
  listener: (status: ConnectivityStatus) => void,
): () => void {
  connectivityListeners.add(listener);
  return () => connectivityListeners.delete(listener);
}

function reportConnectivity(status: ConnectivityStatus): void {
  for (const listener of connectivityListeners) listener(status);
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
    // FormData bodies carry a runtime-generated multipart boundary; the client
    // must not inject a JSON Content-Type (it would break the upload). All
    // other request bodies remain JSON by convention.
    const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
    if (init.body != null && !isFormData && !("Content-Type" in headers)) {
      headers["Content-Type"] = "application/json";
    }

    try {
      const response = await this.fetchImpl(url, {
        ...init,
        signal: controller.signal,
        headers,
      });

      // A response (even 4xx/5xx) proves that the backend is reachable.
      reportConnectivity("reachable");

      if (!response.ok) {
        throw new ApiError(
          `Request failed: ${response.status}`,
          response.status,
          await parseErrorBody(response),
        );
      }

      return response;
    } catch (error) {
      // ApiError is an HTTP response, not a transport failure.
      if (!(error instanceof ApiError)) reportConnectivity("unavailable");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  /**
   * Issue a request and return the binary response body as a Blob.
   *
   * Explicit response mode for binary endpoints: non-2xx responses are
   * handled exactly like `request()` (the backend JSON error body is parsed
   * into an `ApiError`), and only successful responses reach blob decoding.
   * Callers on Web/Desktop/Native runtimes read the resulting Blob directly;
   * no Base64 or JSON round-trip happens here.
   */
  async requestBlob(path: string, init: RequestInit = {}): Promise<Blob> {
    return (await this.request(path, init)).blob();
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
