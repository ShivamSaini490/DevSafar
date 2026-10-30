const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const CSRF_COOKIE_NAME = 'csrf_token'
const SAFE_METHODS = new Set(['GET', 'HEAD'])

export interface ApiErrorDetail {
  location: string
  type: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId?: string
  readonly details?: ApiErrorDetail[]

  constructor(status: number, code: string, message: string, requestId?: string, details?: ApiErrorDetail[]) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
  }
}

export function readCookie(name: string): string | null {
  const prefix = `${name}=`
  const match = document.cookie.split('; ').find((cookie) => cookie.startsWith(prefix))
  return match ? decodeURIComponent(match.slice(prefix.length)) : null
}

/** The CSRF cookie is the only auth cookie JavaScript can see, so it doubles as a "maybe signed in" hint. */
export function hasSessionHint(): boolean {
  return readCookie(CSRF_COOKIE_NAME) !== null
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null)
  const error = body?.error
  if (error?.message) {
    return new ApiError(response.status, error.code, error.message, error.request_id, error.details)
  }
  return new ApiError(response.status, 'unexpected_response', 'DevSafar could not finish that request. Please try again.')
}

export async function apiRequest<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (!SAFE_METHODS.has(method)) {
    const csrfToken = readCookie(CSRF_COOKIE_NAME)
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken
    }
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach DevSafar. Check your connection and try again.')
  }

  if (!response.ok) {
    throw await toApiError(response)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}
