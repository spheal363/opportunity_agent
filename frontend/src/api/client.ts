import type { ApiResponse } from '../types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api';

/** VITE_USE_MOCK=true の間は Backend を呼ばず Mock Data を返す。 */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

/** 画面のヘッダーに出すデータ元の表示。分岐を画面側に持ち込まないためここで決める。 */
export const DATA_SOURCE_LABEL = USE_MOCK ? 'MOCK · サンプルデータ' : 'Backend 接続中';

/** Backend が返したエラー封筒をそのまま持つ例外。 */
export class ApiRequestError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiRequestError';
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch {
    throw new ApiRequestError('NETWORK_ERROR', 'Backend に接続できませんでした', 0);
  }

  let body: ApiResponse<T>;
  try {
    body = (await res.json()) as ApiResponse<T>;
  } catch {
    throw new ApiRequestError('INVALID_RESPONSE', 'レスポンスを解釈できませんでした', res.status);
  }

  if (!body.success) {
    throw new ApiRequestError(body.error.code, body.error.message, res.status);
  }
  return body.data;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  put: <T>(path: string, json: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(json) }),
  post: <T>(path: string, json?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: json === undefined ? undefined : JSON.stringify(json),
    }),
};
