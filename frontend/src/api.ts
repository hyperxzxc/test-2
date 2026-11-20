export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public requestId?: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  key?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const token = sessionStorage.getItem("app-token");
  if (token) headers["X-App-Token"] = token;
  if (key) headers["Idempotency-Key"] = key;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(180000),
    });
  } catch {
    throw new ApiError(
      "Связь с сервером потеряна. Проверьте историю операций перед повтором.",
      "network_error",
    );
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ApiError("Сервер вернул нечитаемый ответ", "invalid_response");
  }
  if (!response.ok) {
    const error = (
      value as {
        error?: {
          message?: string;
          code?: string;
          request_id?: string;
          details?: { field: string; message: string }[];
        };
      }
    ).error;
    const details = error?.details
      ?.map((d) => `${d.field}: ${d.message}`)
      .join("; ");
    throw new ApiError(
      details || error?.message || "Ошибка запроса",
      error?.code || "request_error",
      error?.request_id,
    );
  }
  return value as T;
}

// Keep the same submission key after a lost response, including a browser reload
export function intentKey(scope: string, payload: unknown): string {
  const signature = JSON.stringify(payload);
  const stored = sessionStorage.getItem(`intent:${scope}`);
  if (stored) {
    try {
      const old = JSON.parse(stored) as { signature: string; key: string };
      if (old.signature === signature) return old.key;
    } catch {
      /* Replace invalid session state */
    }
  }
  const key = crypto.randomUUID();
  sessionStorage.setItem(`intent:${scope}`, JSON.stringify({ signature, key }));
  return key;
}
