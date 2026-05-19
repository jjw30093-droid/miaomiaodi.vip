export const NEXT_PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

export const SESSION_REVOKED_EVENT = 'auth:session-revoked';

export interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean>;
  token?: string;
}

class ApiClient {
  private baseURL: string;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  private async fetch<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { params, token, headers, ...customOptions } = options;

    let url = `${this.baseURL}${endpoint}`;
    if (params) {
      const searchParams = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        searchParams.append(key, String(value));
      });
      url += `?${searchParams.toString()}`;
    }

    const authHeaders: HeadersInit = {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
      ...headers,
    };

    const config: RequestInit = {
      ...customOptions,
      headers: authHeaders,
    };

    const response = await fetch(url, config);

    if (!response.ok) {
      // 设备被踢：后端在 401 上附带 X-Session-Revoked: 1
      if (
        response.status === 401 &&
        response.headers.get('x-session-revoked') === '1' &&
        typeof window !== 'undefined'
      ) {
        window.dispatchEvent(new CustomEvent(SESSION_REVOKED_EVENT));
      }

      let errorMessage = response.statusText;
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        // Ignore JSON parse error if text
      }
      throw new Error(`${response.status} - ${errorMessage}`);
    }

    if (response.status === 204) return {} as T;

    return response.json();
  }

  get<T>(endpoint: string, options?: RequestOptions) {
    return this.fetch<T>(endpoint, { ...options, method: 'GET' });
  }

  post<T>(endpoint: string, data: any, options?: RequestOptions) {
    return this.fetch<T>(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  put<T>(endpoint: string, data: any, options?: RequestOptions) {
    return this.fetch<T>(endpoint, {
      ...options,
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  delete<T>(endpoint: string, options?: RequestOptions) {
    return this.fetch<T>(endpoint, { ...options, method: 'DELETE' });
  }

  patch<T>(endpoint: string, data: any, options?: RequestOptions) {
    return this.fetch<T>(endpoint, {
      ...options,
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }
}

export const apiClient = new ApiClient(NEXT_PUBLIC_API_URL);
