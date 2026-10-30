import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest, hasSessionHint, readCookie } from './apiClient.ts'

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('apiClient', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('document', { cookie: 'theme=dark; csrf_token=abc%20123' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it('reads cookies and treats the CSRF cookie as a session hint', () => {
    expect(readCookie('csrf_token')).toBe('abc 123')
    expect(readCookie('missing')).toBeNull()
    expect(hasSessionHint()).toBe(true)
  })

  it('sends credentials and the CSRF header on POST', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }))
    await apiRequest('/api/v1/auth/logout', { method: 'POST', body: { a: 1 } })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.credentials).toBe('include')
    expect(init.headers['X-CSRF-Token']).toBe('abc 123')
    expect(init.headers['Content-Type']).toBe('application/json')
  })

  it('does not attach the CSRF header to GET or for guests', async () => {
    fetchMock.mockImplementation(async () => jsonResponse(200, {}))
    await apiRequest('/api/v1/users/me')
    expect(fetchMock.mock.calls[0][1].headers['X-CSRF-Token']).toBeUndefined()

    vi.stubGlobal('document', { cookie: '' })
    await apiRequest('/api/v1/chat/temporary', { method: 'POST', body: {} })
    expect(fetchMock.mock.calls[1][1].headers['X-CSRF-Token']).toBeUndefined()
  })

  it('maps the backend error envelope to ApiError', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(409, {
        error: { code: 'email_already_registered', message: 'Email is already registered.', request_id: 'r1' },
      }),
    )

    const error = await apiRequest('/api/v1/auth/signup', { method: 'POST', body: {} }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, code: 'email_already_registered', requestId: 'r1' })
  })

  it('survives a non-JSON error and a network failure', async () => {
    fetchMock.mockResolvedValueOnce(new Response('Bad Gateway', { status: 502 }))
    await expect(apiRequest('/x')).rejects.toMatchObject({ status: 502, code: 'unexpected_response' })

    fetchMock.mockRejectedValueOnce(new TypeError('failed'))
    await expect(apiRequest('/x')).rejects.toMatchObject({ status: 0, code: 'network_error' })
  })

  it('returns undefined for 204', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(apiRequest('/x', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})
